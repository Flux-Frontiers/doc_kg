"""
test_traced_pack.py

Unit tests for DocKG provenance tracing (``DocKG.pack(traced=True)``).

Covers the pure path-tracing helpers (``_trace_paths``, ``_hop_label``,
``_node_quote``, ``_render_path``) and an end-to-end pack that attaches a
seed → … → node provenance path with a quoted line per hop.

The index/embedder are mocked so no sentence-transformer or LanceDB is needed —
only the SQLite store is exercised for real.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from doc_kg.dockg import DocEdge, DocNode
from doc_kg.index import SeedHit
from doc_kg.kg import (
    DocKG,
    _hop_label,
    _node_quote,
    _render_path,
    _trace_paths,
)
from doc_kg.store import GraphStore

# ---------------------------------------------------------------------------
# Fixtures — a tiny document: doc → section → chunk_a → (NEXT) chunk_b,
# with chunk_a SIMILAR_TO chunk_b.
# ---------------------------------------------------------------------------

FILE = "voyage.md"

DOC = DocNode(
    id="doc:voyage.md",
    kind="document",
    name="voyage",
    title="Voyage Log",
    file_path=FILE,
    char_start=0,
    char_end=4000,
    heading_level=None,
    text="Full voyage log.",
)
SECTION = DocNode(
    id="section:voyage.md:storm",
    kind="section",
    name="section:storm",
    title="The Storm",
    file_path=FILE,
    char_start=0,
    char_end=2000,
    heading_level=2,
    text="The Storm.",
)
CHUNK_A = DocNode(
    id="chunk:voyage.md:0000",
    kind="chunk",
    name="chunk:0000",
    title="The Storm",
    file_path=FILE,
    char_start=100,
    char_end=400,
    heading_level=None,
    text="The gale tore the mainsail to ribbons. Rain lashed the deck without mercy.",
)
CHUNK_B = DocNode(
    id="chunk:voyage.md:0001",
    kind="chunk",
    name="chunk:0001",
    title="The Storm",
    file_path=FILE,
    char_start=400,
    char_end=700,
    heading_level=None,
    text="By dawn the sea lay flat and the survivors counted their losses.",
)

EDGES = [
    DocEdge(src=DOC.id, rel="CONTAINS", dst=SECTION.id),
    DocEdge(src=SECTION.id, rel="CONTAINS", dst=CHUNK_A.id),
    DocEdge(src=SECTION.id, rel="CONTAINS", dst=CHUNK_B.id),
    DocEdge(src=CHUNK_A.id, rel="NEXT", dst=CHUNK_B.id),
    DocEdge(
        src=CHUNK_A.id,
        rel="SIMILAR_TO",
        dst=CHUNK_B.id,
        evidence={"similarity": 0.91},
    ),
]

_NODE_MAP = {n.id: {**n.__dict__} for n in (DOC, SECTION, CHUNK_A, CHUNK_B)}
_EDGE_DICTS = [{"src": e.src, "rel": e.rel, "dst": e.dst, "evidence": e.evidence} for e in EDGES]


@pytest.fixture()
def store(tmp_path):
    db = tmp_path / "voyage.sqlite"
    s = GraphStore(db)
    s.write([DOC, SECTION, CHUNK_A, CHUNK_B], EDGES, wipe=True)
    yield s
    s.close()


def _mock_index(seed_ids):
    hits = [
        SeedHit(
            id=nid,
            kind="chunk",
            name=nid,
            title="",
            file_path=FILE,
            distance=float(i) * 0.1,
            rank=i,
        )
        for i, nid in enumerate(seed_ids)
    ]
    idx = MagicMock()
    idx.search.return_value = hits
    return idx


# ---------------------------------------------------------------------------
# Pure helper tests
# ---------------------------------------------------------------------------


def test_hop_label_uses_evidence():
    assert _hop_label("SIMILAR_TO", {"similarity": 0.91}) == "similar to (0.91)"
    assert _hop_label("REFERENCES", {"href": "other.md"}) == "links to (other.md)"
    assert _hop_label("CONTAINS", None) == "contains"
    assert _hop_label("MYSTERY_REL", None) == "mystery rel"


def test_node_quote_first_sentence_and_cite():
    quote = _node_quote(_NODE_MAP[CHUNK_A.id])
    assert quote is not None
    # First sentence only, not the whole chunk.
    assert quote["text"] == "The gale tore the mainsail to ribbons."
    assert quote["cite"] == "voyage.md:100"


def test_node_quote_none_without_text():
    assert _node_quote({"kind": "topic", "title": "storms"}) is None


def test_trace_paths_reconstructs_seed_to_target():
    # Seed at the section; target the deepest chunk.
    paths = _trace_paths(
        seed_ids={SECTION.id},
        node_map=_NODE_MAP,
        edges=_EDGE_DICTS,
        targets={CHUNK_B.id},
    )
    chain = paths[CHUNK_B.id]
    ids = [step["id"] for step in chain]
    # Shortest path: section -CONTAINS-> chunk_b (direct), seed first.
    assert ids[0] == SECTION.id
    assert ids[-1] == CHUNK_B.id
    assert chain[0]["rel"] is None  # seed has no incoming edge
    assert chain[-1]["rel"] == "CONTAINS"


def test_trace_paths_seed_is_single_step():
    paths = _trace_paths(
        seed_ids={CHUNK_A.id},
        node_map=_NODE_MAP,
        edges=_EDGE_DICTS,
        targets={CHUNK_A.id},
    )
    assert len(paths[CHUNK_A.id]) == 1
    assert paths[CHUNK_A.id][0]["rel"] is None


def test_trace_paths_omits_unreachable():
    # An isolated node not connected to the seed gets no path.
    node_map = dict(_NODE_MAP)
    node_map["chunk:island.md:0000"] = {
        "id": "chunk:island.md:0000",
        "kind": "chunk",
        "title": "Island",
        "text": "A lonely atoll.",
        "file_path": "island.md",
        "char_start": 0,
    }
    paths = _trace_paths(
        seed_ids={SECTION.id},
        node_map=node_map,
        edges=_EDGE_DICTS,
        targets={"chunk:island.md:0000"},
    )
    assert "chunk:island.md:0000" not in paths


def test_render_path_contains_arrow_and_quote():
    paths = _trace_paths(
        seed_ids={SECTION.id},
        node_map=_NODE_MAP,
        edges=_EDGE_DICTS,
        targets={CHUNK_A.id},
    )
    rendered = _render_path(paths[CHUNK_A.id])
    assert "provenance:" in rendered
    assert "→" in rendered
    assert "The gale tore the mainsail to ribbons." in rendered
    assert "voyage.md:100" in rendered


# ---------------------------------------------------------------------------
# Integration: pack(traced=True)
# ---------------------------------------------------------------------------


def test_pack_traced_attaches_paths(store, tmp_path):
    kg = DocKG(corpus_root=tmp_path, db_path=store.db_path)
    kg._store = store
    kg._index = _mock_index([CHUNK_A.id])

    pack = kg.pack("storm at sea", k=4, hop=2, traced=True)

    assert pack.paths is not None
    # Every returned node should have a provenance path rooted at a seed.
    for node in pack.nodes:
        chain = pack.paths.get(node["id"])
        assert chain, f"missing provenance path for {node['id']}"
        assert chain[-1]["id"] == node["id"]
        assert chain[0]["rel"] is None

    md = pack.to_markdown()
    assert "provenance:" in md
    # to_dict carries paths only when traced.
    assert "paths" in pack.to_dict()


def test_pack_untraced_has_no_paths(store, tmp_path):
    kg = DocKG(corpus_root=tmp_path, db_path=store.db_path)
    kg._store = store
    kg._index = _mock_index([CHUNK_A.id])

    pack = kg.pack("storm at sea", k=4)

    assert pack.paths is None
    assert "paths" not in pack.to_dict()
    assert "provenance:" not in pack.to_markdown()
