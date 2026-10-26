"""End-to-end SemanticIndex and DocKG vector-store tests (offline).

Builds a real doc_kg GraphStore with a handful of nodes and runs
``SemanticIndex.build``/``search`` against the sqlite-vec store with a
deterministic fake embedder (no model download). sqlite-vec is the only
backend since 0.29.0; these tests pin where the store lives, that an explicit
``vectors_path`` reaches every reader, and that LanceDB is refused by name.
The LanceDB parity tests and the ANN configuration tests (test_ann_index.py)
went with LanceDB support.
"""

# pylint: disable=redefined-outer-name,missing-function-docstring

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest
from kg_utils.vector_backend import SqliteVecBackend

# sqlite-vec is a core dependency as of 0.20.0; the guard stays as cheap
# insurance for a partial install.
pytest.importorskip("sqlite_vec")

from doc_kg.dockg import DocNode  # noqa: E402
from doc_kg.index import _META_COLUMNS, SemanticIndex, sqlite_backend  # noqa: E402
from doc_kg.kg import DocKG  # noqa: E402
from doc_kg.store import GraphStore

_KEYWORDS = ["whale", "rocket", "bread", "planet"]


class _FakeEmbedder:
    """Deterministic keyword→basis-vector embedder with a tiny per-text salt.

    The keyword dimension (magnitude 1.0) dominates ranking; a small
    hash-derived salt (magnitude ~1e-3, same salt dims) makes every distinct
    text produce a distinct vector, so no two nodes tie on distance (real
    embeddings never tie either).
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


def _index(tmp_path: Path) -> SemanticIndex:
    return SemanticIndex(tmp_path / ".dockg" / "vectors.sqlite", embedder=_FakeEmbedder())


def _dockg(tmp_path: Path, **kwargs) -> DocKG:
    return DocKG(corpus_root=tmp_path, embedder=_FakeEmbedder(), **kwargs)


# ---------------------------------------------------------------------------
# SemanticIndex
# ---------------------------------------------------------------------------


def test_build_and_search(tmp_path, store):
    idx = _index(tmp_path)
    stats = idx.build(store, wipe=True, discover_similar=False, quiet=True)
    assert stats["indexed_rows"] == 8
    assert stats["vectors_path"] == str(tmp_path / ".dockg" / "vectors.sqlite")

    hits = idx.search("tell me about the whale", k=3)
    assert "whale" in hits[0].id  # a whale node ranks first

    # prefilter to chunks only
    chunk_hits = idx.search("rocket", k=4, where="kind = 'chunk'")
    assert chunk_hits and all(h.kind == "chunk" for h in chunk_hits)


def test_build_writes_the_store_and_nothing_else(tmp_path, store):
    _index(tmp_path).build(store, wipe=True, discover_similar=False, quiet=True)
    assert (tmp_path / ".dockg" / "vectors.sqlite").exists()
    assert not (tmp_path / ".dockg" / "lancedb").exists()


def test_default_backend_is_sqlite_vec_at_vectors_path(tmp_path):
    idx = _index(tmp_path)
    be = idx._get_backend()
    assert isinstance(be, SqliteVecBackend)
    assert be.meta_columns == _META_COLUMNS
    assert Path(be.db_path) == tmp_path / ".dockg" / "vectors.sqlite"


def test_explicit_backend_is_used(tmp_path):
    sb = sqlite_backend(tmp_path / "v.sqlite", dim=_FakeEmbedder.dim)
    idx = SemanticIndex(tmp_path / "unused.sqlite", embedder=_FakeEmbedder(), backend=sb)
    assert idx._get_backend() is sb


# ---------------------------------------------------------------------------
# DocKG: where the store lives
# ---------------------------------------------------------------------------


def test_vectors_path_defaults_beside_the_graph(tmp_path):
    """The file the pre-0.29.0 derivation from lancedb_dir produced."""
    kg = _dockg(tmp_path)
    assert kg.vectors_path == tmp_path / ".dockg" / "vectors.sqlite"
    assert kg.vector_store_path == kg.vectors_path


def test_vectors_path_is_the_third_positional_argument(tmp_path):
    """The SDK's (root, db_path, vectors_path) convention."""
    custom = tmp_path / "v.sqlite"
    kg = DocKG(tmp_path, tmp_path / "g.sqlite", custom)
    assert kg.vectors_path == custom


def test_vectors_path_is_normalised_to_path(tmp_path):
    kg = _dockg(tmp_path, vectors_path=str(tmp_path / "custom" / "v.sqlite"))
    assert isinstance(kg.vectors_path, Path)
    assert kg.vectors_path == tmp_path / "custom" / "v.sqlite"


def test_index_writes_to_explicit_vectors_path(tmp_path, store):
    """The override must reach the backend, not just be stored on the object."""
    custom = tmp_path / "elsewhere" / "vectors.sqlite"
    custom.parent.mkdir()
    kg = _dockg(tmp_path, vectors_path=custom)

    kg.index.build(store, wipe=True, discover_similar=False, quiet=True)

    assert custom.exists()
    assert not (tmp_path / ".dockg" / "vectors.sqlite").exists()
    hits = kg.index.search("tell me about the whale", k=3)
    assert "whale" in hits[0].id


def test_stats_counts_vectors_at_explicit_path(tmp_path, store):
    """stats() builds its own backend -- it must honour the override too, or it
    silently reports 0 vectors for a corpus that has them."""
    custom = tmp_path / "elsewhere" / "vectors.sqlite"
    custom.parent.mkdir()
    kg = _dockg(tmp_path, vectors_path=custom)
    kg.index.build(store, wipe=True, discover_similar=False, quiet=True)

    assert not (tmp_path / ".dockg" / "vectors.sqlite").exists()
    stats = kg.stats()
    assert stats["vector_count"] == 8
    assert stats["vector_backend"] == "sqlite-vec"


# ---------------------------------------------------------------------------
# DocKG: what was removed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["sqlite-vec", "auto", "sqlite", None])
def test_sqlite_spellings_are_accepted(tmp_path, name):
    assert _dockg(tmp_path, vector_backend=name).vector_backend == "sqlite-vec"


@pytest.mark.parametrize("name", ["lancedb", "lance", "LanceDB"])
def test_lancedb_is_refused_naming_the_removal(tmp_path, name):
    with pytest.raises(ValueError, match=r"removed in doc-kg 0\.29\.0"):
        _dockg(tmp_path, vector_backend=name)


def test_lancedb_is_refused_from_the_environment_too(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCKG_VECTOR_BACKEND", "lancedb")
    with pytest.raises(ValueError, match="removed"):
        _dockg(tmp_path)


def test_an_unknown_backend_is_refused(tmp_path):
    with pytest.raises(ValueError, match="'sqlite-vec' or 'auto'"):
        _dockg(tmp_path, vector_backend="faiss")


def test_lancedb_dir_is_no_longer_accepted(tmp_path):
    """Removed with no deprecation period, as kg_utils dropped it in 0.14.0."""
    with pytest.raises(TypeError, match="lancedb_dir"):
        DocKG(corpus_root=tmp_path, lancedb_dir=tmp_path / "lancedb")  # ty: ignore[unknown-argument]


@pytest.mark.parametrize(
    "name",
    [
        "make_backend",
        "resolve_backend_name",
        "vector_store_path",
        "sqlite_vectors_path",
        "convert_lancedb_to_sqlite",
        "_require_lancedb",
    ],
)
def test_removed_index_functions_are_gone(name):
    import doc_kg.index as index_mod

    assert not hasattr(index_mod, name)
