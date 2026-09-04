# Release Notes -- v0.23.0

> Released: 2026-09-03

A bug-fix release for one defect with two halves: section nodes carried the wrong
character offsets, and a heading that repeated within a document collapsed into a single
node. Retrieval was never affected -- chunk offsets and vectors were always correct -- but
anything that reconstructed a chapter from a section's span read the wrong text, and in
the worst case read almost none of it.

## What changed

**Sections now span the chunks they contain.** A guard in `parse_corpus` compared a
section's node id against a dictionary keyed by its slug. The two never matched, so the
guard never fired and every chunk rebuilt its section's node in turn, leaving the last
chunk's offsets behind. A section's start therefore pointed at its own closing paragraph.
Consumers that rebuild a chapter as "the chunks from this section's start to the next
section's" got most of the following chapter instead of the one they asked for. A document
held in a single section was worse: with no next section to bound the range, it returned
only its final paragraph. That is how this surfaced -- a book with no chapter headings
browsing as four hundred characters of transcriber's notes.

**A repeated heading is no longer one node.** Section ids were built from the slug alone,
so a book whose volumes each restart at `Chapter I`, or one carrying several `Preface`
sections, gave every occurrence the same id and merged them. Measured against a real
corpus, this was not an edge case: of 406 Markdown files carrying headings, 106 of them
(26%) repeat at least one, and 3,551 of 14,797 section occurrences (24%) were being merged
away. Verse and drama are hit hardest, where the speaker is the heading -- one text has 187
sections titled `Mephistopheles` -- but ordinary prose is affected too, since multi-volume
novels restart their chapter numbering.

Each occurrence now gets its own node. The first keeps the plain `sec:<file>:<slug>` id, so
ids are unchanged for any document without a repeated heading; later occurrences take a
`~<n>` suffix. `slugify` strips `~`, so that suffix can never collide with an id a real
heading could produce.

**Node id documentation now matches the code.** `docs/SCHEMA.md` and `docs/CHEATSHEET.md`
documented section ids as `section:<path>:<slug>` and document ids as `document:<file>`,
while the code emits `sec:` and `doc:`. Anyone copying an id out of those documents, including
two worked `get_node` examples, got a miss.

## Upgrading

`pip install --upgrade doc-kg`. The fix applies to graphs built after it, so **rebuild any
existing index** rather than upgrading in place.

Offsets alone could be repaired without re-embedding, by setting each section's bounds from
the chunks it contains. Recovering the split sections cannot: a merged node holds no record
of where one occurrence ended and the next began. If your corpus has repeated headings, a
rebuild is the only complete repair.

There are no new options and no API changes. `section_node_id` gained an optional
`occurrence` argument that defaults to the previous behaviour.

---

_Full changelog: [CHANGELOG.md](CHANGELOG.md)_
