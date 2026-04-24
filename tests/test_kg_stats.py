"""Tests for DocKG.stats() and build_graph stamp integration."""

from doc_kg.dockg import DocEdge, DocNode
from doc_kg.kg import DocKG
from doc_kg.store import GraphStore


def _write_minimal_graph(db_path):
    """Write a small graph with one node of each interesting kind."""
    nodes = [
        DocNode(
            id="doc:a.md",
            kind="document",
            name="a",
            title="A",
            file_path="a.md",
            char_start=0,
            char_end=500,
            heading_level=None,
            text="body",
        ),
        DocNode(
            id="chunk:a.md:0",
            kind="chunk",
            name="chunk:0",
            title="Intro",
            file_path="a.md",
            char_start=0,
            char_end=100,
            heading_level=None,
            text="chunk text",
        ),
        DocNode(
            id="sec:a.md:intro",
            kind="section",
            name="intro",
            title="Intro",
            file_path="a.md",
            char_start=0,
            char_end=100,
            heading_level=1,
            text="section text",
        ),
        DocNode(
            id="topic:ai",
            kind="topic",
            name="ai",
            title="AI",
            file_path=None,
            char_start=None,
            char_end=None,
            heading_level=None,
            text=None,
        ),
        DocNode(
            id="ent:alice",
            kind="entity",
            name="alice",
            title="Alice",
            file_path=None,
            char_start=None,
            char_end=None,
            heading_level=None,
            text=None,
        ),
        DocNode(
            id="kw:python",
            kind="keyword",
            name="python",
            title="python",
            file_path=None,
            char_start=None,
            char_end=None,
            heading_level=None,
            text=None,
        ),
    ]
    edges = [
        DocEdge(src="doc:a.md", rel="CONTAINS", dst="chunk:a.md:0"),
        DocEdge(src="doc:a.md", rel="CONTAINS", dst="sec:a.md:intro"),
    ]
    store = GraphStore(db_path)
    store.write(nodes, edges, wipe=True)
    store.close()


def test_dockg_stats_keys(tmp_path):
    db = tmp_path / "graph.sqlite"
    _write_minimal_graph(db)
    kg = DocKG(corpus_root=tmp_path, db_path=db)
    s = kg.stats()
    kg.close()

    required = {
        "node_count",
        "edge_count",
        "document_count",
        "chunk_count",
        "section_count",
        "topic_count",
        "entity_count",
        "keyword_count",
    }
    assert required <= s.keys()


def test_dockg_stats_counts(tmp_path):
    db = tmp_path / "graph.sqlite"
    _write_minimal_graph(db)
    kg = DocKG(corpus_root=tmp_path, db_path=db)
    s = kg.stats()
    kg.close()

    assert s["node_count"] == 6
    assert s["edge_count"] == 2
    assert s["document_count"] == 1
    assert s["chunk_count"] == 1
    assert s["section_count"] == 1
    assert s["topic_count"] == 1
    assert s["entity_count"] == 1
    assert s["keyword_count"] == 1


def test_dockg_stats_never_raises(tmp_path):
    """stats() on a non-existent DB must not raise — returns zeros."""
    kg = DocKG(corpus_root=tmp_path, db_path=tmp_path / "missing.sqlite")
    s = kg.stats()
    kg.close()
    # Non-existent DB creates an empty schema, so all counts should be 0
    assert s["node_count"] == 0
    assert s["edge_count"] == 0
    assert "error" not in s


def test_build_graph_stamps_meta(tmp_path):
    """build_graph() must write _kgrag_meta after writing the graph."""
    (tmp_path / "doc.md").write_text("# Hello\n\nSome content here.\n")
    db = tmp_path / "graph.sqlite"
    kg = DocKG(corpus_root=tmp_path, db_path=db)
    kg.build_graph(wipe=True)
    kg.close()

    import sqlite3

    con = sqlite3.connect(str(db))
    rows = {k: v for k, v in con.execute("SELECT key, value FROM _kgrag_meta").fetchall()}
    con.close()

    assert rows["builder_name"] == "doc_kg"
    assert rows["builder_version"] != ""
    assert rows["built_at"].startswith("20")
