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
    md = (
        "# Introduction\n\n"
        "This is the intro section with enough text to exceed the minimum chunk size threshold.\n\n"
        "# Background\n\n"
        "This is the background section providing additional context and detail for the reader.\n"
    )
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
    md = "# Links\n\nSee [other doc](other.md) for more details about configuration and usage.\n"
    chunker = TextChunker()
    chunks = chunker.chunk(md, file_path="notes.md")
    all_refs = [r for c in chunks for r in c["references"]]
    assert "other.md" in all_refs


_MACBETH = (
    "Till he unseam'd him from the nave to the chops,\n"
    "And fix'd his head upon our battlements.\n\n"
    "DUNCAN.\n"
    "O valiant cousin! worthy gentleman!\n\n"
    "SOLDIER.\n"
    "As whence the sun 'gins his reflection\n"
    "Shipwracking storms and direful thunders break,\n"
)


def test_chunk_text_keeps_the_blank_line_between_speeches():
    chunks = TextChunker(chunk_size=2000).chunk(_MACBETH, file_path="macbeth.txt")
    assert len(chunks) == 1
    assert (
        "battlements.\n\nDUNCAN.\nO valiant cousin! worthy gentleman!\n\nSOLDIER."
        in chunks[0]["text"]
    )


def test_chunk_text_is_the_source_slice_it_spans():
    text = "Intro words here.\n\n" + _MACBETH
    for chunk in TextChunker(chunk_size=120, chunk_overlap=40).chunk(text, file_path="m.txt"):
        assert chunk["text"] == text[chunk["char_start"] : chunk["char_end"]]


def test_chunk_boundaries_ignore_whitespace():
    # The same words with every run of whitespace collapsed split in the same
    # places: chunk sizes are measured on the joined sentences.
    flat = " ".join(_MACBETH.split())
    chunker = TextChunker(chunk_size=90, chunk_overlap=30)
    restored = chunker.chunk(_MACBETH, file_path="m.txt")
    joined = chunker.chunk(flat, file_path="m.txt")
    assert [c["text"].split() for c in restored] == [c["text"].split() for c in joined]


def test_a_repeated_speaker_cue_does_not_misplace_the_chunk():
    # "FIRST WITCH." recurs, so the first copy of a chunk's first or last
    # sentence is not always the chunk's own.
    text = (
        "FIRST WITCH.\nWhere hast thou been, sister?\n\n"
        "SECOND WITCH.\nKilling swine.\n\n"
        "THIRD WITCH.\nSister, where thou?\n\n"
        "FIRST WITCH.\nA sailor's wife had chestnuts in her lap.\n\n"
        "SECOND WITCH.\nI'll give thee a wind.\n\n"
        "FIRST WITCH.\nThou art kind.\n"
    )
    chunks = TextChunker(chunk_size=105, chunk_overlap=5, min_chunk_chars=10).chunk(
        text, file_path="w.txt"
    )
    assert len(chunks) > 2
    for chunk in chunks:
        assert text[chunk["char_start"] : chunk["char_end"]].split() == chunk["text"].split()
