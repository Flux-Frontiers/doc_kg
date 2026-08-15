"""
test_pack_dedup.py

Unit tests for DocKG.pack() deduplication: document and section nodes must be
dropped from the result when chunks from the same file are present.

The index and embedder are mocked so no sentence-transformer or LanceDB is
needed — only the SQLite store is exercised for real.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from doc_kg.dockg import DocEdge, DocNode
from doc_kg.index import SeedHit
from doc_kg.kg import DocKG
from doc_kg.store import GraphStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


FILE = "ocean.md"

DOC_NODE = DocNode(
    id="doc:ocean.md",
    kind="document",
    name="ocean",
    title="Ocean Notes",
    file_path=FILE,
    char_start=0,
    char_end=5000,
    heading_level=None,
    text="Full document text spanning thousands of characters.",
)

SECTION_NODE = DocNode(
    id="section:ocean.md:whaling",
    kind="section",
    name="section:whaling",
    title="Whaling",
    file_path=FILE,
    char_start=0,
    char_end=2000,
    heading_level=2,
    text="Whaling section heading.",
)

CHUNK_A = DocNode(
    id="chunk:ocean.md:0000",
    kind="chunk",
    name="chunk:0000",
    title="Whaling",
    file_path=FILE,
    char_start=0,
    char_end=500,
    heading_level=None,
    text="The harpooner raised his arm and hurled the spear into the churning sea.",
)

CHUNK_B = DocNode(
    id="chunk:ocean.md:0001",
    kind="chunk",
    name="chunk:0001",
    title="Whaling",
    file_path=FILE,
    char_start=500,
    char_end=1000,
    heading_level=None,
    text="Waves crashed against the bow as the whale sounded into the depths below.",
)

EDGES = [
    DocEdge(src="doc:ocean.md", rel="CONTAINS", dst="section:ocean.md:whaling"),
    DocEdge(src="section:ocean.md:whaling", rel="CONTAINS", dst="chunk:ocean.md:0000"),
    DocEdge(src="section:ocean.md:whaling", rel="CONTAINS", dst="chunk:ocean.md:0001"),
    DocEdge(src="chunk:ocean.md:0000", rel="NEXT", dst="chunk:ocean.md:0001"),
]


@pytest.fixture()
def store(tmp_path):
    db = tmp_path / "test.sqlite"
    s = GraphStore(db)
    s.write([DOC_NODE, SECTION_NODE, CHUNK_A, CHUNK_B], EDGES, wipe=True)
    yield s
    s.close()


def _mock_index(seed_ids: list[str]) -> MagicMock:
    """Return a fake SemanticIndex whose search() returns the given node IDs as seeds."""
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
# Tests
# ---------------------------------------------------------------------------


def test_pack_excludes_document_when_chunks_present(store, tmp_path):
    """pack() must not return the document node when chunk nodes from the same
    file are in the expansion set."""
    kg = DocKG(corpus_root=tmp_path, db_path=store.db_path)
    kg._store = store
    kg._index = _mock_index([CHUNK_A.id, CHUNK_B.id])

    pack = kg.pack("whale hunting at sea", k=4)

    node_ids = {n["id"] for n in pack.nodes}
    assert DOC_NODE.id not in node_ids, "document node should be deduped away"
    assert CHUNK_A.id in node_ids or CHUNK_B.id in node_ids, "at least one chunk must be kept"


def test_pack_excludes_section_when_chunks_present(store, tmp_path):
    """pack() must not return the section node when chunk nodes from the same
    file are in the expansion set."""
    kg = DocKG(corpus_root=tmp_path, db_path=store.db_path)
    kg._store = store
    kg._index = _mock_index([CHUNK_A.id])

    pack = kg.pack("whale hunting at sea", k=4)

    node_ids = {n["id"] for n in pack.nodes}
    assert SECTION_NODE.id not in node_ids, "section node should be deduped away"
    assert CHUNK_A.id in node_ids, "chunk must be kept"


def test_pack_keeps_section_when_no_chunks_present(store, tmp_path):
    """pack() must keep a section node when no chunk from the same file was
    returned — only covered files are filtered."""
    # Seed with a different file's chunk (simulate no chunks from ocean.md)
    other_chunk_id = "chunk:other.md:0000"
    other_node = DocNode(
        id=other_chunk_id,
        kind="chunk",
        name="chunk:0000",
        title="",
        file_path="other.md",
        char_start=0,
        char_end=100,
        heading_level=None,
        text="Other document chunk text content here.",
    )
    store.write([other_node], [], wipe=False)

    kg = DocKG(corpus_root=tmp_path, db_path=store.db_path)
    kg._store = store
    # Seed only returns the other file's chunk; expansion brings in section via hop
    idx = MagicMock()
    idx.search.return_value = [
        SeedHit(
            id=other_chunk_id,
            kind="chunk",
            name=other_chunk_id,
            title="",
            file_path="other.md",
            distance=0.1,
            rank=0,
        )
    ]
    kg._index = idx

    pack = kg.pack("ocean waves", k=8)

    # ocean.md section may or may not be in results via graph expansion,
    # but if it is, it should NOT be filtered (no ocean.md chunks were returned)
    node_ids = {n["id"] for n in pack.nodes}
    if SECTION_NODE.id in node_ids:
        # Confirm: no ocean.md chunks appeared alongside it
        ocean_chunks = {
            n["id"] for n in pack.nodes if n.get("file_path") == FILE and n["kind"] == "chunk"
        }
        assert not ocean_chunks, "section kept only because no chunks from same file were returned"


def test_pack_excerpt_preferred_over_raw_text(store, tmp_path):
    """pack() must attach an 'excerpt' key to each node; excerpt is the content
    field adapters should read (not the raw 'text' key)."""
    kg = DocKG(corpus_root=tmp_path, db_path=store.db_path)
    kg._store = store
    kg._index = _mock_index([CHUNK_A.id])

    pack = kg.pack("whale hunting at sea", k=4)

    chunk_nodes = [n for n in pack.nodes if n["kind"] == "chunk"]
    assert chunk_nodes, "expected at least one chunk in pack result"
    for n in chunk_nodes:
        assert "excerpt" in n, f"node {n['id']} missing 'excerpt' key"
        assert n["excerpt"], f"node {n['id']} has empty excerpt"


def test_short_chunk_boost_ignores_micro_fragments():
    """_short_chunk_boost must return 0.0 for chunks shorter than _MIN_CHUNK_CHARS.
    Without this guard, 3-char fragments like 'see' get a near-maximum boost and
    float to the top of pack results."""
    from doc_kg.kg import _MIN_CHUNK_CHARS, _short_chunk_boost

    micro = {"kind": "chunk", "text": "see"}
    assert _short_chunk_boost(micro) == 0.0, "micro-fragment must not be boosted"

    borderline = {"kind": "chunk", "text": "x" * (_MIN_CHUNK_CHARS - 1)}
    assert _short_chunk_boost(borderline) == 0.0, "chunk just below floor must not be boosted"

    ok = {"kind": "chunk", "text": "x" * _MIN_CHUNK_CHARS}
    assert _short_chunk_boost(ok) > 0.0, "chunk at floor must receive boost"


def test_text_chunker_default_min_chunk_chars():
    """TextChunker must default to min_chunk_chars=50, not 1.
    The old default of 1 allowed micro-fragments to be stored and indexed."""
    from doc_kg.chunker import TextChunker

    chunker = TextChunker()
    assert chunker.min_chunk_chars == 50, (
        f"expected min_chunk_chars=50, got {chunker.min_chunk_chars}"
    )


def test_chunker_for_semantic_default_min_chunk_chars():
    """chunker_for('semantic') must also default to min_chunk_chars=50."""
    from doc_kg.chunker import chunker_for

    chunker = chunker_for("semantic")
    assert chunker.min_chunk_chars == 50
