# Verse / Sacred Text Ingestion Plan
**Project:** doc_kg
**Date:** 2026-05-06
**Author:** Eric G. Suchanek, PhD
**Status:** In progress

---

## Background

doc_kg's current `TextChunker` is designed for prose Markdown (technical docs,
READMEs, narrative text).  Verse / sacred-text documents have a fundamentally
different structure: each line (or short paragraph) is an addressable **verse**
identified by a canonical reference (`chapter:verse`), grouped into chapters,
and chapters into books.

The immediate target is the KJV Bible at:

    gutenberg_kg/corpus/sacred-texts/The Bible (King James Version)/the_bible.md

Stats: **99,356 lines**, **24,995 verse-anchored lines**.

The diary_kg project is the closest analogue: diary entries are similarly
"anchored" (by ISO timestamp), grouped (by date/phase), and need per-entry
rather than per-sentence chunking.

---

## Structural Problems with Current Pipeline

### 1. TOC duplication
Lines 1–104 of the_bible.md are a table-of-contents — all 66 book titles
listed as `##` headings and plain-text/italicized entries, with NO verse content.
Lines 105+ repeat those `##` headings immediately followed by verse content.

Current `_split_by_headings` treats the TOC headings as real sections, so each
TOC book "section" has empty body text, then a second real section for the
actual content.  The TOC section for "The Old Testament" heading (line 7) would
accumulate all non-`##` TOC entries (Ezra, Proverbs, Ecclesiastes, …) as
unstructured body text.

### 2. Verse references are invisible to the chunker
Chapters have **no Markdown heading** — only books get `##`.  Every verse begins
with `chapter:verse ` (e.g. `1:1`, `12:31`) and may soft-wrap across 2–3
lines.  The chunker never sees these as boundaries, so one chapter becomes a
single large blob handed to `_semantic_chunks()`.

### 3. `_SENT_SPLIT` misfires on KJV prose
The sentence-splitting regex (`(?<=[.!?])\s+(?=[A-Z\"\'...])`) splits at `.`
followed by a capital, which works for modern prose but not KJV:

- Mid-verse abbreviations fire false splits
- Poetic parallelism (successive short clauses) creates micro-chunks
- Archaic conjunctions at line-start (`And`, `But`) look like sentence starts
  even in the middle of a verse

### 4. No content_type / verse metadata on DocNode
`DocNode` and `SourceProvenance` have no fields for:
- `content_type` (`"verse"` vs `"prose"` vs `"diary"`)
- `book`, `chapter`, `verse_start`, `verse_end`

Downstream queries cannot filter by canonical address or content kind.

---

## Implementation Plan

### Step 1 — Data model additions

**File:** `src/doc_kg/entry_chunk.py`

Add to `SourceProvenance`:
```python
content_type: str | None = None    # "prose" | "verse" | "poetry" | "diary"
book: str | None = None            # e.g. "Genesis"
chapter: int | None = None
verse_start: int | None = None
verse_end: int | None = None
```

Update `EntryChunk.to_node_dict()` to include all five new fields.

**File:** `src/doc_kg/dockg.py`

Add to `DocNode`:
```python
content_type: str | None = None
book: str | None = None
chapter: int | None = None
verse_start: int | None = None
verse_end: int | None = None
```

These fields are `None` for all existing prose documents — no behaviour change.

---

### Step 2 — VerseChunker (`chunker.py`)

Add a new chunking strategy: `"verse"`.

#### Key regex
```python
_VERSE_REF = re.compile(r"^(\d+):(\d+)\s+", re.MULTILINE)
```

#### `VerseChunker` class

```python
class VerseChunker:
    def __init__(self, *, verses_per_chunk: int = 5, min_chunk_chars: int = 50): ...
    def chunk(self, text: str, *, file_path: str = "") -> list[dict]: ...
```

Algorithm:

1. **Skip preamble** — find the position of the first verse reference
   (`_VERSE_REF`).  Everything before it is discarded (or emitted as a single
   `section_level=None` preamble chunk if it contains substantive prose).

2. **Split by book heading** — run `_split_by_headings()` as before, but only
   on text from the first verse reference onward.  Each `##` heading gives the
   current `book` name.

3. **Within each book section, split by chapter** — scan verse refs; when the
   chapter number increments, start a new logical chapter group.

4. **Within each chapter, collect verses** into groups of `verses_per_chunk`
   (default 5).  Each verse is:
   - identified by its `chapter:verse` anchor
   - reconstructed by joining soft-wrapped continuation lines (everything up to
     the next `chapter:verse` ref or the end of the chapter)

5. **Emit chunk dicts** — same schema as existing chunks, plus the new fields:
   ```python
   {
       "text":          str,       # verse text, anchor prefix stripped
       "section_title": str,       # book name (from ## heading)
       "section_level": 2,
       "char_start":    int,
       "char_end":      int,
       "references":    [],
       "content_type":  "verse",
       "book":          str,       # e.g. "Genesis"
       "chapter":       int,       # e.g. 1
       "verse_start":   int,       # first verse in this chunk
       "verse_end":     int,       # last verse in this chunk
   }
   ```

6. **Auto-detection** — `VerseChunker.is_verse_document(text)` returns `True`
   if >10 % of non-blank lines match `_VERSE_REF`.  Used by `parse_corpus` for
   automatic strategy selection.

#### `chunker_for()` update
Add case:
```python
case "verse":
    return VerseChunker(
        verses_per_chunk=sentences_per_chunk,
        min_chunk_chars=min_chunk_chars,
    )
```

---

### Step 3 — Wire through `parse_corpus()` (`dockg.py`)

Changes:

1. **Auto-detection in the file loop** — after reading file text, call
   `VerseChunker.is_verse_document(text)`.  If `True` and `chunk_strategy` is
   not explicitly `"verse"`, switch the chunker for this file only.

2. **Propagate extra chunk fields to `DocNode`** — in the chunk-to-node builder,
   if the chunk dict contains `content_type`, copy `content_type`, `book`,
   `chapter`, `verse_start`, `verse_end` into the `DocNode`.

3. **`topics_file_map` parameter** — new `dict[str, str] | None` parameter
   keyed by glob pattern:
   ```python
   topics_file_map: dict[str, str] | None = None
   # e.g. {"sacred-texts/*": "topics/sacred-texts.topics.yaml"}
   ```
   For each file, resolve the matching pattern (first match wins) and
   instantiate a `TopicExtractor` with that file's topics.  Falls back to the
   global `topics_file`.

4. **New edge relation** (optional, additive): `VERSE_IN_CHAPTER` — a
   chapter-level pseudo-node (`kind="chapter"`) that verse chunk nodes are
   linked to.  Enables canonical navigation: `Genesis → chapter 1 → verses 1–5`.
   This is **deferred** until the basic verse chunker is validated.

---

### Step 4 — Sacred-text topics catalog

**File:** `src/doc_kg/topics/sacred-texts.topics.yaml`

```yaml
# Sacred-text topic catalog for DocKG
# Used with topics_file_map: {"sacred-texts/*": "topics/sacred-texts.topics.yaml"}
topics:
  - name: Creation
    keywords: [created, heaven, earth, beginning, formed, made, void, darkness]
  - name: Covenant
    keywords: [covenant, promise, oath, swear, everlasting, blood, sign]
  - name: Law
    keywords: [commandment, statute, ordinance, law, Moses, shall not, transgress]
  - name: Prophecy
    keywords: [thus saith, behold, shall come, vision, prophesy, oracle, burden]
  - name: Gospel
    keywords: [Jesus, Christ, kingdom, repent, baptize, salvation, grace, faith]
  - name: Epistle
    keywords: [brethren, therefore, justified, sanctified, holy spirit, grace peace]
  - name: Wisdom
    keywords: [wisdom, understanding, fear of the Lord, proverb, heart, folly]
  - name: Lament
    keywords: [cry, mourn, weep, affliction, sorrow, forsake, desolate, grief]
  - name: Praise
    keywords: [praise, sing, hallelujah, bless, glorify, exalt, worship, thanksgiving]
  - name: Narrative
    keywords: [went, said, came, arose, king, battle, slew, gathered, children of Israel]
  - name: Apocalyptic
    keywords: [beast, seal, trumpet, vision, dragon, thousand years, lake of fire, throne]
  - name: Ethics
    keywords: [love, neighbor, just, righteous, mercy, compassion, forgive, humble]
```

For Quran, Upanishads, or other sacred texts: create a parallel YAML with
domain-appropriate keywords.  The `content_type="verse"` tag makes all verse
chunks queryable together regardless of source.

---

### Step 5 — Per-document topic extraction

**Problem:** current `parse_corpus` instantiates one global `TopicExtractor`.
For heterogeneous corpora (technical docs + sacred texts + diary entries),
per-document (or per-path-pattern) topic routing is more accurate.

**Solution:** `topics_file_map: dict[str, str] | None` in `parse_corpus`.

Resolution order per file:
1. Check `topics_file_map` patterns (glob match against relative file path)
2. Fall back to global `topics_file`
3. Fall back to built-in default topics

Implementation: cache `TopicExtractor` instances keyed by resolved YAML path to
avoid re-loading per file.

---

### Step 6 — Tests

**File:** `tests/test_verse_chunker.py`

Fixture: Genesis chapter 1 (verses 1:1–1:31) as a raw string literal.

Test cases:
1. `test_verse_detection` — `VerseChunker.is_verse_document()` returns `True`
   for the Genesis fixture, `False` for a prose paragraph.
2. `test_verse_chunk_count` — Genesis 1 (31 verses) with `verses_per_chunk=5`
   produces ceil(31/5) = 7 chunks.
3. `test_verse_metadata` — first chunk has `book="Genesis"`, `chapter=1`,
   `verse_start=1`, `verse_end=5`, `content_type="verse"`.
4. `test_verse_text_clean` — chunk text does not contain the `1:1 ` prefix.
5. `test_soft_wrap_join` — a verse whose text soft-wraps across two lines is
   reconstructed as a single string.
6. `test_toc_skipped` — running `VerseChunker` on the full bible.md produces no
   chunk whose text is a bare book-title line from the TOC.
7. `test_chapter_boundary` — last verse of chapter 1 and first verse of chapter
   2 appear in different chunks.

---

## File Change Summary

| File | Change |
|------|--------|
| `src/doc_kg/entry_chunk.py` | +5 fields on `SourceProvenance`; update `to_node_dict()` |
| `src/doc_kg/dockg.py` | +5 fields on `DocNode`; auto-detect verse; `topics_file_map`; propagate chunk extras |
| `src/doc_kg/chunker.py` | `VerseChunker` class; `is_verse_document()`; `"verse"` case in `chunker_for()` |
| `src/doc_kg/topics/sacred-texts.topics.yaml` | New file — sacred-text topic catalog |
| `tests/test_verse_chunker.py` | New file — 7 test cases |

No existing tests should break — all new fields are `None`-defaulted and the
`"verse"` strategy is opt-in.

---

## Deferred / Future Work

- **`VERSE_IN_CHAPTER` edge** — chapter pseudo-nodes for canonical navigation.
- **Quran / Upanishads** — parallel topic catalogs once the Bible pipeline validates.
- **Poetry mode** — `VerseChunker` variant that handles numbered stanzas without
  `chapter:verse` refs (e.g., Psalms poetry, Proverbs couplets).
- **Cross-reference edges** — KJV has textual cross-references (e.g., John 3:16
  ↔ Romans 5:8); these could become `CROSS_REFERENCES` edges once the canonical
  address structure is in place.
