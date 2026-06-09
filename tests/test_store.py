"""Tests for GraphStore."""

from doc_kg.dockg import DocEdge, DocNode
from doc_kg.store import GraphStore


def _make_nodes():
    return [
        DocNode(
            id="doc:notes.md",
            kind="document",
            name="notes",
            title="Notes",
            file_path="notes.md",
            char_start=0,
            char_end=500,
            heading_level=None,
            text="Document summary text.",
        ),
        DocNode(
            id="chunk:notes.md:0000",
            kind="chunk",
            name="chunk:0000",
            title="Introduction",
            file_path="notes.md",
            char_start=0,
            char_end=100,
            heading_level=None,
            text="This is the first chunk of text.",
        ),
        DocNode(
            id="chunk:notes.md:0001",
            kind="chunk",
            name="chunk:0001",
            title="Introduction",
            file_path="notes.md",
            char_start=100,
            char_end=200,
            heading_level=None,
            text="This is the second chunk of text.",
        ),
    ]


def _make_edges():
    return [
        DocEdge(src="doc:notes.md", rel="CONTAINS", dst="chunk:notes.md:0000"),
        DocEdge(src="doc:notes.md", rel="CONTAINS", dst="chunk:notes.md:0001"),
        DocEdge(src="chunk:notes.md:0000", rel="NEXT", dst="chunk:notes.md:0001"),
    ]


def test_store_write_and_read(tmp_path):
    db = tmp_path / "test.sqlite"
    store = GraphStore(db)
    store.write(_make_nodes(), _make_edges(), wipe=True)

    n = store.node("doc:notes.md")
    assert n is not None
    assert n["kind"] == "document"
    assert n["title"] == "Notes"
    store.close()


def test_store_stats(tmp_path):
    db = tmp_path / "test.sqlite"
    store = GraphStore(db)
    store.write(_make_nodes(), _make_edges(), wipe=True)

    s = store.stats()
    assert s["total_nodes"] == 3
    assert s["total_edges"] == 3
    assert s["node_counts"]["document"] == 1
    assert s["node_counts"]["chunk"] == 2
    store.close()


def test_store_query_nodes_by_kind(tmp_path):
    db = tmp_path / "test.sqlite"
    store = GraphStore(db)
    store.write(_make_nodes(), _make_edges(), wipe=True)

    chunks = store.query_nodes(kinds=["chunk"])
    assert len(chunks) == 2
    assert all(n["kind"] == "chunk" for n in chunks)
    store.close()


def test_store_expand(tmp_path):
    db = tmp_path / "test.sqlite"
    store = GraphStore(db)
    store.write(_make_nodes(), _make_edges(), wipe=True)

    meta = store.expand({"doc:notes.md"}, hop=1, rels=("CONTAINS",))
    assert "chunk:notes.md:0000" in meta
    assert "chunk:notes.md:0001" in meta
    store.close()


def test_store_edges_within(tmp_path):
    db = tmp_path / "test.sqlite"
    store = GraphStore(db)
    store.write(_make_nodes(), _make_edges(), wipe=True)

    node_ids = {"doc:notes.md", "chunk:notes.md:0000", "chunk:notes.md:0001"}
    edges = store.edges_within(node_ids)
    rels = {e["rel"] for e in edges}
    assert "CONTAINS" in rels
    assert "NEXT" in rels
    store.close()


def test_store_wipe(tmp_path):
    db = tmp_path / "test.sqlite"
    store = GraphStore(db)
    store.write(_make_nodes(), _make_edges(), wipe=False)
    store.write(_make_nodes(), _make_edges(), wipe=True)
    s = store.stats()
    assert s["total_nodes"] == 3  # no duplicates after wipe
    store.close()


def test_store_context_manager(tmp_path):
    db = tmp_path / "test.sqlite"
    with GraphStore(db) as store:
        store.write(_make_nodes(), _make_edges(), wipe=True)
        assert store.stats()["total_nodes"] == 3


def test_stamp_meta_writes_required_keys(tmp_path):
    db = tmp_path / "test.sqlite"
    store = GraphStore(db)
    store.write(_make_nodes(), _make_edges(), wipe=True)
    store.stamp_meta("doc_kg", "1.2.3")

    import sqlite3

    con = sqlite3.connect(str(db))
    rows = {k: v for k, v in con.execute("SELECT key, value FROM _kgrag_meta").fetchall()}
    con.close()
    store.close()

    assert rows["builder_name"] == "doc_kg"
    assert rows["builder_version"] == "1.2.3"
    assert "built_at" in rows
    assert rows["built_at"].startswith("20")  # ISO-8601 timestamp


def test_stamp_meta_idempotent(tmp_path):
    db = tmp_path / "test.sqlite"
    store = GraphStore(db)
    store.write(_make_nodes(), _make_edges(), wipe=True)
    store.stamp_meta("doc_kg", "1.0.0")
    store.stamp_meta("doc_kg", "1.0.1")  # second call must not raise or duplicate

    import sqlite3

    con = sqlite3.connect(str(db))
    rows = con.execute("SELECT value FROM _kgrag_meta WHERE key='builder_version'").fetchall()
    con.close()
    store.close()

    assert len(rows) == 1
    assert rows[0][0] == "1.0.1"


def test_fts_lexical_search(tmp_path):
    """rebuild_fts() enables exact-phrase BM25 retrieval over chunk text."""
    db = tmp_path / "test.sqlite"
    store = GraphStore(db)
    store.write(_make_nodes(), _make_edges(), wipe=True)

    # No index yet -> graceful empty result, not an error.
    assert store.has_fts() is False
    assert store.search_lexical("first chunk") == []

    n = store.rebuild_fts(quiet=True)
    assert n == 2  # two chunk nodes; the document node is excluded
    assert store.has_fts() is True

    # Exact-phrase match isolates the right chunk.
    assert store.search_lexical("first chunk") == ["chunk:notes.md:0000"]
    assert store.search_lexical("second chunk") == ["chunk:notes.md:0001"]

    # Apostrophes / punctuation must not break FTS5 query syntax. No exact
    # phrase here ("first chunk of text"), so it falls back to OR-of-terms and
    # still ranks the best lexical match first.
    assert store.search_lexical("first chunk's text!")[0] == "chunk:notes.md:0000"

    # Empty / term-less queries degrade cleanly.
    assert store.search_lexical("   ") == []
    store.close()


def test_fts_rebuild_is_idempotent(tmp_path):
    """rebuild_fts() can be called repeatedly without error or duplication."""
    db = tmp_path / "test.sqlite"
    store = GraphStore(db)
    store.write(_make_nodes(), _make_edges(), wipe=True)
    assert store.rebuild_fts(quiet=True) == 2
    assert store.rebuild_fts(quiet=True) == 2  # drop + rebuild, no duplicates
    assert store.search_lexical("first chunk") == ["chunk:notes.md:0000"]
    store.close()
