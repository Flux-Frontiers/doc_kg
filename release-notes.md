# Release Notes — v0.15.8

> Released: 2026-06-10

DocKG 0.15.8 is a calibration release for the hybrid retrieval pipeline introduced in
v0.15.7. The headline result: **exact-phrase recall@15 nearly doubles (0.37 → 0.67)**
while labeled gold-set retrieval stays within 1 pp of the dense-only baseline — the
hybrid lexical channel now delivers the benefit it was designed for without taxing
ordinary semantic queries.

## What changed

**Dual-distance lexical seeds.** Benchmarking exposed that the single synthetic
distance assigned to BM25-only seeds could not be made safe: set low, one lexical hit's
expansion neighbourhood evicted every dense result from the top-k (−14 pp recall on the
gold set, 7 of 34 queries wiped to zero); set high, the exact-phrase match itself was
buried under dense-seeded expansion noise. The fix splits the two roles — a lexical
seed now ranks *itself* just behind the best dense hit while its *neighbourhood*
inherits a conservative distance. An exact lexical match is strong evidence for the
matching chunk, weak evidence for its structural neighbours.

**Scope-prefilter correctness.** The LanceDB side of query-time scope pushdown treated
`%` and `_` in path prefixes as SQL wildcards (so `doc_kg/` could also match
`docXkg/`); it now uses literal `starts_with()` matching, identical to the SQLite FTS5
channel and the post-expansion scope guard.

**A standard recall benchmark.** `benchmarks/recall_bench.py` makes these measurements
repeatable: it A/Bs seeding conditions over prebuilt corpora using the gutenberg_kg
labeled gold set (cost side) plus auto-generated, unique-in-book exact-phrase queries
(benefit side), without modifying any corpus artifacts. Run it before shipping any
future seeding change.

**Query-path documentation.** `docs/query_path_visual.md` documents the full hybrid
query path — both seed channels, scope gates, RRF fusion, expansion, ranking, and
guards — as an image-generation brief plus a per-stage technical reference.

## Upgrading

Corpora built before v0.15.7 need a one-time `dockg reindex-fts` to gain the hybrid
lexical channel this release calibrates — no re-embedding required. Corpora built on
v0.15.7+ pick up the improvements automatically; no rebuild needed.

---

_Full details: [CHANGELOG.md](CHANGELOG.md)_
