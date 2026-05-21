"""
Tests for front-matter / reference detection and query-time seed filtering.

Coverage:
  _classify_section_content_type — unit tests for all decision branches
  parse_corpus                   — integration: content_type set on DocNodes
  DocKG.query                    — integration: front_matter/reference nodes
                                   excluded from seeds and returned results
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from doc_kg.dockg import (
    DocEdge,
    DocNode,
    _classify_section_content_type,
    parse_corpus,
)
from doc_kg.kg import DocKG
from doc_kg.store import GraphStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PROSE_BODY = (
    "This is a body paragraph with enough words to exceed the minimum chunk "
    "character threshold used by the fixed-size chunker. "
) * 6


def _chunk_nodes(nodes: list[DocNode]) -> list[DocNode]:
    return [n for n in nodes if n.kind == "chunk"]


def _content_types(nodes: list[DocNode]) -> set[str | None]:
    return {n.content_type for n in _chunk_nodes(nodes)}


# ---------------------------------------------------------------------------
# Unit tests — _classify_section_content_type
# ---------------------------------------------------------------------------


class TestClassifySectionContentType:
    """Pure unit tests — no I/O."""

    def test_h1_title_never_fm(self):
        # H1 is the book title; should never be classified as front matter.
        assert _classify_section_content_type("Introduction", 1, 0, 10_000, "book.md") is None

    def test_reference_md_always_reference(self):
        # Any section in a reference.md file is "reference", regardless of title.
        assert _classify_section_content_type("Summary", 2, 0, 5_000, "reference.md") == "reference"
        assert _classify_section_content_type(None, None, 0, 5_000, "reference.md") == "reference"
        assert (
            _classify_section_content_type("Chapter I", 2, 100, 5_000, "path/to/reference.md")
            == "reference"
        )

    def test_main_content_heading_wins(self):
        # Headings starting with chapter/book/part/etc. override FM classification.
        for heading in (
            "Chapter I",
            "Book II",
            "Part Three",
            "Volume IV",
            "CHAPTER 1. Introduction",
            "Book I. Introduction.",
        ):
            result = _classify_section_content_type(heading, 2, 0, 50_000, "prose.md")
            assert result is None, f"Expected None for main-content heading {heading!r}"

    def test_fm_heading_in_early_position(self):
        # Standard FM headings within the first 40% of the file.
        fm_headings = [
            "Introduction",
            "Preface",
            "Foreword",
            "Translator's Introduction",
            "Editor's Note",
            "Biographical Sketch of the Author",
            "Transcriber's Note",
            "About the Author",
            "Table of Contents",
            "SELECT BIBLIOGRAPHY",
            "Introductory Essay",
        ]
        total = 100_000
        early = int(total * 0.20)  # well within the 40% cutoff
        for heading in fm_headings:
            result = _classify_section_content_type(heading, 2, early, total, "book.md")
            assert result == "front_matter", (
                f"Expected 'front_matter' for {heading!r} at position 20%"
            )

    def test_fm_heading_past_position_cutoff(self):
        # Same FM headings appearing after 40% of the file should NOT be classified as FM.
        total = 100_000
        late = int(total * 0.60)
        for heading in ("Introduction", "Preface", "Translator's Introduction"):
            result = _classify_section_content_type(heading, 2, late, total, "book.md")
            assert result is None, f"Expected None for {heading!r} at position 60% (past cutoff)"

    def test_fm_heading_at_cutoff_boundary(self):
        # Exactly at 40% → still front matter (≤ cutoff, not strictly <).
        total = 10_000
        at_cutoff = 4_000  # exactly 40%
        result = _classify_section_content_type("Preface", 2, at_cutoff, total, "book.md")
        assert result == "front_matter"

        just_past = 4_001  # just past 40%
        result = _classify_section_content_type("Preface", 2, just_past, total, "book.md")
        assert result is None

    def test_normal_prose_section(self):
        # Headings that are neither FM nor main-content keywords → None.
        for heading in ("The Stoic Philosophy", "Athens and Rome", "Moral Reflections"):
            result = _classify_section_content_type(heading, 2, 0, 10_000, "book.md")
            assert result is None, f"Expected None for prose heading {heading!r}"

    def test_none_title_preamble(self):
        # The preamble before the first heading has title=None → not classified as FM.
        assert _classify_section_content_type(None, None, 0, 10_000, "book.md") is None

    def test_zero_total_chars_no_crash(self):
        # Guard against zero-length files.
        result = _classify_section_content_type("Preface", 2, 0, 0, "book.md")
        # With total_chars=0 the position check is skipped; FM pattern still fires.
        assert result == "front_matter"


# ---------------------------------------------------------------------------
# Integration tests — parse_corpus content_type tagging
# ---------------------------------------------------------------------------


class TestParseCorpusFrontMatterTagging:
    """Integration tests via parse_corpus on synthetic tmp_path corpora."""

    def test_reference_md_chunks_tagged(self, tmp_path):
        (tmp_path / "reference.md").write_text(
            "# Reference: My Book\n\nAuthor: Jane Doe. Published 1920. " + _PROSE_BODY
        )
        nodes, _ = parse_corpus(tmp_path)
        ref_chunks = [n for n in nodes if n.kind == "chunk" and n.file_path == "reference.md"]
        assert ref_chunks, "Expected at least one chunk from reference.md"
        for c in ref_chunks:
            assert c.content_type == "reference", (
                f"reference.md chunk {c.id} should have content_type='reference', got {c.content_type!r}"
            )

    def test_fm_section_chunks_tagged(self, tmp_path):
        # A book with a Preface and a Chapter; preface → front_matter, chapter → None.
        md = (
            "# My Great Novel\n\n"
            "## Preface\n\n" + _PROSE_BODY + "\n\n"
            "## Chapter I\n\n" + _PROSE_BODY
        )
        (tmp_path / "book.md").write_text(md)
        nodes, _ = parse_corpus(tmp_path)
        chunks = _chunk_nodes(nodes)
        fm = [c for c in chunks if c.content_type == "front_matter"]
        prose = [c for c in chunks if c.content_type is None]
        assert fm, "Expected at least one front_matter chunk from Preface section"
        assert prose, "Expected at least one prose chunk from Chapter I"

    def test_introduction_section_tagged(self, tmp_path):
        md = (
            "# Philosophy Primer\n\n"
            "## Introduction\n\n" + _PROSE_BODY + "\n\n"
            "## Part One — The Good Life\n\n" + _PROSE_BODY
        )
        (tmp_path / "primer.md").write_text(md)
        nodes, _ = parse_corpus(tmp_path)
        chunks = _chunk_nodes(nodes)
        fm = [c for c in chunks if c.content_type == "front_matter"]
        assert fm, "Expected front_matter chunks from Introduction"
        # Chunks from the main section should be prose
        prose = [c for c in chunks if c.content_type is None]
        assert prose, "Expected prose chunks from Part One"

    def test_chapter_heading_not_tagged(self, tmp_path):
        # Chapter headings that contain "introduction" after "Chapter I." → not FM
        # because main-content keyword wins.
        md = (
            "# Lives of the Philosophers\n\n"
            "## Book I. Introduction.\n\n" + _PROSE_BODY + "\n\n"
            "## Book II. Life of Plato.\n\n" + _PROSE_BODY
        )
        (tmp_path / "lives.md").write_text(md)
        nodes, _ = parse_corpus(tmp_path)
        chunks = _chunk_nodes(nodes)
        fm = [c for c in chunks if c.content_type == "front_matter"]
        assert not fm, f"Book I/II headings should NOT be tagged as FM; got: {[c.id for c in fm]}"

    def test_late_contextual_intro_not_tagged(self, tmp_path):
        # An "Introduction" heading that appears past 40% of the file → not FM.
        early_body = _PROSE_BODY * 10  # large early section pushes Introduction past cutoff
        md = (
            "# Long Work\n\n"
            "## Part One\n\n" + early_body + "\n\n"
            "## Introduction\n\n" + _PROSE_BODY  # this will be > 40% into the file
        )
        (tmp_path / "long.md").write_text(md)
        nodes, _ = parse_corpus(tmp_path)
        chunks = _chunk_nodes(nodes)
        fm = [c for c in chunks if c.content_type == "front_matter"]
        # The late Introduction should not be tagged because it's past the position cutoff.
        late_fm = [c for c in fm if c.file_path == "long.md"]
        assert not late_fm, (
            f"Late Introduction (past 40%) should not be FM; got: {[c.id for c in late_fm]}"
        )

    def test_prose_only_file_no_fm(self, tmp_path):
        # A file with no FM headings should produce no front_matter chunks.
        md = "# The Republic\n\n## Book I\n\n" + _PROSE_BODY + "\n\n## Book II\n\n" + _PROSE_BODY
        (tmp_path / "republic.md").write_text(md)
        nodes, _ = parse_corpus(tmp_path)
        assert "front_matter" not in _content_types(nodes)

    def test_mixed_corpus_correct_distribution(self, tmp_path):
        # Reference file + book with preface + book with only chapters.
        (tmp_path / "reference.md").write_text("# Reference\n\nMetadata. " + _PROSE_BODY)
        (tmp_path / "with_preface.md").write_text(
            "# War and Peace\n\n## Preface\n\n" + _PROSE_BODY + "\n\n## Part I\n\n" + _PROSE_BODY
        )
        (tmp_path / "no_preface.md").write_text("# Clean Work\n\n## Chapter I\n\n" + _PROSE_BODY)
        nodes, _ = parse_corpus(tmp_path)
        chunks = _chunk_nodes(nodes)
        ref = [c for c in chunks if c.content_type == "reference"]
        fm = [c for c in chunks if c.content_type == "front_matter"]
        prose = [c for c in chunks if c.content_type is None]
        assert ref, "reference.md should produce 'reference' chunks"
        assert fm, "with_preface.md should produce 'front_matter' chunks"
        assert prose, "Both books should produce prose chunks"
        # No reference chunk from the non-reference files
        ref_wrong_file = [c for c in ref if not c.file_path.endswith("reference.md")]
        assert not ref_wrong_file


# ---------------------------------------------------------------------------
# Integration tests — DocKG.query seed / result filtering
# ---------------------------------------------------------------------------


def _make_chunk_node(node_id: str, file_path: str, content_type: str | None = None) -> DocNode:
    """Helper: build a minimal chunk DocNode."""
    return DocNode(
        id=node_id,
        kind="chunk",
        name=node_id.split(":")[-1],
        title="Section",
        file_path=file_path,
        char_start=0,
        char_end=200,
        heading_level=None,
        text="Content of this chunk. " * 8,
        content_type=content_type,
    )


class TestQuerySeedFiltering:
    """
    Test that DocKG.query excludes front_matter and reference nodes from
    both seeds and returned results.

    The LanceDB index is mocked so these tests run fast without model loading.
    The SQLite GraphStore is real — we write nodes directly and verify the
    filtering logic operates on actual store data.
    """

    def _build_store(self, tmp_path) -> tuple[GraphStore, list[DocNode]]:
        """Write a graph with one prose chunk, one FM chunk, one reference chunk."""
        prose = _make_chunk_node("chunk:book.md:0000", "book.md", None)
        fm = _make_chunk_node("chunk:book.md:0001", "book.md", "front_matter")
        ref = _make_chunk_node("chunk:reference.md:0000", "reference.md", "reference")
        doc = DocNode(
            id="doc:book.md",
            kind="document",
            name="book",
            title="Book",
            file_path="book.md",
            char_start=0,
            char_end=1000,
            heading_level=None,
            text="book summary",
        )
        nodes = [doc, prose, fm, ref]
        edges = [
            DocEdge(src="doc:book.md", rel="CONTAINS", dst="chunk:book.md:0000"),
            DocEdge(src="doc:book.md", rel="CONTAINS", dst="chunk:book.md:0001"),
        ]
        db_path = tmp_path / ".dockg" / "graph.sqlite"
        db_path.parent.mkdir()
        store = GraphStore(db_path)
        store.write(nodes, edges, wipe=True)
        return store, nodes

    def _fake_seed_hit(self, node_id: str, file_path: str, distance: float = 0.1):
        """Create a mock SeedHit-like object."""
        hit = MagicMock()
        hit.id = node_id
        hit.file_path = file_path
        hit.kind = "chunk"
        hit.name = node_id.split(":")[-1]
        hit.title = ""
        hit.distance = distance
        hit.rank = 0
        return hit

    def test_reference_md_excluded_from_results(self, tmp_path):
        store, _ = self._build_store(tmp_path)

        # Simulate index returning hits that include a reference.md node.
        hits = [
            self._fake_seed_hit("chunk:book.md:0000", "book.md", 0.05),
            self._fake_seed_hit("chunk:reference.md:0000", "reference.md", 0.10),
        ]

        kg = DocKG(tmp_path)
        kg._store = store  # inject real store

        with patch.object(kg.index, "search", return_value=hits):
            result = kg.query("stoic philosophy")

        returned_ids = {n["id"] for n in result.nodes}
        assert "chunk:reference.md:0000" not in returned_ids, (
            "reference.md chunk should be excluded from query results"
        )

    def test_front_matter_excluded_from_results(self, tmp_path):
        store, _ = self._build_store(tmp_path)

        hits = [
            self._fake_seed_hit("chunk:book.md:0000", "book.md", 0.05),
            self._fake_seed_hit("chunk:book.md:0001", "book.md", 0.08),
        ]

        kg = DocKG(tmp_path)
        kg._store = store

        with patch.object(kg.index, "search", return_value=hits):
            result = kg.query("stoic philosophy")

        returned_ids = {n["id"] for n in result.nodes}
        assert "chunk:book.md:0001" not in returned_ids, (
            "front_matter chunk should be excluded from query results"
        )

    def test_prose_chunk_included_in_results(self, tmp_path):
        store, _ = self._build_store(tmp_path)

        hits = [
            self._fake_seed_hit("chunk:book.md:0000", "book.md", 0.05),
            self._fake_seed_hit("chunk:book.md:0001", "book.md", 0.08),
            self._fake_seed_hit("chunk:reference.md:0000", "reference.md", 0.12),
        ]

        kg = DocKG(tmp_path)
        kg._store = store

        with patch.object(kg.index, "search", return_value=hits):
            result = kg.query("stoic philosophy")

        returned_ids = {n["id"] for n in result.nodes}
        assert "chunk:book.md:0000" in returned_ids, "Prose chunk should be present in results"

    def test_all_filtered_seeds_still_returns_empty(self, tmp_path):
        store, _ = self._build_store(tmp_path)

        # Only FM and reference hits — no prose.
        hits = [
            self._fake_seed_hit("chunk:book.md:0001", "book.md", 0.05),
            self._fake_seed_hit("chunk:reference.md:0000", "reference.md", 0.08),
        ]

        kg = DocKG(tmp_path)
        kg._store = store

        with patch.object(kg.index, "search", return_value=hits):
            result = kg.query("stoic philosophy")

        # No front_matter or reference in results regardless.
        for n in result.nodes:
            assert n.get("content_type") not in ("front_matter", "reference")
