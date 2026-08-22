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


# ---------------------------------------------------------------------------
# Node metadata persistence + additive migration
# ---------------------------------------------------------------------------


def _dated_node(node_id="chunk:diary.md:0000", metadata=None):
    return DocNode(
        id=node_id,
        kind="chunk",
        name="chunk:0000",
        title=None,
        file_path="diary.md",
        char_start=0,
        char_end=100,
        heading_level=None,
        text="Up betimes, and to the office.",
        metadata=metadata,
    )


def test_node_metadata_round_trips(tmp_path):
    """Dated corpora live on this store, so it has to carry the temporal keys."""
    store = GraphStore(tmp_path / "t.sqlite")
    store.write([_dated_node(metadata={"occurred_start": "1666-09-02"})], [], wipe=True)
    assert store.node("chunk:diary.md:0000")["metadata"] == {"occurred_start": "1666-09-02"}


def test_node_without_metadata_reads_as_empty_dict(tmp_path):
    store = GraphStore(tmp_path / "t.sqlite")
    store.write([_dated_node()], [], wipe=True)
    assert store.node("chunk:diary.md:0000")["metadata"] == {}


def test_metadata_survives_query_nodes(tmp_path):
    store = GraphStore(tmp_path / "t.sqlite")
    store.write([_dated_node(metadata={"occurred_start": "1666-09-02"})], [], wipe=True)
    nodes = store.query_nodes(kinds=["chunk"])
    assert nodes[0]["metadata"]["occurred_start"] == "1666-09-02"


def test_metadata_survives_nodes_batch(tmp_path):
    store = GraphStore(tmp_path / "t.sqlite")
    store.write([_dated_node(metadata={"recorded_at": "1666-09-03"})], [], wipe=True)
    batch = store.nodes_batch({"chunk:diary.md:0000"})
    assert batch["chunk:diary.md:0000"]["metadata"] == {"recorded_at": "1666-09-03"}


def test_metadata_updated_on_upsert(tmp_path):
    store = GraphStore(tmp_path / "t.sqlite")
    store.write([_dated_node(metadata={"occurred_start": "1666-09-02"})], [], wipe=True)
    store.write([_dated_node(metadata={"occurred_start": "1666-09-05"})], [])
    assert store.node("chunk:diary.md:0000")["metadata"]["occurred_start"] == "1666-09-05"


def test_corrupt_metadata_does_not_break_the_node(tmp_path):
    store = GraphStore(tmp_path / "t.sqlite")
    store.write([_dated_node()], [], wipe=True)
    store.con.execute("UPDATE nodes SET metadata=? WHERE id=?", ("{bad", "chunk:diary.md:0000"))
    store.con.commit()
    node = store.node("chunk:diary.md:0000")
    assert node["metadata"] == {}
    assert node["kind"] == "chunk"


def test_legacy_db_without_metadata_column_is_migrated(tmp_path):
    """A pre-existing DocKG database must open, not raise 'no such column'.

    The verse columns set this precedent; metadata follows the same additive
    path. Every DocKG-backed KG in the fleet is an existing database.
    """
    import sqlite3

    db = tmp_path / "legacy.sqlite"
    con = sqlite3.connect(str(db))
    con.executescript(
        """
        CREATE TABLE nodes (
          id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL, title TEXT,
          file_path TEXT, char_start INTEGER, char_end INTEGER, heading_level INTEGER,
          text TEXT
        );
        CREATE TABLE edges (
          src TEXT NOT NULL, rel TEXT NOT NULL, dst TEXT NOT NULL, evidence TEXT,
          PRIMARY KEY (src, rel, dst)
        );
        """
    )
    con.execute(
        "INSERT INTO nodes (id, kind, name, file_path) VALUES (?,?,?,?)",
        ("chunk:old.md:0000", "chunk", "old", "old.md"),
    )
    con.commit()
    con.close()

    store = GraphStore(db)
    node = store.node("chunk:old.md:0000")
    assert node is not None
    assert node["name"] == "old"
    assert node["metadata"] == {}

    store.write([_dated_node(metadata={"occurred_start": "1666-09-02"})], [])
    assert store.node("chunk:diary.md:0000")["metadata"]["occurred_start"] == "1666-09-02"


# ---------------------------------------------------------------------------
# Read paths agree — drift guard
# ---------------------------------------------------------------------------
#
# The failure this guards against is silent by construction: a SELECT that
# omits a column yields a node dict missing that key, and a missing
# `metadata` key reads as "this node is undated" rather than raising. It is
# how an unselected `metadata` column reached one of doc_kg's four node read
# paths (`nodes_batch`) before a test caught it. `_NODE_COLUMNS` now drives
# every SELECT and `_row_to_node`, so the paths cannot disagree by
# construction — these pin that they don't, because a future hand-written
# query would not be covered by the constant.


class TestReadPathsAgree:
    def _store_with_node(self, tmp_path):
        store = GraphStore(tmp_path / "g.sqlite")
        store.write(
            [_dated_node(metadata={"occurred_start": "1666-09-02"})],
            [],
            wipe=True,
        )
        return store

    def test_node_and_query_nodes_return_the_same_keys(self, tmp_path):
        store = self._store_with_node(tmp_path)
        single = store.node("chunk:diary.md:0000")
        listed = store.query_nodes()
        store.close()
        assert listed
        assert set(single) == set(listed[0])

    def test_nodes_batch_agrees_too(self, tmp_path):
        """The one path that actually missed `metadata` before this refactor."""
        store = self._store_with_node(tmp_path)
        single = store.node("chunk:diary.md:0000")
        batch = store.nodes_batch({"chunk:diary.md:0000"})
        store.close()
        assert set(single) == set(batch["chunk:diary.md:0000"])

    def test_iter_nodes_agrees_too(self, tmp_path):
        """`iter_nodes` streams `list[dict]` batches, not bare dicts."""
        store = self._store_with_node(tmp_path)
        single = store.node("chunk:diary.md:0000")
        flattened = [n for batch in store.iter_nodes() for n in batch]
        store.close()
        assert flattened
        assert set(single) == set(flattened[0])

    def test_every_declared_column_is_a_key(self, tmp_path):
        """The mapper must expose every column the SELECTs ask for."""
        from doc_kg.store import _NODE_COLUMNS

        store = self._store_with_node(tmp_path)
        node = store.node("chunk:diary.md:0000")
        store.close()
        assert set(node) == set(_NODE_COLUMNS)

    def test_metadata_survives_every_path(self, tmp_path):
        """The key existing is not enough — it must carry the value."""
        store = self._store_with_node(tmp_path)
        paths = {
            "node": store.node("chunk:diary.md:0000"),
            "nodes_batch": store.nodes_batch({"chunk:diary.md:0000"})["chunk:diary.md:0000"],
            "query_nodes": store.query_nodes()[0],
            "iter_nodes": next(iter(store.iter_nodes()))[0],
        }
        store.close()
        for name, node in paths.items():
            assert node["metadata"] == {"occurred_start": "1666-09-02"}, name
