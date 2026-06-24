# Release Notes — v0.16.0

> Released: 2026-06-24

DocKG 0.16.0 adds a **row-count-gated approximate-nearest-neighbour (ANN) index** to the
LanceDB vector store. Below a configurable threshold the exact flat cosine scan is
unchanged (sub-millisecond, exact); above it, `SemanticIndex` builds an IVF index
automatically and `search()` uses it transparently. On the 683k-vector gutenberg-all
corpus this cuts query latency **~64 ms → ~12 ms end-to-end** with no change to the
embedding model or ranking. The change is additive and backward-compatible — small
corpora are untouched, and consumer repos inherit it through `DocKG.build_index_from_cache`
with no code changes.

## What changed

**Gated IVF index.** Once a table crosses `ann_threshold` (default 50k rows), the index is
built at the end of every build path and consumed by `search()`; below it, nothing changes.
Defaults are `IVF_FLAT` (full vectors — exact within probed cells, best recall; `IVF_PQ`
available for disk-constrained or multi-million-scale corpora), `nprobes=50`, and
`refine_factor=0`, all overridable via `DOCKG_ANN_*` environment variables. Index-build
failures fall back to the flat scan, so the index is never load-bearing.

**Validated against the exact scan.** Because only *which* vectors get scored changes — the
embeddings and cosine ranking are held fixed — the index is validated by fidelity to the
exact flat scan on real queries rather than by gold labels. IVF_FLAT reproduces **0.91 of
the exact top-10 with 94% top-1 retention** at `nprobes=50`. The new
`benchmarks/ann_recall_bench.py` makes this measurement repeatable, and
`docs/design-ann-index.md` records the design and full benchmark results.

**Incremental embedding and pruning.** Also folded into this release: embedding now skips
nodes already present in the index (`build_embeddings(only_missing=True)`), and orphaned
vectors left by removed or renamed nodes can be cleared (`DocKG.prune_index()` /
`SemanticIndex.prune()`) — so incremental updates neither re-embed unchanged content nor
leave stale hits behind.

## Upgrading

No action is required for small corpora — they keep the exact flat scan. Large corpora
(>50k vectors) pick up the IVF index automatically on the next build; because the index is
derived and disposable, it can also be added to an existing index without re-embedding.
Tune recall versus latency at query time with `DOCKG_ANN_NPROBES` if needed.

---

_Full changelog: [CHANGELOG.md](CHANGELOG.md)_
