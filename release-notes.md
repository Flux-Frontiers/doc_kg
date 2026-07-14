# Release Notes — v0.18.0

> Released: 2026-07-14

DocKG 0.18.0 adds a second vector store: an exact **`sqlite-vec`** backend that lives beside
LanceDB behind a pluggable seam. On the consolidated Gutenberg corpus it returns the exact
top-k (recall@10 = 1.0) where LanceDB's approximate index averaged ~0.825 — surfacing hits
the old index quietly dropped — while taking roughly a tenth of the disk and keeping query
latency in the same class. Vectors move over with a converter that reads them straight out
of an existing LanceDB table, so adopting it is a conversion, never a re-embed. LanceDB
stays fully supported; the default is `auto`, which does the right thing without a flag.

## What changed

**Pluggable vector backend.** `SemanticIndex` now routes all vector storage through a
`VectorBackend` seam (from `kgmodule-utils>=0.5.0`). The new `sqlite-vec` store is a sidecar
`.dockg/vectors.sqlite` — an exact brute-force cosine index that unifies dense vectors, FTS5,
and the graph on one storage engine. Public API is unchanged; the switch is a single knob,
via `DocKG(vector_backend=...)`, the `DOCKG_VECTOR_BACKEND` env var, or
`dockg build/query --vector-backend`.

**An `auto` default that won't surprise you.** Backend selection defaults to `auto`: fresh
and already-converted corpora build and read `sqlite-vec`, while a corpus that still has only
a LanceDB store keeps using LanceDB untouched. Nothing silently changes store type under an
existing index; forcing either backend is always one flag away.

**Convert without re-embedding.** `dockg convert-index --to sqlite-vec [--dtype fp32|int8]`
reads vectors directly out of a LanceDB table and writes `vectors.sqlite`, validating the row
count and re-reading a sample to prove the conversion is lossless. `--delete-lancedb` reclaims
the old store's space, but only after that validation passes.

**Internals consolidated.** The LanceDB table plumbing and the IVF/ANN index machinery moved
out of `doc_kg` into `kgmodule-utils`' `LanceDBBackend` (ANN applies to LanceDB only —
`sqlite-vec` is exact by construction). `DocKG.stats()` now reports the active
`vector_backend` and `vector_count`.

## Upgrading

No rebuild required. Existing LanceDB corpora keep working exactly as before under the `auto`
default. To move a corpus to the smaller, exact store, run `dockg convert-index --to
sqlite-vec` (optionally `--delete-lancedb` once you've confirmed it) — no model load, no
re-embedding. `sqlite-vec` is an opt-in dependency: `pip install 'doc-kg[sqlite-vec]'`.
`kgmodule-utils>=0.5.0` is pulled in automatically on install.

---

_Full changelog: [CHANGELOG.md](CHANGELOG.md)_
