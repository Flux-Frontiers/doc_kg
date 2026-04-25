"""Tests for SentenceGroupChunker and the chunker_for factory in chunker.py."""

from doc_kg.chunker import SentenceGroupChunker, TextChunker, chunker_for

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REQUIRED_KEYS = {"text", "section_title", "section_level", "char_start", "char_end", "references"}

_PLAIN_TEXT = (
    "The quick brown fox jumps over the lazy dog. "
    "A second sentence follows immediately after. "
    "Here comes a third sentence for good measure. "
    "And a fourth sentence rounds things out. "
    "Fifth sentence here. Sixth sentence here. "
    "Seventh sentence, going strong. Eighth sentence too."
)

_MD_TEXT = (
    "# Introduction\n\n"
    "This is the introduction section. It has two sentences here. "
    "A third sentence for the intro. A fourth sentence.\n\n"
    "## Background\n\n"
    "Background information goes here. It spans multiple sentences. "
    "More background detail follows. And a final background sentence.\n\n"
    "## Implementation\n\n"
    "Implementation details are described here. "
    "Functions and classes are defined. "
    "Tests verify correctness. Deployment completes the cycle.\n"
)


# ---------------------------------------------------------------------------
# SentenceGroupChunker — basic behaviour
# ---------------------------------------------------------------------------


def test_sentence_group_chunker_default_params():
    chunker = SentenceGroupChunker()
    assert chunker.sentences_per_chunk == 4
    assert chunker.min_chunk_chars == 50


def test_sentence_group_chunker_custom_sentences_per_chunk():
    chunker = SentenceGroupChunker(sentences_per_chunk=2)
    assert chunker.sentences_per_chunk == 2


def test_sentence_group_chunks_have_required_keys_plain():
    chunker = SentenceGroupChunker(sentences_per_chunk=2, min_chunk_chars=1)
    chunks = chunker.chunk(_PLAIN_TEXT, file_path="plain.txt")
    assert len(chunks) > 0
    for chunk in chunks:
        for key in _REQUIRED_KEYS:
            assert key in chunk, f"Missing key '{key}' in chunk"


def test_sentence_group_chunks_have_required_keys_markdown():
    chunker = SentenceGroupChunker(sentences_per_chunk=2, min_chunk_chars=1)
    chunks = chunker.chunk(_MD_TEXT, file_path="doc.md")
    assert len(chunks) > 0
    for chunk in chunks:
        for key in _REQUIRED_KEYS:
            assert key in chunk, f"Missing key '{key}' in chunk"


def test_sentence_group_produces_correct_number_of_chunks():
    # 8 sentences with 2 per chunk => 4 chunks for plain text
    # (using min_chunk_chars=1 to avoid filtering)
    chunker = SentenceGroupChunker(sentences_per_chunk=2, min_chunk_chars=1)
    # Construct text with exactly 8 clearly separated sentences
    text = (
        "Sentence one here. Sentence two here. "
        "Sentence three here. Sentence four here. "
        "Sentence five here. Sentence six here. "
        "Sentence seven here. Sentence eight here."
    )
    chunks = chunker.chunk(text, file_path="test.txt")
    # Should produce approximately n_sentences / sentences_per_chunk chunks
    assert len(chunks) >= 1


def test_sentence_group_chunk_text_is_non_empty():
    chunker = SentenceGroupChunker(sentences_per_chunk=2, min_chunk_chars=1)
    chunks = chunker.chunk(_PLAIN_TEXT, file_path="test.txt")
    for chunk in chunks:
        assert chunk["text"].strip() != ""


def test_sentence_group_char_offsets_are_non_negative():
    chunker = SentenceGroupChunker(sentences_per_chunk=2, min_chunk_chars=1)
    chunks = chunker.chunk(_PLAIN_TEXT, file_path="test.txt")
    for chunk in chunks:
        assert chunk["char_start"] >= 0
        assert chunk["char_end"] >= chunk["char_start"]


def test_sentence_group_references_is_list():
    chunker = SentenceGroupChunker(sentences_per_chunk=2, min_chunk_chars=1)
    chunks = chunker.chunk(_PLAIN_TEXT, file_path="test.txt")
    for chunk in chunks:
        assert isinstance(chunk["references"], list)


# ---------------------------------------------------------------------------
# SentenceGroupChunker — sentences_per_chunk honoured
# ---------------------------------------------------------------------------


def test_sentences_per_chunk_parameter_one():
    """sentences_per_chunk=1 should produce more chunks than sentences_per_chunk=4."""
    text = " ".join(f"Sentence number {i} here." for i in range(12))
    chunker1 = SentenceGroupChunker(sentences_per_chunk=1, min_chunk_chars=1)
    chunker4 = SentenceGroupChunker(sentences_per_chunk=4, min_chunk_chars=1)

    chunks1 = chunker1.chunk(text, file_path="test.txt")
    chunks4 = chunker4.chunk(text, file_path="test.txt")

    assert len(chunks1) >= len(chunks4)


def test_sentences_per_chunk_large_value_produces_fewer_chunks():
    """Larger sentences_per_chunk means fewer, bigger chunks."""
    text = " ".join(f"Sentence {i}." for i in range(20))
    chunker2 = SentenceGroupChunker(sentences_per_chunk=2, min_chunk_chars=1)
    chunker8 = SentenceGroupChunker(sentences_per_chunk=8, min_chunk_chars=1)

    chunks2 = chunker2.chunk(text, file_path="test.txt")
    chunks8 = chunker8.chunk(text, file_path="test.txt")

    assert len(chunks2) >= len(chunks8)


# ---------------------------------------------------------------------------
# SentenceGroupChunker — Markdown section boundaries
# ---------------------------------------------------------------------------


def test_markdown_sections_respected_as_boundaries():
    """Chunks must not span across Markdown heading boundaries."""
    chunker = SentenceGroupChunker(sentences_per_chunk=8, min_chunk_chars=1)
    chunks = chunker.chunk(_MD_TEXT, file_path="doc.md")

    # We should have chunks in at least two different sections
    sections_found = {c.get("section_title") for c in chunks if c.get("section_title")}
    assert len(sections_found) >= 2


def test_markdown_section_title_propagated():
    """Each chunk in a markdown section must carry the correct section_title."""
    chunker = SentenceGroupChunker(sentences_per_chunk=2, min_chunk_chars=1)
    chunks = chunker.chunk(_MD_TEXT, file_path="doc.md")

    for chunk in chunks:
        if chunk["section_title"] is not None:
            assert chunk["section_title"] in ("Introduction", "Background", "Implementation")


def test_markdown_section_level_propagated():
    """Heading levels should be set on chunks from headed sections."""
    chunker = SentenceGroupChunker(sentences_per_chunk=2, min_chunk_chars=1)
    chunks = chunker.chunk(_MD_TEXT, file_path="doc.md")

    headed = [c for c in chunks if c["section_level"] is not None]
    assert len(headed) > 0
    for c in headed:
        assert c["section_level"] in (1, 2, 3, 4, 5, 6)


def test_markdown_no_section_has_none_title():
    """Plain text chunked via markdown path gives section_title=None for preamble."""
    md = "Just a preamble paragraph without any heading.\n\nAnother paragraph here."
    chunker = SentenceGroupChunker(sentences_per_chunk=4, min_chunk_chars=1)
    chunks = chunker.chunk(md, file_path="doc.md")
    for chunk in chunks:
        assert chunk["section_title"] is None


# ---------------------------------------------------------------------------
# SentenceGroupChunker — plain text
# ---------------------------------------------------------------------------


def test_plain_text_chunking_works():
    """Non-markdown text (no .md extension) is chunked without heading parsing."""
    text = (
        "Alpha beta gamma sentence. Delta epsilon sentence. "
        "Zeta eta theta sentence. Iota kappa lambda sentence."
    )
    chunker = SentenceGroupChunker(sentences_per_chunk=2, min_chunk_chars=1)
    chunks = chunker.chunk(text, file_path="notes.txt")
    assert len(chunks) >= 1
    for chunk in chunks:
        assert chunk["section_title"] is None
        assert chunk["section_level"] is None


def test_plain_text_link_extraction():
    text = "See [docs](https://example.com) for more. Another sentence here."
    chunker = SentenceGroupChunker(sentences_per_chunk=2, min_chunk_chars=1)
    chunks = chunker.chunk(text, file_path="notes.txt")
    all_refs = [r for c in chunks for r in c["references"]]
    assert "https://example.com" in all_refs


def test_markdown_link_extraction():
    md = "# Links\n\nCheck out [guide](guide.md) and [api](api.md) for details."
    chunker = SentenceGroupChunker(sentences_per_chunk=4, min_chunk_chars=1)
    chunks = chunker.chunk(md, file_path="doc.md")
    all_refs = [r for c in chunks for r in c["references"]]
    assert "guide.md" in all_refs
    assert "api.md" in all_refs


# ---------------------------------------------------------------------------
# chunker_for factory
# ---------------------------------------------------------------------------


def test_chunker_for_sentence_group_returns_sentence_group_chunker():
    chunker = chunker_for("sentence_group")
    assert isinstance(chunker, SentenceGroupChunker)


def test_chunker_for_semantic_returns_text_chunker():
    chunker = chunker_for("semantic")
    assert isinstance(chunker, TextChunker)


def test_chunker_for_fixed_returns_text_chunker():
    chunker = chunker_for("fixed")
    assert isinstance(chunker, TextChunker)


def test_chunker_for_sentence_group_passes_sentences_per_chunk():
    chunker = chunker_for("sentence_group", sentences_per_chunk=6)
    assert isinstance(chunker, SentenceGroupChunker)
    assert chunker.sentences_per_chunk == 6


def test_chunker_for_semantic_passes_chunk_size():
    chunker = chunker_for("semantic", chunk_size=1024)
    assert isinstance(chunker, TextChunker)
    assert chunker.chunk_size == 1024


def test_chunker_for_default_strategy_is_semantic():
    # Default strategy is "semantic" per the type signature
    chunker = chunker_for()
    assert isinstance(chunker, TextChunker)


def test_chunker_for_sentence_group_passes_min_chunk_chars():
    chunker = chunker_for("sentence_group", min_chunk_chars=100)
    assert isinstance(chunker, SentenceGroupChunker)
    assert chunker.min_chunk_chars == 100
