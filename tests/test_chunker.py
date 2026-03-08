"""Tests for TextChunker."""

from doc_kg.chunker import (
    TextChunker,
    _extract_links,
    _split_by_headings,
    _split_sentences,
)


def test_split_by_headings_basic():
    text = "Intro text.\n\n# Section One\n\nContent one.\n\n## Sub\n\nContent two.\n"
    sections = _split_by_headings(text)
    titles = [s["title"] for s in sections]
    assert "Section One" in titles
    assert "Sub" in titles


def test_split_by_headings_no_headings():
    text = "Just plain text with no headings."
    sections = _split_by_headings(text)
    assert len(sections) == 1
    assert sections[0]["title"] is None


def test_split_sentences_basic():
    text = "This is sentence one. This is sentence two. And a third one!"
    sents = _split_sentences(text)
    assert len(sents) >= 2


def test_split_sentences_empty():
    assert _split_sentences("") == []


def test_extract_links():
    text = "See [docs](https://example.com) and [local](readme.md)."
    links = _extract_links(text)
    assert "https://example.com" in links
    assert "readme.md" in links


def test_chunker_plain_no_embedder():
    chunker = TextChunker(chunk_size=200, chunk_overlap=20)
    text = "Alpha beta gamma. " * 20
    chunks = chunker.chunk(text, file_path="test.txt")
    assert len(chunks) >= 1
    for c in chunks:
        assert "text" in c
        assert "char_start" in c
        assert "references" in c


def test_chunker_markdown_sections():
    md = "# Introduction\n\nThis is the intro.\n\n# Background\n\nThis is background.\n"
    chunker = TextChunker(chunk_size=512)
    chunks = chunker.chunk(md, file_path="test.md")
    assert len(chunks) >= 2
    section_titles = {c["section_title"] for c in chunks if c["section_title"]}
    assert "Introduction" in section_titles
    assert "Background" in section_titles


def test_chunker_markdown_no_headings():
    md = "Just a paragraph.\n\nAnother paragraph here with some content."
    chunker = TextChunker(chunk_size=512)
    chunks = chunker.chunk(md, file_path="test.md")
    assert len(chunks) >= 1


def test_chunker_references_extracted():
    md = "# Links\n\nSee [other doc](other.md) for details.\n"
    chunker = TextChunker()
    chunks = chunker.chunk(md, file_path="notes.md")
    all_refs = [r for c in chunks for r in c["references"]]
    assert "other.md" in all_refs
