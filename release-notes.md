# Release Notes — v0.18.1

> Released: 2026-07-15

A small maintenance release with two build-time fixes: `dockg build` no longer
leaves its intermediate embedding cache behind, and long index builds are no
longer drowned in per-batch telemetry. No schema change, no re-index, no API
change.

## What changed

**`dockg build` cleans up its embedding cache.** The main build command wrote an
intermediate `embeddings.json` in the embed phase and consumed it in the index
phase, but never deleted it — so every corpus's `.dockg/` accumulated the cache
(one even leaked into a sibling project's staging area). The cache is now removed
after a successful index. A new `--keep-cache/--delete-cache` flag (default
`--delete-cache`) lets you retain it, e.g. to feed `dockg build-index-from-cache`.
`dockg pipeline` was never affected — it keeps embeddings in memory.

**Quieter builds.** `SemanticIndex.build()` printed an `ingest : …` telemetry line
every 25 batches, which floods the console on large corpus builds. It is now
silent by default and opt-in via `DOCKG_EMBED_TELEMETRY` (`1`/`true`/`yes`/`on`).
The periodic allocator cache-release still runs, so long-build memory behaviour is
unchanged.

## Upgrading

Nothing to do — no schema or index change. If any tooling relied on
`embeddings.json` lingering in `.dockg/` after `dockg build`, pass `--keep-cache`
to preserve the old behaviour.

---

_Full changelog: [CHANGELOG.md](CHANGELOG.md)_
