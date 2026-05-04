# Release Notes — v0.14.0

> Released: 2026-05-04

## Highlights

**Bounded SIMILAR_TO graph density.** On stylistically homogeneous corpora — academic papers, internal docs, code from a single author — the legacy "every pair above the cosine threshold" rule for `SIMILAR_TO` edges was effectively quadratic: most chunk pairs sat just above 0.85 similarity, and the edge table grew with `O(N²)` per build. v0.14.0 caps each chunk at the **top-`k` most-similar peers** (default `k=5`), keeping recall on the genuine semantic neighbours while preventing edge blow-up.

## What changed

- **New CLI flags on `dockg build`:** `--similar-k` (default `5`) and `--similar-threshold` (default `0.85`). Set `--similar-k 0` to opt back into the v0.13.0 "all pairs above threshold" behaviour.
- **New kwargs on `DocKG.build()` / `build_index()` / `build_from_cache()`:** `similar_k` and `similarity_edge_threshold`. The defaults match the CLI, so existing callers get the bounded behaviour automatically.
- **Edges are now canonical and undirected.** Each pair `(a, b)` is emitted exactly once with `src=min(a, b)`, `dst=max(a, b)`. The SQLite `(src, rel, dst)` PRIMARY KEY handles the asymmetric top-k case where `A` picks `B` but `B` doesn't pick `A`. Self-similarity is masked to `-inf` so it can never occupy a top-k slot.

## Compatibility

Backward compatible. The defaults change the *shape* of the SIMILAR_TO subgraph (fewer, higher-quality edges) but no public API was renamed or removed. Rebuilding the index against an existing graph store is sufficient to adopt the new behaviour.

---

_Full changelog: [CHANGELOG.md](CHANGELOG.md)_
