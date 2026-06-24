# Design: Row-count-gated ANN index for `SemanticIndex`

Status: draft · Branch: `feat/ann-index-gate` · Owner: doc_kg

## Problem

`SemanticIndex` (LanceDB) never calls `create_index()`. Every query is a
brute-force flat cosine scan over the whole table. Measured on the
`gutenberg-all` bundle (683,001 vectors, 384-d):

- ~64 ms / query (no filter), ~100+ ms with a `kind` prefilter
- latency grows **linearly** with corpus size
- one undifferentiated table — a chunk query still scans the 335k
  topic/entity/keyword vectors it will discard

Small corpora (e.g. doc_kg itself, ~3.3k rows; per-book gutenberg DocKGs)
are *correctly* served by flat scan — exact and sub-ms. The fix must not
regress them.

## Goal

Add an **IVF index, gated on row count**, built automatically at the end of
the index build, and consumed transparently at search time. Additive and
backward-compatible: no API breaks, no required changes in consumer repos
(gutenberg_kg, diary_kg) — they inherit it through `DocKG.build_index_from_cache`.

Non-goals (deferred): kind-separated tables (Opt 2), SIMILAR_TO scale guard
(Opt 3), binary cache (Opt 4), model upgrade (Opt 5).

## Design

### Where it lands

`doc_kg` only. gutenberg_kg is a pure consumer:

- per-book builds → `ingest.py:221 build_index_from_cache(...)` → small → gate skips
- merged bundle  → `build_corpus.py:478 build_index_from_cache(...)` → 683k → gate fires

Single shared helper called by all three build paths after rows are loaded:

- `SemanticIndex.build` (direct-from-store)
- `SemanticIndex.build_from_cache` (`EmbeddingCache` path)
- `SemanticIndex._build_from_jsonl_cache` (streaming JSONL path)

### New helper

```python
def _maybe_create_ann_index(self, tbl, *, quiet: bool) -> bool:
    """Build an IVF index when the table is large enough to benefit.

    Below ``self.ann_threshold`` rows, an exact flat scan is faster and
    more accurate, so no index is built. At or above it, build an IVF
    index on the ``vector`` column with cosine metric. Failures are
    logged and swallowed — flat scan remains correct, so indexing is
    never load-bearing.
    """
```

Called after the final `tbl.add(...)` / SIMILAR_TO pass, before the stats
dict is returned. Idempotent on rebuild (drop/replace, or skip if present
and row count unchanged).

### Parameters (constants, overridable via `__init__` + env)

| Knob | Default | Rationale |
|---|---|---|
| `ann_threshold` (rows) | `50_000` | Below this, flat scan wins. 683k ≫ 50k; 3.3k ≪. |
| index type | `IVF_FLAT` | Full vectors → exact within probed cells, best recall, no refine tax. PQ is the disk-constrained / multi-million-scale opt-in. |
| `num_partitions` | `≈ sqrt(n)` clamped | √683k ≈ 826; standard IVF heuristic. |
| `num_sub_vectors` | `dim / 16` (=24 @ 384) | PQ-only subspace count; must divide dim. Unused for IVF_FLAT. |
| metric | `cosine` | Matches `search()` + normalized embeddings. |
| `nprobes` (search) | `50` | On real text queries: 0.91 fidelity@10 / 94% top-1 vs exact, vs 0.83 / 81% at 20 — no latency cost. |
| `refine_factor` (search) | `0` | No-op for FLAT (full vectors); PQ needs ≥10 to recover recall. |

Env overrides: `DOCKG_ANN_THRESHOLD`, `DOCKG_ANN_INDEX_TYPE`,
`DOCKG_ANN_NPROBES`, `DOCKG_ANN_REFINE_FACTOR` (so the gutenberg bundle build
can switch to IVF_PQ and tune without code changes).

### Benchmark (683k-vector gutenberg-all bundle, 384-d, real query points)

| Index | nprobes | refine | recall@10 | latency | index size |
|---|---|---|---|---|---|
| flat (exact) | — | — | 1.000 | ~64 ms | 0 |
| IVF_FLAT | 20 | 0 | 0.926 | ~2.3 ms | ~1.0 GB |
| IVF_FLAT | 50 | 0 | 0.982 | ~5.8 ms | ~1.0 GB |
| IVF_PQ | 20 | 10 | 0.904 | ~5.3 ms | ~tens of MB |
| IVF_PQ | 20 | 0 | 0.596 | ~2.2 ms | ~tens of MB |

IVF_FLAT chosen as default: dominates PQ on the recall/latency frontier here;
the only cost is ~1 GB disk, acceptable when the table itself is already 1.6 GB.

### Real-query fidelity (`benchmarks/ann_recall_bench.py`)

The gold labels were built against the per-book indices and do **not** map onto
the re-chunked bundle, so the index is validated by **fidelity to the exact flat
scan** on the 36 real human gold query *texts* (labels ignored): for the same
query on the same corpus, how much of the exact top-k does IVF_FLAT reproduce?

| nprobes | fidelity@10 vs exact | top-1 retained | end-to-end p50 |
|---|---|---|---|
| 10 | 0.717 | 75.0% | ~14 ms |
| 20 | 0.825 | 80.6% | ~14 ms |
| **50 (default)** | **0.911** | **94.4%** | ~12 ms |
| 100 | 0.942 | 97.2% | ~13 ms |

Real text queries are harder than sampled corpus vectors (the query is not
itself a corpus point), so nprobes=20 was too low; nprobes=50 is the chosen
default. Latency is dominated by query embedding (~10 ms), not the index, so
raising nprobes is effectively free. Run with::

    PYTHONPATH=src python benchmarks/ann_recall_bench.py \
        --lancedb ../gutenberg_kg/bundles/gutenberg-all/.dockg/lancedb \
        --gold ../gutenberg_kg/analysis/similar_to_query_template.csv \
        --nprobes 10,20,50,100 --k 10

### Search-time change

`SemanticIndex.search` adds `.nprobes(...)` and `.refine_factor(...)` to the
LanceDB query builder **only when an index exists** (probe `tbl.list_indices()`
once, cache the result). With no index the call path is byte-for-byte today's
flat scan — guarantees small corpora are untouched.

## Risk & mitigation

- **Approximate recall.** IVF is approximate. Mitigated by `refine_factor`
  re-ranking + a recall benchmark gate (see Validation). `nprobes`/threshold
  are tunable without re-embedding.
- **Index build cost.** One-time, post-embed. Negligible vs the embed itself.
- **LanceDB version drift.** `create_index` signature varies by version.
  Wrap in try/except; on failure, log and fall back to flat scan.
- **Regression on small corpora.** Prevented by the threshold gate + the
  "index exists?" check in `search`.

## Validation

1. Unit: gate skips below threshold, builds at/above; `search` adds probes
   only when an index exists.
2. Recall benchmark (`project_recall_benchmark`, gold set in
   `../gutenberg_kg`): IVF vs flat MRR@k delta within tolerance at default
   `nprobes`; sweep `nprobes` to chart recall/latency.
3. Latency: re-time the 683k bundle (target single-digit ms vs 64 ms flat).

## Rollout

1. Land helper + gate + search probes behind defaults (this branch).
2. Rebuild `gutenberg-all` bundle; confirm `list_indices()` non-empty and
   latency/recall numbers.
3. No consumer-repo changes; bump doc_kg, gutenberg picks it up on next build.
