"""Tests for dockg.py — corpus extraction primitives."""

from doc_kg.dockg import (
    chunk_node_id,
    doc_node_id,
    iter_text_files,
    parse_corpus,
    section_node_id,
    slugify,
)


def test_doc_node_id():
    assert doc_node_id("notes/journal.md") == "doc:notes/journal.md"


def test_section_node_id():
    assert section_node_id("notes/journal.md", "intro") == "sec:notes/journal.md:intro"
    # The first occurrence keeps the bare id, so ids stay stable for the
    # ordinary case of a heading appearing once.
    assert section_node_id("notes/journal.md", "intro", 1) == "sec:notes/journal.md:intro"
    assert section_node_id("notes/journal.md", "intro", 2) == "sec:notes/journal.md:intro~2"
    # The suffix cannot collide with a heading: slugify strips "~".
    assert "~" not in slugify("Intro ~2")


def test_chunk_node_id():
    assert chunk_node_id("notes/journal.md", 42) == "chunk:notes/journal.md:0042"


def test_slugify():
    assert slugify("Hello World!") == "hello-world"
    assert slugify("  Multi  Word  ") == "multi-word"


def test_iter_text_files_finds_md_and_txt(tmp_path):
    (tmp_path / "a.md").write_text("# Hello")
    (tmp_path / "b.txt").write_text("plain text")
    (tmp_path / "c.py").write_text("# python")
    found = iter_text_files(tmp_path)
    names = {f.name for f in found}
    assert "a.md" in names
    assert "b.txt" in names
    assert "c.py" not in names


def test_iter_text_files_skips_hidden(tmp_path):
    (tmp_path / ".hidden.md").write_text("hidden")
    (tmp_path / "visible.md").write_text("visible")
    found = iter_text_files(tmp_path)
    names = {f.name for f in found}
    assert "visible.md" in names
    assert ".hidden.md" not in names


def test_parse_corpus_basic(tmp_path):
    (tmp_path / "doc1.md").write_text(
        "# Introduction\n\n"
        "This is the introduction section with enough content to exceed the minimum chunk size.\n\n"
        "# Background\n\n"
        "This is the background section providing additional context for the reader.\n"
    )
    (tmp_path / "doc2.txt").write_text(
        "Plain text content here covering several sentences. "
        "More text follows to ensure it meets the minimum chunk character threshold."
    )

    nodes, edges = parse_corpus(tmp_path)

    assert any(n.id.startswith("doc:") for n in nodes)
    assert any(n.id.startswith("chunk:") for n in nodes)

    # Edges should include at least CONTAINS
    rels = {e.rel for e in edges}
    assert "CONTAINS" in rels


def test_parse_corpus_sections(tmp_path):
    (tmp_path / "guide.md").write_text(
        "# Setup\n\n"
        "Install the package using pip or poetry to get started with the library.\n\n"
        "# Usage\n\n"
        "Run the command from the terminal with the appropriate flags and arguments.\n"
    )
    nodes, edges = parse_corpus(tmp_path)

    section_nodes = [n for n in nodes if n.kind == "section"]
    section_titles = {n.title for n in section_nodes}
    assert "Setup" in section_titles
    assert "Usage" in section_titles


def test_parse_corpus_references(tmp_path):
    (tmp_path / "a.md").write_text(
        "# Links\n\nSee [b](b.md) for more details about the configuration and setup process.\n"
    )
    (tmp_path / "b.md").write_text(
        "# B Document\n\nContent here describes the configuration options available to the user.\n"
    )

    nodes, edges = parse_corpus(tmp_path)
    ref_edges = [e for e in edges if e.rel == "REFERENCES"]
    # At least one REFERENCES edge should be emitted
    assert len(ref_edges) >= 1


def test_parse_corpus_next_edges(tmp_path):
    # A document with enough content to generate multiple chunks
    long_text = "This is a sentence. " * 60
    (tmp_path / "long.md").write_text(f"# Section\n\n{long_text}\n")
    nodes, edges = parse_corpus(tmp_path, chunk_size=100)

    next_edges = [e for e in edges if e.rel == "NEXT"]
    # With chunk_size=100 and ~1200 chars of content, we should get NEXT edges
    assert len(next_edges) >= 1


def test_parse_corpus_semantic_edges(tmp_path):
    (tmp_path / "semantic.md").write_text(
        "# Architecture\n\n"
        "DocKG architecture improves database query design. "
        "DocKG integrates LanceDB and SQLite for performance.\n"
    )

    nodes, edges = parse_corpus(tmp_path, emit_cooccur=True)

    kinds = {n.kind for n in nodes}
    rels = {e.rel for e in edges}

    assert "topic" in kinds
    assert "entity" in kinds
    assert "keyword" in kinds

    assert "HAS_TOPIC" in rels
    assert "MENTIONS_ENTITY" in rels
    assert "HAS_KEYWORD" in rels
    assert "CO_OCCURS_WITH" in rels


def test_parse_corpus_semantic_edges_can_be_disabled(tmp_path):
    (tmp_path / "plain.md").write_text(
        "# Title\n\nSimple content about architecture and query design.\n"
    )

    nodes, edges = parse_corpus(
        tmp_path,
        enable_topics=False,
        enable_entities=False,
        enable_keywords=False,
        emit_cooccur=False,
    )

    rels = {e.rel for e in edges}
    assert "HAS_TOPIC" not in rels
    assert "MENTIONS_ENTITY" not in rels
    assert "HAS_KEYWORD" not in rels
    assert "CO_OCCURS_WITH" not in rels


def test_parse_corpus_empty_dir(tmp_path):
    nodes, edges = parse_corpus(tmp_path)
    assert nodes == []
    assert edges == []


def test_section_spans_all_its_chunks(tmp_path):
    """A multi-chunk section starts at its first chunk and ends at its last.

    Regression: the reuse guard tested ``sec_id`` against a dict keyed by
    ``slug``, so it never fired and every chunk rebuilt the section node.
    The last chunk won, leaving ``char_start`` at the section's final
    paragraph -- which made Browse show a chapter's successor instead of
    the chapter, and nothing at all for a book held in a single section.
    """
    # Distinct sentences: repeating one collapses every chunk onto one offset.
    body = " ".join(f"Paragraph number {i} of the section body." for i in range(60))
    (tmp_path / "long.md").write_text(f"# Section\n\n{body}\n")
    nodes, edges = parse_corpus(tmp_path, chunk_size=100)

    section = next(n for n in nodes if n.kind == "section")
    chunks = [n for n in nodes if n.kind == "chunk"]
    assert len(chunks) > 1, "the fixture must span several chunks to be meaningful"

    assert section.char_start == min(c.char_start for c in chunks)
    assert section.char_end == max(c.char_end for c in chunks)


def test_repeated_heading_gets_its_own_section(tmp_path):
    """A heading repeated within one file yields one section per occurrence.

    Regression: section ids were built from the slug alone, so a book whose
    volumes each restart at ``Chapter I`` collapsed both onto a single node.
    Its span then ran from the first volume's opening to the second volume's
    close, and Browse rendered everything in between as one giant chapter.

    The assertions below mirror what a reader-style consumer actually does:
    take a section's ``char_start``, run to the next section's, and collect
    the chunks in between.
    """

    def body(label):
        # Distinct sentences: repeating one collapses chunks onto one offset.
        return " ".join(f"{label} sentence number {i}." for i in range(40))

    (tmp_path / "book.md").write_text(
        f"# Chapter I\n\n{body('First')}\n\n"
        f"# Chapter II\n\n{body('Second')}\n\n"
        f"# Chapter I\n\n{body('Third')}\n"
    )
    nodes, edges = parse_corpus(tmp_path, chunk_size=100)

    sections = sorted((n for n in nodes if n.kind == "section"), key=lambda n: n.char_start)
    chunks = sorted((n for n in nodes if n.kind == "chunk"), key=lambda c: c.char_start)

    # Both "Chapter I" headings survive as separate nodes; the first keeps the
    # bare id so ids stay stable for documents without repeated headings.
    assert [s.id for s in sections] == [
        "sec:book.md:chapter-i",
        "sec:book.md:chapter-ii",
        "sec:book.md:chapter-i~2",
    ]

    owned = {s.id: [] for s in sections}
    for e in edges:
        if e.rel == "CONTAINS" and e.src in owned:
            owned[e.src].append(next(c for c in chunks if c.id == e.dst))
    assert all(len(v) > 1 for v in owned.values()), (
        "each chapter must span several chunks for this test to be meaningful"
    )

    for section in sections:
        mine = owned[section.id]
        assert section.char_start == min(c.char_start for c in mine)
        assert section.char_end == max(c.char_end for c in mine)

    # Spans are disjoint and in document order -- the third chapter must not
    # reach back to the first, which is what the merged node used to do.
    for earlier, later in zip(sections, sections[1:]):
        assert earlier.char_end <= later.char_start

    # The consumer's reconstruction returns each chapter, and only it.
    for i, section in enumerate(sections):
        end = sections[i + 1].char_start if i + 1 < len(sections) else None
        rebuilt = [
            c
            for c in chunks
            if c.char_start >= section.char_start and (end is None or c.char_start < end)
        ]
        assert rebuilt == owned[section.id]

    # Content check: no chapter bleeds into its neighbour.
    for section, label in zip(sections, ("First", "Second", "Third")):
        assert all(label in c.text for c in owned[section.id])
