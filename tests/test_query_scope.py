"""Tests for query-time scope pushdown (source_path / node-kind filtering).

Covers the SQL/Lance filter builders, the lexical-search pushdown, and the
post-expansion scope guard helpers added to support genre-restricted queries.
"""

from __future__ import annotations

from doc_kg.dockg import DocNode
from doc_kg.kg import _lance_where, _node_in_scope
from doc_kg.store import GraphStore, _node_filter_sql

# ---------------------------------------------------------------------------
# _node_filter_sql — parameterised SQL fragment for the nodes table
# ---------------------------------------------------------------------------


class TestNodeFilterSql:
    def test_empty_returns_no_clause(self):
        assert _node_filter_sql(None, None) == ("", [])

    def test_prefixes_only(self):
        sql, params = _node_filter_sql(("sci-fi/",), None, alias="n")
        assert sql.startswith(" AND ")
        assert "n.file_path LIKE ?" in sql
        assert "ESCAPE" in sql
        assert params == ["sci-fi/%"]

    def test_kinds_only(self):
        sql, params = _node_filter_sql(None, ("chunk", "section"), alias="n")
        assert "n.kind IN (?, ?)" in sql
        assert params == ["chunk", "section"]

    def test_prefixes_and_kinds_combined(self):
        sql, params = _node_filter_sql(("a/", "b/"), ("chunk",), alias="n")
        assert " OR " in sql  # two prefixes OR-combined
        assert params == ["a/%", "b/%", "chunk"]

    def test_like_wildcards_escaped(self):
        # %/_ in a prefix must be matched literally, not as wildcards.
        _, params = _node_filter_sql(("100%_done/",), None)
        assert params == [r"100\%\_done/%"]


# ---------------------------------------------------------------------------
# _lance_where — LanceDB prefilter string
# ---------------------------------------------------------------------------


class TestLanceWhere:
    def test_empty_returns_none(self):
        assert _lance_where(None, None) is None

    def test_prefixes(self):
        where = _lance_where(("sci-fi/",), None)
        assert where == "(file_path LIKE 'sci-fi/%')"

    def test_kinds(self):
        where = _lance_where(None, ("chunk", "section"))
        assert where == "kind IN ('chunk', 'section')"

    def test_combined(self):
        where = _lance_where(("a/",), ("chunk",))
        assert where == "(file_path LIKE 'a/%') AND kind IN ('chunk')"

    def test_single_quotes_escaped(self):
        where = _lance_where(("o'brien/",), None)
        assert "o''brien/" in where


# ---------------------------------------------------------------------------
# _node_in_scope — final post-expansion guard
# ---------------------------------------------------------------------------


class TestNodeInScope:
    def test_unconstrained_matches(self):
        assert _node_in_scope({"file_path": "x", "kind": "topic"}, None, None) is True

    def test_prefix_match(self):
        n = {"file_path": "science-fiction/Dune.md", "kind": "chunk"}
        assert _node_in_scope(n, ("science-fiction/",), None) is True

    def test_prefix_mismatch(self):
        n = {"file_path": "philosophy/Ethics.md", "kind": "chunk"}
        assert _node_in_scope(n, ("science-fiction/",), None) is False

    def test_kind_match_and_mismatch(self):
        n = {"file_path": "a/x.md", "kind": "topic"}
        assert _node_in_scope(n, None, ("chunk", "section")) is False
        assert _node_in_scope(n, None, ("topic",)) is True

    def test_missing_file_path_treated_as_empty(self):
        assert _node_in_scope({"kind": "chunk"}, ("a/",), None) is False


# ---------------------------------------------------------------------------
# search_lexical pushdown — true in-DB filtering
# ---------------------------------------------------------------------------


def _genre_nodes() -> list[DocNode]:
    """Two chunks under different genre subtrees plus a section node."""
    return [
        DocNode(
            id="chunk:sci-fi/dune.md:0",
            kind="chunk",
            name="c0",
            title="Arrakis",
            file_path="science-fiction/dune.md",
            char_start=0,
            char_end=80,
            heading_level=None,
            text="The desert planet spice melange shapes galactic travel.",
        ),
        DocNode(
            id="chunk:phil/ethics.md:0",
            kind="chunk",
            name="c1",
            title="Virtue",
            file_path="philosophy/ethics.md",
            char_start=0,
            char_end=80,
            heading_level=None,
            text="The desert of vice and the mean of virtue and travel of the soul.",
        ),
        DocNode(
            id="section:sci-fi/dune.md:s0",
            kind="section",
            name="s0",
            title="Part One",
            file_path="science-fiction/dune.md",
            char_start=0,
            char_end=200,
            heading_level=1,
            text="Part one covers desert travel and political intrigue on Arrakis.",
        ),
    ]


class TestSearchLexicalPushdown:
    def _store(self, tmp_path):
        store = GraphStore(tmp_path / "g.sqlite")
        store.write(_genre_nodes(), [], wipe=True)
        store.rebuild_fts(quiet=True)
        return store

    def test_unscoped_returns_both_genres(self, tmp_path):
        store = self._store(tmp_path)
        ids = store.search_lexical("desert travel", limit=10)
        # Without a filter, chunks from both genre subtrees are eligible.
        assert "chunk:sci-fi/dune.md:0" in ids
        assert "chunk:phil/ethics.md:0" in ids
        store.close()

    def test_prefix_pushdown_restricts_to_genre(self, tmp_path):
        store = self._store(tmp_path)
        ids = store.search_lexical("desert travel", limit=10, file_prefixes=("science-fiction/",))
        assert ids
        assert all("sci-fi" in i or "science-fiction" in i for i in ids)
        # the philosophy chunk must be excluded
        assert "chunk:phil/ethics.md:0" not in ids
        store.close()

    def test_kind_pushdown_restricts_to_chunks(self, tmp_path):
        store = self._store(tmp_path)
        ids = store.search_lexical("desert travel", limit=10, node_kinds=("chunk",))
        assert ids
        assert "section:sci-fi/dune.md:s0" not in ids
        store.close()

    def test_combined_pushdown(self, tmp_path):
        store = self._store(tmp_path)
        ids = store.search_lexical(
            "desert travel",
            limit=10,
            file_prefixes=("science-fiction/",),
            node_kinds=("chunk",),
        )
        assert ids == ["chunk:sci-fi/dune.md:0"]
        store.close()
