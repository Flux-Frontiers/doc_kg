# Release Notes -- v0.30.0

> Released: 2026-11-04

A chunk's text is now the stretch of the source it covers, blank lines and
line breaks included. Before, the chunkers rebuilt each chunk by joining its
sentences with single spaces, so every paragraph break between two sentences
disappeared. Plays showed it worst: a speaker's name ran into the line before
it ("battlements. DUNCAN. O valiant cousin!"). Where chunks split has not
changed, so a rebuilt store has the same chunks under the same ids.

## What changed

**Chunk text keeps the source's whitespace.** Each chunk carries
`text[char_start:char_end]` from its document. The chunkers still measure
sizes on the joined sentences, so boundaries do not depend on whitespace:
across the 265 books and 13,286 diary entries of the GutenbergKG corpus,
every document gives the same number of chunks with the same words as
before, and 147,067 chunks get their whitespace back. Embeddings are
unaffected, since the tokenizer ignores whitespace. `VerseChunker` is
unchanged; it collapses whitespace on purpose.

**Chunk offsets are right when a sentence repeats.** A chunk's start was
taken from the first copy of its first sentence after the previous chunk.
A play repeats short sentences such as "MACBETH." within that reach, so
`char_start` and `char_end` could point at the wrong text. The span is now
the first one that holds the chunk's sentences in order. In the GutenbergKG
corpus this moves `char_start` forward on 3,443 of 396,615 book chunks, each
of which was misplaced before.

## Upgrading

Rebuild a corpus to get the new text: `dockg build`. Index-based ids
(`chunk:<file>:NNNN`) and chunk counts stay the same, so references to
chunks keep resolving. Two things do change:

- Ids from the multipass pipeline's `make_chunk_id` hash the chunk text, so
  they change for every chunk whose whitespace is restored.
- An incremental embed (`only_missing=True`) skips ids that already have a
  vector, so the vector store's `text` column keeps the old joined text. The
  vectors are the same; embed in full if you read text from the vector store.

---

_Full changelog: [CHANGELOG.md](CHANGELOG.md)_
