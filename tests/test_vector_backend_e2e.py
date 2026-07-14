"""End-to-end SemanticIndex tests over both vector backends (offline).

Builds a real doc_kg GraphStore with a handful of nodes and runs
``SemanticIndex.build``/``search`` against both the LanceDB and sqlite-vec
backends with a deterministic fake embedder (no model download). Asserts the
two backends agree on top-k, that the ``where`` prefilter works, and that the
sqlite build writes ``vectors.sqlite`` rather than a LanceDB directory.
"""

# pylint: disable=redefined-outer-name,missing-function-docstring

from __future__ import annotations

import hashlib

import numpy as np
import pytest

# Every test here exercises the sqlite-vec backend; skip the module when the
# optional dependency is absent (CI installs the `sqlite-vec` extra).
pytest.importorskip("sqlite_vec")

from doc_kg.dockg import DocNode  # noqa: E402
from doc_kg.index import (  # noqa: E402
    SemanticIndex,
    convert_lancedb_to_sqlite,
    make_backend,
    resolve_backend_name,
    sqlite_vectors_path,
)
from doc_kg.store import GraphStore

_KEYWORDS = ["whale", "rocket", "bread", "planet"]


class _FakeEmbedder:
    """Deterministic keyword→basis-vector embedder with a tiny per-text salt.

    The keyword dimension (magnitude 1.0) dominates ranking; a small
    hash-derived salt (magnitude ~1e-3, same salt dims) makes every distinct
    text produce a distinct vector, so no two nodes tie on distance — both
    backends then sort identically (real embeddings never tie either).
    """

    dim = len(_KEYWORDS) + 4  # keyword dims + salt dims
    model_name = "fake"

    def embed_texts(self, texts, encode_batch_size: int = 128):
        out = []
        for t in texts:
            v = np.zeros(self.dim, dtype=np.float32)
            low = t.lower()
            for i, kw in enumerate(_KEYWORDS):
                if kw in low:
                    v[i] = 1.0
            digest = hashlib.md5(t.encode()).digest()
            for j in range(4):
                v[len(_KEYWORDS) + j] = (digest[j] % 97) / 1e4
            if not v.any():
                v[0] = 1e-3
            out.append(v.tolist())
        return out

    def embed_query(self, query: str):
        return self.embed_texts([query])[0]


def _populate(store: GraphStore) -> None:
    nodes = []
    for i, kw in enumerate(_KEYWORDS):
        nodes.append(
            DocNode(
                id=f"chunk:{kw}.md:0000",
                kind="chunk",
                name=f"{kw} chunk",
                title=None,
                file_path=f"{kw}.md",
                char_start=0,
                char_end=10,
                heading_level=None,
                text=f"a passage about the {kw} and more {kw}",
            )
        )
        nodes.append(
            DocNode(
                id=f"doc:{kw}.md",
                kind="document",
                name=kw,
                title=kw.title(),
                file_path=f"{kw}.md",
                char_start=None,
                char_end=None,
                heading_level=None,
                text=f"document about {kw}",
            )
        )
    store._upsert_nodes(nodes, quiet=True)


@pytest.fixture
def store(tmp_path):
    s = GraphStore(tmp_path / "graph.sqlite")
    _populate(s)
    yield s
    s.close()


def _index(tmp_path, backend_name):
    lancedb_dir = tmp_path / ".dockg" / "lancedb"
    be = make_backend(
        backend_name, lancedb_dir=lancedb_dir, dim=_FakeEmbedder.dim, table="dockg_nodes"
    )
    return SemanticIndex(lancedb_dir, embedder=_FakeEmbedder(), backend=be)


@pytest.mark.parametrize("backend_name", ["lancedb", "sqlite-vec"])
def test_build_and_search(tmp_path, store, backend_name):
    idx = _index(tmp_path, backend_name)
    stats = idx.build(store, wipe=True, discover_similar=False, quiet=True)
    assert stats["indexed_rows"] == 8

    hits = idx.search("tell me about the whale", k=3)
    assert "whale" in hits[0].id  # a whale node ranks first

    # prefilter to chunks only
    chunk_hits = idx.search("rocket", k=4, where="kind = 'chunk'")
    assert chunk_hits and all(h.kind == "chunk" for h in chunk_hits)


def test_backends_agree(tmp_path, store):
    # build both in isolated dirs
    lidx = _index(tmp_path / "ldir", "lancedb")
    sidx = _index(tmp_path / "sdir", "sqlite-vec")
    lidx.build(store, wipe=True, discover_similar=False, quiet=True)
    sidx.build(store, wipe=True, discover_similar=False, quiet=True)
    for q in ("whale", "rocket", "bread"):
        lids = [h.id for h in lidx.search(q, k=4)]
        sids = [h.id for h in sidx.search(q, k=4)]
        assert lids == sids, f"{q}: {lids} != {sids}"


def test_sqlite_writes_sidecar_not_lancedb(tmp_path, store):
    idx = _index(tmp_path, "sqlite-vec")
    idx.build(store, wipe=True, discover_similar=False, quiet=True)
    assert sqlite_vectors_path(tmp_path / ".dockg" / "lancedb").exists()
    assert not (tmp_path / ".dockg" / "lancedb").exists()


def test_resolve_backend_name_auto(tmp_path):
    lancedb_dir = tmp_path / ".dockg" / "lancedb"
    # nothing exists yet -> fresh build picks sqlite-vec
    assert resolve_backend_name("auto", lancedb_dir=lancedb_dir) == "sqlite-vec"
    assert resolve_backend_name(None, lancedb_dir=lancedb_dir) == "sqlite-vec"
    # only lancedb exists -> keep lancedb (don't silently switch)
    lancedb_dir.mkdir(parents=True)
    assert resolve_backend_name("auto", lancedb_dir=lancedb_dir) == "lancedb"
    # once converted (sidecar present) -> sqlite-vec wins
    sqlite_vectors_path(lancedb_dir).write_bytes(b"")
    assert resolve_backend_name("auto", lancedb_dir=lancedb_dir) == "sqlite-vec"
    # explicit names pass through
    assert resolve_backend_name("lancedb", lancedb_dir=lancedb_dir) == "lancedb"
    assert resolve_backend_name("sqlite-vec", lancedb_dir=lancedb_dir) == "sqlite-vec"


def test_convert_lancedb_to_sqlite_matches(tmp_path, store):
    # Build a LanceDB index, convert it, and confirm the sqlite store returns
    # the same top-k as the original LanceDB index (no re-embedding).
    lidx = _index(tmp_path, "lancedb")
    lidx.build(store, wipe=True, discover_similar=False, quiet=True)

    lancedb_dir = tmp_path / ".dockg" / "lancedb"
    stats = convert_lancedb_to_sqlite(lancedb_dir, table="dockg_nodes", quiet=True)
    assert stats["validated"] is True
    assert stats["converted"] == 8
    assert sqlite_vectors_path(lancedb_dir).exists()

    sbe = make_backend(
        "sqlite-vec", lancedb_dir=lancedb_dir, dim=_FakeEmbedder.dim, table="dockg_nodes"
    )
    sidx = SemanticIndex(lancedb_dir, embedder=_FakeEmbedder(), backend=sbe)
    for q in ("whale", "rocket", "bread"):
        lids = [h.id for h in lidx.search(q, k=4)]
        sids = [h.id for h in sidx.search(q, k=4)]
        assert lids == sids, f"{q}: {lids} != {sids}"
