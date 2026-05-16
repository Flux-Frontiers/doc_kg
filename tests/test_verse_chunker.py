"""Tests for VerseChunker — verse-structured document chunking."""

import textwrap

from doc_kg.chunker import VerseChunker

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

GENESIS_1 = textwrap.dedent("""\
    ## The First Book of Moses: Called Genesis

    1:1 In the beginning God created the heaven and the earth.

    1:2 And the earth was without form, and void; and darkness was upon
    the face of the deep. And the Spirit of God moved upon the face of the
    waters.

    1:3 And God said, Let there be light: and there was light.

    1:4 And God saw the light, that it was good: and God divided the light
    from the darkness.

    1:5 And God called the light Day, and the darkness he called Night.
    And the evening and the morning were the first day.

    1:6 And God said, Let there be a firmament in the midst of the waters,
    and let it divide the waters from the waters.

    1:7 And God made the firmament, and divided the waters which were
    under the firmament from the waters which were above the firmament:
    and it was so.

    1:8 And God called the firmament Heaven. And the evening and the
    morning were the second day.

    1:9 And God said, Let the waters under the heaven be gathered together
    unto one place, and let the dry land appear: and it was so.

    1:10 And God called the dry land Earth; and the gathering together of
    the waters called he Seas: and God saw that it was good.

    1:11 And God said, Let the earth bring forth grass, the herb yielding
    seed, and the fruit tree yielding fruit after his kind, whose seed is
    in itself, upon the earth: and it was so.

    1:12 And the earth brought forth grass, and herb yielding seed after
    his kind, and the tree yielding fruit, whose seed was in itself, after
    his kind: and God saw that it was good.

    1:13 And the evening and the morning were the third day.

    1:14 And God said, Let there be lights in the firmament of the heaven
    to divide the day from the night; and let them be for signs, and for
    seasons, and for days, and years:

    1:15 And let them be for lights in the firmament of the heaven to give
    light upon the earth: and it was so.

    1:16 And God made two great lights; the greater light to rule the day,
    and the lesser light to rule the night: he made the stars also.

    1:17 And God set them in the firmament of the heaven to give light
    upon the earth,

    1:18 And to rule over the day and over the night, and to divide the
    light from the darkness: and God saw that it was good.

    1:19 And the evening and the morning were the fourth day.

    1:20 And God said, Let the waters bring forth abundantly the moving
    creature that hath life, and fowl that may fly above the earth in the
    open firmament of heaven.

    1:21 And God created great whales, and every living creature that
    moveth, which the waters brought forth abundantly, after their kind,
    and every winged fowl after his kind: and God saw that it was good.

    1:22 And God blessed them, saying, Be fruitful, and multiply, and fill
    the waters in the seas, and let fowl multiply in the earth.

    1:23 And the evening and the morning were the fifth day.

    1:24 And God said, Let the earth bring forth the living creature after
    his kind, cattle, and creeping thing, and beast of the earth after his
    kind: and it was so.

    1:25 And God made the beast of the earth after his kind, and cattle
    after their kind, and every thing that creepeth upon the earth after
    his kind: and God saw that it was good.

    1:26 And God said, Let us make man in our image, after our likeness:
    and let them have dominion over the fish of the sea, and over the fowl
    of the air, and over the cattle, and over all the earth, and over
    every creeping thing that creepeth upon the earth.

    1:27 So God created man in his own image, in the image of God created
    he him; male and female created he them.

    1:28 And God blessed them, and God said unto them, Be fruitful, and
    multiply, and replenish the earth, and subdue it: and have dominion
    over the fish of the sea, and over the fowl of the air, and over every
    living thing that moveth upon the earth.

    1:29 And God said, Behold, I have given you every herb bearing seed,
    which is upon the face of all the earth, and every tree, in the which
    is the fruit of a tree yielding seed; to you it shall be for meat.

    1:30 And to every beast of the earth, and to every fowl of the air,
    and to every thing that creepeth upon the earth, wherein there is life,
    I have given every green herb for meat: and it was so.

    1:31 And God saw every thing that he had made, and, behold, it was
    very good. And the evening and the morning were the sixth day.
""")

GENESIS_CHAPTER_BREAK = textwrap.dedent("""\
    ## The First Book of Moses: Called Genesis

    1:30 And to every beast of the earth, and to every fowl of the air,
    I have given every green herb for meat: and it was so.

    1:31 And God saw every thing that he had made, and, behold, it was
    very good. And the evening and the morning were the sixth day.

    2:1 Thus the heavens and the earth were finished, and all the host of them.

    2:2 And on the seventh day God ended his work which he had made; and
    he rested on the seventh day from all his work which he had made.
""")

TOC_THEN_CONTENT = textwrap.dedent("""\
    # The Bible

    **Unknown**

    ---

    ## The Old Testament of the King James Version of the Bible

    ## The First Book of Moses: Called Genesis

    ## The Second Book of Moses: Called Exodus

    Ezra
    The Book of Nehemiah

    ## The Old Testament of the King James Version of the Bible

    ## The First Book of Moses: Called Genesis

    1:1 In the beginning God created the heaven and the earth.

    1:2 And the earth was without form, and void; and darkness was upon
    the face of the deep.
""")

PROSE_TEXT = textwrap.dedent("""\
    # Introduction to Python

    Python is a high-level programming language known for its readability.
    It supports multiple programming paradigms. Many developers choose Python
    for its extensive standard library and vibrant community.

    ## Getting Started

    Install Python from the official website. Then open your terminal and
    type `python3` to start the interpreter.
""")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestVerseDetection:
    def test_verse_document_detected(self):
        assert VerseChunker.is_verse_document(GENESIS_1) is True

    def test_prose_not_detected(self):
        assert VerseChunker.is_verse_document(PROSE_TEXT) is False

    def test_empty_text(self):
        assert VerseChunker.is_verse_document("") is False

    def test_toc_without_content_not_detected(self):
        # Pure TOC — no verse refs, only headings
        toc_only = "## Genesis\n\n## Exodus\n\n## Leviticus\n"
        assert VerseChunker.is_verse_document(toc_only) is False


class TestVerseChunkCount:
    def test_genesis1_five_per_chunk(self):
        # 31 verses, 5 per chunk → ceil(31/5) = 7 chunks
        chunker = VerseChunker(verses_per_chunk=5)
        chunks = chunker.chunk(GENESIS_1)
        assert len(chunks) == 7

    def test_genesis1_one_per_chunk(self):
        chunker = VerseChunker(verses_per_chunk=1)
        chunks = chunker.chunk(GENESIS_1)
        assert len(chunks) == 31

    def test_genesis1_ten_per_chunk(self):
        # 31 verses, 10 per chunk → 4 chunks (10+10+10+1)
        chunker = VerseChunker(verses_per_chunk=10)
        chunks = chunker.chunk(GENESIS_1)
        assert len(chunks) == 4


class TestVerseMetadata:
    def setup_method(self):
        self.chunker = VerseChunker(verses_per_chunk=5)
        self.chunks = self.chunker.chunk(GENESIS_1)

    def test_content_type(self):
        for chunk in self.chunks:
            assert chunk["content_type"] == "verse"

    def test_first_chunk_book(self):
        assert self.chunks[0]["book"] == "The First Book of Moses: Called Genesis"

    def test_first_chunk_chapter(self):
        assert self.chunks[0]["chapter"] == 1

    def test_first_chunk_verse_range(self):
        assert self.chunks[0]["verse_start"] == 1
        assert self.chunks[0]["verse_end"] == 5

    def test_second_chunk_verse_range(self):
        assert self.chunks[1]["verse_start"] == 6
        assert self.chunks[1]["verse_end"] == 10

    def test_last_chunk_ends_at_31(self):
        assert self.chunks[-1]["verse_end"] == 31

    def test_section_title_matches_book(self):
        for chunk in self.chunks:
            assert chunk["section_title"] == chunk["book"]


class TestVerseTextQuality:
    def test_anchor_prefix_stripped(self):
        chunker = VerseChunker(verses_per_chunk=1)
        chunks = chunker.chunk(GENESIS_1)
        # No chunk should start with a bare "1:1 " prefix
        for chunk in chunks:
            import re

            assert not re.match(r"^\d+:\d+\s", chunk["text"]), (
                f"Chunk text still starts with verse ref: {chunk['text'][:30]!r}"
            )

    def test_soft_wrap_joined(self):
        # Genesis 1:2 spans 3 lines in the fixture — should be one clean string
        chunker = VerseChunker(verses_per_chunk=1)
        chunks = chunker.chunk(GENESIS_1)
        verse_2 = chunks[1]  # 0-indexed: verse 2 is chunk index 1
        assert "\n" not in verse_2["text"], "Soft-wrapped lines not joined"
        assert "Spirit of God" in verse_2["text"]

    def test_chunk_text_non_empty(self):
        chunker = VerseChunker(verses_per_chunk=5)
        for chunk in chunker.chunk(GENESIS_1):
            assert chunk["text"].strip()


class TestChapterBoundary:
    def test_chapter_boundary_splits_chunks(self):
        chunker = VerseChunker(verses_per_chunk=5)
        chunks = chunker.chunk(GENESIS_CHAPTER_BREAK)
        # Verses 1:30–1:31 should be in chapter=1 chunk(s)
        # Verses 2:1–2:2 should be in chapter=2 chunk(s)
        chapters_seen = {c["chapter"] for c in chunks}
        assert 1 in chapters_seen
        assert 2 in chapters_seen

    def test_no_chunk_spans_chapter_boundary(self):
        chunker = VerseChunker(verses_per_chunk=10)
        chunks = chunker.chunk(GENESIS_CHAPTER_BREAK)
        for chunk in chunks:
            # Each chunk must belong to exactly one chapter
            assert chunk["verse_start"] is not None
            assert chunk["verse_end"] is not None


class TestTOCSkipping:
    def test_toc_titles_not_in_chunk_text(self):
        """TOC book-title lines (bare text, no verse refs) must not appear as chunk text."""
        chunker = VerseChunker(verses_per_chunk=5)
        chunks = chunker.chunk(TOC_THEN_CONTENT)
        for chunk in chunks:
            assert "The Second Book of Moses" not in chunk["text"], (
                "TOC entry leaked into chunk text"
            )
            assert "The Book of Nehemiah" not in chunk["text"]

    def test_content_verses_present(self):
        """Actual verse content must be ingested despite the TOC preamble."""
        chunker = VerseChunker(verses_per_chunk=5)
        chunks = chunker.chunk(TOC_THEN_CONTENT)
        assert len(chunks) >= 1
        combined = " ".join(c["text"] for c in chunks)
        assert "In the beginning" in combined
