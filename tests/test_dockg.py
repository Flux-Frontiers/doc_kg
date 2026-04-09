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
        "# Introduction\n\nThis is the introduction.\n\n# Background\n\nThis is background.\n"
    )
    (tmp_path / "doc2.txt").write_text("Plain text content here. More text follows.")

    nodes, edges = parse_corpus(tmp_path)

    assert any(n.id.startswith("doc:") for n in nodes)
    assert any(n.id.startswith("chunk:") for n in nodes)

    # Edges should include at least CONTAINS
    rels = {e.rel for e in edges}
    assert "CONTAINS" in rels


def test_parse_corpus_sections(tmp_path):
    (tmp_path / "guide.md").write_text(
        "# Setup\n\nInstall the package.\n\n# Usage\n\nRun the command.\n"
    )
    nodes, edges = parse_corpus(tmp_path)

    section_nodes = [n for n in nodes if n.kind == "section"]
    section_titles = {n.title for n in section_nodes}
    assert "Setup" in section_titles
    assert "Usage" in section_titles


def test_parse_corpus_references(tmp_path):
    (tmp_path / "a.md").write_text("# Links\n\nSee [b](b.md) for more.\n")
    (tmp_path / "b.md").write_text("# B Document\n\nContent here.\n")

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
