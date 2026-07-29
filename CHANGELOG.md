# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

### Changed

### Removed

### Fixed

## [0.19.0] - 2026-07-28

### Changed

- **`transformers` unpinned: `>=4.40.0,<4.57` → `>=5.5.0,<6`.** The old cap held
  the stack at 4.56.2, which carries two open high-severity advisories — remote
  code execution (fixed in 5.3.0) and arbitrary code execution in the LightGlue
  model-loading path (fixed in 5.5.0). The cap was introduced without a recorded
  rationale, bundled into an unrelated commit, and no longer matched anything:
  doc-kg 0.12.3 had already shipped on transformers 5.6.2, and the `<4.57` value
  was aligned to a `personal_agent` constraint that has since moved.

  **This is a breaking dependency change** — the old and new ranges are disjoint,
  so an environment holding transformers 4.x can no longer install doc-kg.

  **Embeddings are unaffected and no re-index is required.** Verified against
  transformers 5.14.1 with the rest of the stack unchanged: vectors are *bitwise
  identical* on `bge-small-en-v1.5` (384d), `bge-large-en-v1.5` (1024d) and
  `nomic-embed-text-v1.5` (768d, the `trust_remote_code` path), across empty,
  whitespace-only, 3000-character, unicode/emoji and CRLF inputs. A full rebuild
  of a 2847-vector corpus produces a *byte-identical* `vectors.sqlite`, and
  queries against an index built on 4.56.2 return identical rankings and scores.

  `huggingface-hub` moves from 0.36.x to 1.x as a consequence (transformers 5
  requires `>=1.5.0,<2.0`), and `typer` arrives as a new transitive dependency.
  Nothing in the stack caps either, and `rich` still resolves below its `<15`
  cap.

- **`kgmodule-utils` floor raised to `>=0.9.0`.** 0.9.0 is the first release
  carrying both the relaxed transformers range and the
  `transformers.utils.logging` embedder fix. The floor is load-bearing, not
  cosmetic: 0.8.0 scopes its transformers cap to the `semantic` extra, and
  doc-kg requires *plain* `kgmodule-utils`, so the cap never conflicted and the
  resolver was free to keep 0.8.0 — pairing transformers 5 with an embedder
  whose `importlib.import_module("transformers.logging")` raises
  `ModuleNotFoundError` on 5.x and is silently swallowed, disabling log and
  progress-bar suppression.

### Removed

- **The `kgdeps` extra.** `pip install 'doc-kg[kgdeps]'` no longer resolves —
  install the sibling by hand instead: `pip install pycode-kg`. `pycode-kg` was
  also dropped from the `dev` and `all` extras.

  doc-kg and pycode-kg each declared the other in their extras, and Poetry locks
  optional groups too, so once either relaxed its transformers pin no *published*
  sibling could satisfy it and resolution deadlocked — neither could lock until
  the other was released. Nothing under `src/` or `tests/` imports `pycode_kg`;
  the dependency was purely a dev convenience. Removing it breaks the cycle
  permanently, following the pattern memory_kg already uses for the same reason.
  Manual-install instructions replace the extra as a comment in `pyproject.toml`,
  and `docs/INSTALLATION.md` was updated in both its `pip` and `poetry add`
  sections.

## [0.18.2] - 2026-07-26

### Added

- **`DocKG(vectors_path=...)`** — the sqlite-vec store location is now settable
  from the `DocKG` constructor. `doc_kg.index` has always accepted an explicit
  `vectors_path`; `DocKG` was the one layer that neither accepted nor forwarded
  it, so the store was always derived as the sidecar next to `graph.sqlite`
  (`<store>/.dockg/vectors.sqlite`). Callers that track the vector store
  independently — notably the KGRAG registry's `KGEntry.vectors_path` — can now
  point `DocKG` at a store that does not sit beside `lancedb_dir`.

  Defaults to `None`, which reproduces the previous derived-sidecar behaviour
  exactly, so this is backward compatible. The path is forwarded to both
  backend construction sites (`DocKG.index` and `DocKG.stats`) — `stats()`
  builds its own throwaway backend, and had it been missed, a corpus with an
  explicit store would have silently reported `vector_count: 0`.

  Because `make_backend` also passes the path to `resolve_backend_name`, an
  explicit `vectors_path` lets `vector_backend="auto"` resolve to sqlite-vec
  when a store exists there, even with no sidecar at the derived location.

- **`--vectors-path` CLI option** on every command that reads or writes the
  vector store: `build`, `build-index`, `build-index-from-cache`,
  `build-two-phase`, `query`, `pack`, `mcp`, and `snapshot save`. The `mcp`
  command forwards it through its argv hop into `mcp_server.main`, which
  resolves a relative path against `--repo` (matching how `--db` and
  `--lancedb` behave) and reports it in the startup banner.

  Deliberately **not** added to the graph-only commands — `build-graph`,
  `build-embeddings`, `status`, and `reindex-fts` never touch a vector store,
  so the option would be misleading there. A test asserts both the presence
  and the absence, so the boundary does not drift.

### Fixed

- **MCP server startup output printed literal `\n` instead of newlines.**
  The startup banner and the missing-database warning in `mcp_server.main`
  were written with doubled backslashes (`\\n`) inside f-strings, so every
  field collapsed onto a single run-on line in stderr — e.g.
  `DocKG MCP server starting\n  repo     : …\n  db       : …`. Affected all 7
  escapes in the file; nothing else in the codebase had the same defect.
  Regression-tested by asserting the rendered stderr contains no literal
  `\n` and that each field lands on its own line.

- **CI `Lint & Format` failed on Markdown, not on any source file.** ruff
  (>=0.14, pulled in by the recent dependency pins) formats Python code blocks
  embedded in Markdown, so `ruff format --check .` began failing on four
  documents no source change had touched — `docs/SNAPSHOTS.md`, the two
  `benchmarks/*.md`, and a vendored HuggingFace model card under `.kgcache/`.
  `.kgcache` and `*.md` are now excluded in `[tool.ruff]`: prose docs use
  illustrative, deliberately-formatted snippets, and the model card is not ours
  to reformat. All 75 Python files remain covered.

## [0.18.1] - 2026-07-15

### Fixed

- **`dockg build` no longer leaves `embeddings.json` behind.** The main build
  command wrote the intermediate embedding cache in step 2a and consumed it in
  step 2b but never deleted it, littering every corpus's `.dockg/` (one leaked
  into pycode_kg's staging area). The cache is now removed after indexing, with
  a `--keep-cache/--delete-cache` opt-out matching `build-two-phase`'s existing
  convention. `dockg pipeline` was unaffected (in-memory embeddings).

- **Silenced noisy per-batch ingest telemetry during index builds.**
  `SemanticIndex.build()` printed an `ingest : batch=… fragments=… embed_ms_per_row=…`
  line every 25 batches, which floods the console on large corpus builds. It is
  now suppressed by default and opt-in via the `DOCKG_EMBED_TELEMETRY` env var
  (truthy: `1`/`true`/`yes`/`on`). The periodic allocator cache-release still
  runs regardless, so long-build memory behaviour is unchanged.

## [0.18.0] - 2026-07-14

### Added

- **Pluggable vector backend: `sqlite-vec` alongside LanceDB.** `SemanticIndex`
  now routes all vector storage through `kg_utils.vector_backend.VectorBackend`
  (requires `kgmodule-utils>=0.5.0`). Select per-KG with `DocKG(...,
  vector_backend="sqlite-vec")`, the `DOCKG_VECTOR_BACKEND` env var, or
  `dockg build/query --vector-backend sqlite-vec`. The sqlite-vec store is a
  sidecar `.dockg/vectors.sqlite` (exact brute-force cosine, ~10× smaller than
  LanceDB, recall 1.0). Backend selection defaults to `"auto"` (see Changed).
  Opt-in dependency: `pip install 'doc-kg[sqlite-vec]'`.
- `make_backend()` / `sqlite_vectors_path()` helpers in `index.py`;
  `DocKG.stats()` now reports `vector_backend` and `vector_count`.
- **`dockg convert-index --to sqlite-vec [--dtype fp32|int8] [--delete-lancedb]`**
  — convert an existing LanceDB index to a `vectors.sqlite` store with no
  re-embedding (reads vectors straight out of LanceDB, validates row count + a
  vector sample). `--delete-lancedb` reclaims space by removing the source dir
  **only after** validation passes. `convert_lancedb_to_sqlite()` in `index.py`.

### Changed

- **Default vector backend is now `"auto"`** (was implicitly lancedb):
  `resolve_backend_name()` picks sqlite-vec for fresh/converted corpora and
  lancedb only when an un-migrated lancedb store is all that exists — so new
  builds go to sqlite-vec while existing lancedb corpora keep working untouched.
  Force either with `--vector-backend` / `DOCKG_VECTOR_BACKEND`.
- **`index.py::SemanticIndex` refactored onto the backend seam.** `build`,
  `build_from_cache`, `_build_from_jsonl_cache`, `search`, `prune`, and
  `_existing_index_ids` now delegate storage to the backend; the LanceDB table
  plumbing and IVF ANN machinery moved into `kg_utils`'s `LanceDBBackend`
  (ANN applies to LanceDB only — sqlite-vec is always exact). Public API
  (`SemanticIndex(...)`, `build()`, `search()`, stats keys) unchanged; a new
  `backend=` parameter defaults to LanceDB.

### Removed

- Dead `index.py` internals folded into `kg_utils.vector_backend`:
  `_open_table`, `_get_table`, `_maybe_create_ann_index`,
  `_table_has_ann_index`, `_pq_subvectors`, `_escape`.

### Fixed

- **`index.py`: MPS cache evicted each batch in the streaming embed.**
  `_precompute_embeddings_jsonl_stream` embeds batch-by-batch and flushes to disk, but
  never freed the Metal/MPS allocator cache; on Apple Silicon the allocator hoards freed
  blocks, so a long consolidated embed (700k+ nodes) grows unbounded and dies with
  "MPS backend out of memory" even though the working set stays ~1 GB.
  `torch.mps.empty_cache` is now invoked after each batch flush (guarded on torch + MPS
  availability), keeping GPU memory flat across arbitrarily large corpora. CPU/CUDA paths
  unaffected. Re-applies the orphaned `fix/mps-cache-streaming-embed` branch (June 14)
  onto the post-0.17.0 code, where the GPU precompute path deliberately routes through
  this stream.

## [0.17.0] - 2026-07-13

### Added

- **Traced provenance in `pack` (`traced=True`).** `DocKG.pack(..., traced=True)` now
  attaches a `seed → … → node` provenance path to every returned node, with a quoted
  source line (and a `file_path:char_start` citation) at each hop — turning a text pack
  from "here are similar chunks" into a traceable chain of *why* each result surfaced.
  Paths are reconstructed by a multi-source BFS over the edge set `pack` already fetches,
  so tracing adds no extra queries, no schema change, and **no rebuild** — it works on the
  existing `.dockg` graph. New helpers in `kg.py`: `_trace_paths()`, `_hop_label()`
  (`"similar to (0.91)"`, `"links to (other.md)"`, `"contains"`, `"mentions"`, …),
  `_node_quote()`, and `_render_path()`. `TextPack` gains an optional `paths` field that
  serializes and renders **only when populated**, so untraced output is byte-identical.
  Exposed through the MCP `pack_docs(traced=...)` tool and the `dockg pack --traced` CLI
  flag. Inspired by zvizdo/ufo-knowledge-base's traversal-grounded, path-cited answers
  (see `analysis/ufo_kb_comparison_20260702.md`).

### Changed

- **`embedder_worker.py`: `CorpusEmbedder`/`EmbeddingCache` moved to `kg_utils.corpus_embedder`.**
  This file carried the canonical implementation of the multi-process, device-safe corpus
  embedder — but it had been independently forked into memory_kg and diary_kg, and the
  device-pinning/GPU-guard/shard-recycling fixes from 0.15.9 (the 683k-node consolidated-build
  incident; see `gutenberg_kg/SUMMARY.md`) never propagated to those copies. The implementation
  now lives in `kgmodule-utils>=0.4.7` (`kg_utils.corpus_embedder`); `doc_kg.embedder_worker`
  re-exports `CorpusEmbedder`/`EmbeddingCache`/`PIPELINE_MODEL` for backward compatibility, so
  no caller-facing change. `kg_utils.embedder.resolve_device()` is the new public device
  resolver `_resolve_device()` delegated to. `tests/test_embedder_worker.py` now only tests
  doc_kg's own surface (`PIPELINE_MODEL`, re-export identity); the low-level `_embed_shard`/
  `EmbeddingCache`/save-load unit coverage moved to `kg_utils`'s own test suite.

- **`index.py`: `SemanticIndex.build()` encode batch hard-capped at 128.** Default
  `encode_batch_size` lowered 1024 → 128, and the per-call encode sub-batch is now
  `min(current_encode_batch, 128)` **unconditionally** (previously only capped after
  240k rows, so the first ~quarter-million rows encoded at 1024). Transformer attention
  memory scales with `batch × seq²`, so a 1024 batch on long chunks allocates ~7–9 GB
  per `model.encode` call and OOMs / stalls MPS; throughput is flat above ~128 on CPU
  and MPS, so the cap costs nothing. `dockg build-index --encode-batch` default likewise
  1024 → 128. (The `dockg build` cache path via `CorpusEmbedder` was already at batch 64;
  unaffected.)

- **`index.py`: no more mid-run embedder reloads in `SemanticIndex.build()`.** Both the
  adaptive "refresh embedder on latency spike" and the periodic every-120k-rows reload
  are gone — a mid-run `make_embedder()` discards a caller-supplied shared embedder
  (e.g. DiaryKG reusing its transformer's model) and on MPS risks a second-load SIGBUS.
  The encode sub-batch is likewise fixed for the whole run
  (`min(max(64, encode_batch_size), 128)`) instead of dynamically halving/doubling on
  latency; long-run backend drift is handled solely by releasing allocator caches at
  telemetry checkpoints, which stays.

- **`index.py`: CPU embedding-cache precompute is now multi-process *and* streaming.**
  `precompute_embeddings` with a JSONL cache target now routes by device
  (`kg_utils.embedder.resolve_device`): MPS/CUDA keeps the single-process JSONL stream
  (a GPU can't fan out across spawn workers, and reusing the live embedder avoids a
  second model load), while CPU goes through the new
  `_precompute_embeddings_parallel_stream()` — `CorpusEmbedder.embed_to_cache()` from
  `kgmodule-utils>=0.4.9` (floor bumped 0.4.8 → 0.4.9) streams vectors shard-by-shard
  to the JSONL cache, so peak memory scales with shard size, not corpus size (the
  689k-node OOM fix, now on the precompute path too). Node reading is factored into
  `_read_texts_metadata()`, shared with the in-memory cache path and keeping
  `only_missing` incremental support.

## [0.16.0] - 2026-06-24

### Added

- **Row-count-gated approximate-nearest-neighbour (ANN) index.** `SemanticIndex` now
  builds a LanceDB IVF index automatically at the end of every build path once a table
  crosses `ann_threshold` (default 50k rows), and `search()` consumes it transparently;
  below the threshold the exact flat cosine scan is unchanged (sub-ms, exact). On the
  683k-vector gutenberg-all corpus this cuts query latency ~64 ms → ~12 ms end-to-end.
  Defaults: `IVF_FLAT` (full vectors, exact within probed cells; `IVF_PQ` available for
  disk-constrained / multi-million-scale corpora), `nprobes=50`, `refine_factor=0` — all
  overridable via `DOCKG_ANN_*` env vars. New helpers `_maybe_create_ann_index()`,
  `_table_has_ann_index()`, `_pq_subvectors()`. Index-build failures fall back to flat
  scan, so the index is never load-bearing. Additive: consumer repos (gutenberg_kg,
  diary_kg) inherit it through `DocKG.build_index_from_cache` with no changes, and small
  corpora are untouched.
- **`benchmarks/ann_recall_bench.py`** — validates the ANN index by *fidelity to the exact
  flat scan* on real query texts (the correct measure for an index change: embeddings and
  ranking are held fixed; only *which* vectors get scored changes). On the 683k corpus,
  IVF_FLAT reproduces 0.91 of the exact top-10 with 94% top-1 retention at `nprobes=50`.
- **`docs/design-ann-index.md`** — design rationale, parameter table, and benchmark results
  for the ANN index.
- **Incremental embedding.** `precompute_embeddings(only_missing=True)` (and
  `DocKG.build_embeddings(only_missing=...)`) skips nodes whose id is already in the
  LanceDB table, so only new/changed nodes are embedded. Pair with
  `build_index_from_cache(wipe=False)` to upsert. Backed by `_existing_index_ids()`,
  which projects just the `id` column (cheap on large tables).
- **`DocKG.prune_index()` / `SemanticIndex.prune(keep_ids)`** — delete index vectors whose
  node id is no longer in the graph (orphans from removed/renamed nodes), so incremental
  updates don't leave stale hits behind.

### Changed

- `pyproject.toml`, `src/doc_kg/__init__.py`, `README.md`: version bumped to 0.16.0.

## [0.15.9] - 2026-06-17

### Added

- **Device control for embedding.** `CorpusEmbedder(device=...)` plus a `_resolve_device()`
  helper (precedence: explicit arg > `KG_EMBED_DEVICE` env > auto-detect). Threaded through
  `DocKG.build_embeddings(device=...)` and `index.precompute_embeddings(device=...)`.

### Changed

- **Parallel embedding now recycles workers.** `_embed_parallel` splits work into many small
  shards (`_RECYCLE_SHARD`, default 25k texts) and runs `Pool(maxtasksperchild=1)`, so a fresh
  process handles each shard. Long-lived embedding workers accumulate allocator/heap/GC state
  that decays throughput on large corpora; recycling resets each worker and keeps throughput
  flat at any scale. (Previously one giant shard per worker, which degraded past ~300k items.)

### Removed

### Fixed

- **GPU embedding no longer fans out into an OOM.** When the device is `mps`/`cuda`,
  `CorpusEmbedder.embed` forces single-process embedding — a GPU can't be shared across spawn
  workers, so N workers stacked N allocations and OOM'd. Only CPU parallelises now.

## [0.15.8] - 2026-06-10

### Added
- `docs/query_path_visual.md`: Visual description of the hybrid query path for image generation — illustration brief covering the dense (LanceDB) and lexical (FTS5/BM25) seed channels, scope pushdown gates, RRF fusion with dual-distance lexical seeds, graph expansion, ranking, guards, and outputs, plus a structured per-stage reference, benchmark validation table, and ASCII overview. Follows the `docs/pipeline_visual.md` format.
- `benchmarks/recall_bench.py`: Standard retrieval-recall benchmark for seeding changes, adapted from `gutenberg_kg/scripts/evaluate_similar_to_value.py`. A/Bs query-time seeding conditions (`dense`, `hybrid`, or explicit base-dist floats) over the same prebuilt per-book indices, with two complementary query sets: **gold mode** (human-labeled gutenberg_kg gold CSV — dense-biased, measures the lexical channel's cost) and **phrase mode** (auto-generated exact-phrase queries sampled from chunk text, unique-in-book, FTS5-tokenizer-aligned — measures the lexical channel's benefit with no human labeling). Corpus artifacts are never modified: each `graph.sqlite` is copied to a temp dir for the FTS rebuild and LanceDB is opened read-only, keeping node IDs stable against gold labels. Emits per-query JSON under `benchmarks/data/`.

### Changed
- `pyproject.toml`, `src/doc_kg/__init__.py`, `README.md`, `CITATION.cff`: Version bumped to 0.15.8.

### Removed

### Fixed
- `src/doc_kg/kg.py`: `_lance_where()` now matches `file_path` prefixes with `starts_with()` instead of `LIKE` — `%`/`_` in a prefix were treated as SQL wildcards by the LanceDB (DataFusion) prefilter, so e.g. prefix `doc_kg/` also matched `docXkg/`. The SQLite-side `_node_filter_sql()` already escaped these via `LIKE ... ESCAPE`; the two pushdown channels and the `_node_in_scope()` guard now share identical literal-prefix semantics. Verified against LanceDB 0.30.2.
- `src/doc_kg/kg.py`: Lexical-only seed ranking rebuilt after `benchmarks/recall_bench.py` measured both failure modes of the single synthetic distance shipped in v0.15.7. (1) `_LEXICAL_SEED_BASE_DIST` raised 0.12 → 0.45: at 0.12 a lexical seed's expansion neighbourhood outranked virtually every dense hit, costing −14.2 pp recall@15 / −21.3 pp MRR@15 on the gutenberg_kg gold set (7/34 queries wiped to zero); a sweep (0.25–0.60) plateaus at ≥0.40. (2) But at 0.45 the exact-phrase hit *itself* was evicted by dense-seeded expansion noise (hybrid lost to dense-only on verbatim-phrase retrieval, 0.317 vs 0.367 recall@15). Fix: `_fused_seeds()` now assigns lexical-only seeds two distances — `self_dist` (just behind the best dense hit; ranks the matching chunk itself) and `dist` (conservative 0.45; inherited by expanded neighbours via provenance) — applied through the new `_seed_base_dist()` helper in both `query()` and `pack()`. A lexical match is strong evidence for the matching chunk, weak evidence for its neighbourhood. Result: phrase-mode recall@15 0.367 → **0.667** (+30 pp vs dense-only) with gold-set cost unchanged (−1 pp, a single RRF seed-membership displacement).
- `tests/test_query_scope.py`: `_lance_where` assertions updated to `starts_with()`; added literal-underscore regression test.

## [0.15.7] - 2026-06-09

### Added
- **Query-time scope pushdown** (`src/doc_kg/kg.py`, `src/doc_kg/store.py`, `src/doc_kg/index.py`): `DocKG.query()` and `DocKG.pack()` accept optional `source_path_prefixes` and `node_kinds` constraints that restrict retrieval to a subtree (e.g. a single genre of a consolidated corpus) and/or node kinds. The filter is pushed *into* both seed channels — LanceDB vector search via a prefilter `where` clause (`SemanticIndex.search(..., where=)`) and FTS5 lexical search via parameterised SQL (`GraphStore.search_lexical(..., file_prefixes=, node_kinds=)`) — so the seed budget is spent entirely on in-scope nodes rather than post-filtered, eliminating cross-subtree starvation. A final `_node_in_scope()` guard drops any node that graph expansion pulled out of scope via edges. New helpers: `_lance_where()`/`_node_in_scope()` (`kg.py`) and `_node_filter_sql()` (`store.py`, injection-safe with `LIKE ... ESCAPE`).
- `tests/test_query_scope.py`: covers the SQL/Lance filter builders, the scope guard, and FTS5 lexical pushdown (prefix-only, kind-only, and combined) restricting results to a genre subtree.
- `src/doc_kg/store.py`: Hybrid lexical retrieval via SQLite FTS5. `GraphStore.rebuild_fts()` builds a *contentless* FTS5 table `nodes_fts` (inverted index only, ≈1× chunk-text size) over all `kind='chunk'` rows; safe to call repeatedly (drops + rebuilds) and no-ops cleanly when SQLite lacks FTS5. `has_fts()` reports index presence. `search_lexical()` runs BM25 ranking, trying an exact-phrase query first and falling back to OR-of-terms for recall; returns chunk IDs best-first, or `[]` on older corpora so callers degrade to dense-only. Added `_fts_terms()` helper to tokenise queries into bare alphanumerics, stripping apostrophes/punctuation that FTS5 would otherwise treat as query syntax (e.g. `Lot's` → `lot`, `s`).
- `src/doc_kg/kg.py`: `DocKG._fused_seeds()` blends the dense (vector) and lexical (BM25) seed channels with reciprocal rank fusion (RRF, `_RRF_K=60`) so exact-phrase matches that dense embeddings bury can seed graph expansion without sacrificing dense recall. Lexical-only seeds receive a synthetic cosine distance (`_LEXICAL_SEED_BASE_DIST` + per-rank step) so distance-based ranking can place them. `query()` and `pack()` now seed via `_fused_seeds()`. `DocKG.build()` calls `store.rebuild_fts()` so new builds get the lexical index automatically.
- `src/doc_kg/cli/cmd_build.py`: `dockg reindex-fts` command backfills the FTS5 lexical index on an existing graph from chunk text already in SQLite — no re-embedding, no LanceDB changes. Lets corpora built before the lexical index existed gain hybrid retrieval.
- `tests/test_store.py`: `test_fts_lexical_search` and `test_fts_rebuild_is_idempotent` cover graceful empty results before indexing, chunk-count after `rebuild_fts()`, exact-phrase isolation, apostrophe/punctuation handling via OR-fallback, term-less query degradation, and idempotent rebuilds.

### Changed
- `pyproject.toml`, `src/doc_kg/__init__.py`: Version bumped to 0.15.7.

### Removed

### Fixed

## [0.15.5] - 2026-06-05

### Changed
- `.pre-commit-config.yaml`, `pyproject.toml`: Removed `pylint` entirely; linting is now handled exclusively by `ruff`, consistent with the `kgrag` project. Dropped `pylint>=4.0.5` from `dev` and `all` optional-dependency groups and deleted `[tool.pylint.messages_control]` configuration.

### Fixed
- `src/doc_kg/kg.py`: Restored `similar_max_degree: int = 0` parameter to `DocKG.build()`, `build_from_cache()`, and `build_index_from_cache()`. The parameter was introduced in v0.15.3 but removed in v0.15.4 because it was accepted without being forwarded to `SemanticIndex`. It is now threaded through correctly to `_discover_similar_edges()` via all three public build paths.
- `tests/test_front_matter.py`: `TestQuerySeedFiltering` tests were failing in CI with a HuggingFace connectivity error. The root cause was that `patch.object(kg.index, "search", ...)` triggered the lazy `index` property before the patch applied, initialising `SemanticIndex` and loading the sentence-transformer model. Fixed by injecting `kg._index = MagicMock()` directly so the lazy property is bypassed entirely. Tests now run in ~0.05 s with no network access.

## [0.15.4] - 2026-06-01

### Changed
- `pyproject.toml`, `.github/workflows/ci.yml`, `.pre-commit-config.yaml`: Migrated type checker from `mypy` to Astral `ty`. Replaced `mypy>=1.10.0` with `ty>=0.0.41` in `dev` and `all` optional-dependency groups; replaced `[tool.mypy]` configuration with `[tool.ty.environment]` / `[tool.ty.rules]`; CI step changed from `poetry run mypy src/` to `poetry run ty check src/`; pre-commit `mypy` hook replaced by `ty`; `ruff-pre-commit` pinned to `v0.15.13` and hook renamed `ruff` → `ruff-check`.
- `src/doc_kg/app.py`, `src/doc_kg/dockg.py`, `src/doc_kg/index.py`, `src/doc_kg/kg.py`, `src/doc_kg/store.py`, `src/doc_kg/topics.py`: All `# type: ignore[...]` suppression comments that target ty-specific diagnostics converted to `# ty: ignore[...]` format.
- `src/doc_kg/graph.py`: `nodes` and `edges` properties now narrow `None` via `assert self._nodes/edges is not None` instead of `# type: ignore[return-value]`, making the invariant explicit.
- `analysis/doc_kg_analysis_20260523.md`: Refreshed analysis snapshot (2 975 nodes, 22 140 edges, 93.4% entity coverage).

### Removed
- `src/doc_kg/kg.py`: Removed unused `similar_max_degree` parameter from `DocKG.build()`, `build_from_cache()`, and `build_index_from_cache()`. The parameter was accepted but never forwarded to `SemanticIndex`; use `similar_k` for per-node edge caps.
- `.claude/agents/`: Removed 13 stale agent definition files (`cco`, `cw`, `do`, `doc`, `kc`, `me`, `qa`, `sd`, `sec`, `ta`, `uid`, `uids`, `uxd`).

## [0.15.3] - 2026-05-20

### Added
- `src/doc_kg/dockg.py`: `_classify_section_content_type()` — classifies a document section as `'front_matter'`, `'reference'`, or `None`. Rules applied in order: (1) `reference.md` files → `'reference'`; (2) H1 headings → `None` (book title); (3) headings matching main-content keywords (`chapter`, `book`, `part`, `volume`, etc.) → `None`; (4) sections starting after 40% of the file → `None` (late contextual intros); (5) headings matching `_FM_HEADING` regex → `'front_matter'`. `_FM_HEADING` regex covers prefaces, introductions, forewords, translator/editor/transcriber notes, biographical sketches, tables of contents, select bibliographies, and copyright sections. `_FM_MAIN_CONTENT` regex anchors on chapter/book/part/volume headings to ensure they always win over FM heuristics.
- `tests/test_front_matter.py`: 19 new tests across three classes — `TestClassifySectionContentType` (8 unit tests covering all decision branches: H1 bypass, `reference.md` override, main-content keyword wins, FM headings in early vs. late position, boundary conditions, normal prose, `None` preamble, zero-length file guard), `TestParseCorpusFrontMatterTagging` (7 integration tests: `reference.md` chunks tagged, preface/chapter distribution, introduction tagging, `Book I. Introduction.` not tagged, late contextual intro not tagged, prose-only file clean, mixed corpus), `TestQuerySeedFiltering` (4 integration tests with mocked LanceDB index and real SQLite store verifying `reference.md` and `front_matter` nodes are excluded from seeds and returned results while prose chunks pass through).
- `src/doc_kg/index.py`: `_discover_similar_edges()` gains `max_degree` parameter — when > 0, uses a per-node min-heap to collect top-k candidate edges during the ANN scan, then enforces a hard per-node cap with a greedy high-similarity selection pass before writing to SQLite. Prevents hub nodes from accumulating unbounded SIMILAR_TO degree in dense corpora. `build()`, `build_from_cache()`, and `_build_index_from_cache_chunks()` all gain a `similar_max_degree: int = 0` parameter (default 0 = unlimited, preserving existing behaviour).
- `src/doc_kg/kg.py`: `DocKG.build()`, `build_from_cache()`, and `build_index_from_cache()` gain `similar_max_degree: int = 0` parameter, threaded through to `SemanticIndex`.
- `tests/test_similar_edges.py`: 12 new tests for `_discover_similar_edges()` covering empty input, self-hit skipping, threshold filtering, canonical edge direction, similarity evidence, and all `max_degree` pruning cases (unlimited, cap=1, cap=2, dense graph, prefers highest similarity, threshold+cap interaction).

### Changed
- `src/doc_kg/dockg.py`: `parse_corpus()` now calls `_classify_section_content_type()` for every chunk whose `content_type` is `None` after chunking. Captures `total_chars = len(raw_text)` per file for position-cutoff calculation. Front-matter and reference sections are tagged during corpus ingestion so the content type is persisted in SQLite.
- `src/doc_kg/kg.py`: `DocKG.query()` now filters front-matter and reference content from both seed selection and returned results. Seeds are oversampled 3× to compensate for filtering; `reference.md` hits are dropped by file path immediately; remaining candidates are checked against the SQLite store for `content_type == 'front_matter'` and dropped. In the ranked result walk, nodes with `content_type` in `{'front_matter', 'reference'}` are skipped in the returned list but remain in the graph for traversal (they can still contribute neighbour edges).
- `src/doc_kg/index.py`: `_discover_similar_edges()` rewritten from per-chunk LanceDB ANN queries to a **blocked NumPy matmul** (BLAS SGEMM). Because sentence-transformers emits L2-normalised vectors (`normalize_embeddings=True`), cosine similarity equals the dot product, so `X[block] @ X.T` gives exact pairwise similarities with a single BLAS call per block — no per-chunk Python↔LanceDB round-trip. Block size is adaptively clamped so the `(B × N)` similarity matrix stays under ~256 MB regardless of corpus size. Top-k filtering now uses `np.argpartition` (O(N)) instead of a full sort. The `tbl` parameter is retained for call-site compatibility but is no longer used. Added `block_size: int = 512` parameter.
- `tests/test_similar_edges.py`: All tests rewritten to use real L2-normalised NumPy vectors instead of mocked LanceDB ANN results. `_make_tbl()` helper removed; `_run_discovery()` now takes `chunk_vecs` directly. Star scenario uses geometrically correct vectors (hub-spoke sim=0.6, spoke-spoke sim=0.36 < threshold). `test_max_degree_prefers_higher_similarity` uses exact dot-product construction for 0.99 and 0.85 similarities.
- `analysis/architecture.md`: Moved from project root into `analysis/` directory (renamed from `architecture.md`).
- `.vscode/settings.json`: Added `python.defaultInterpreterPath` and `python.testing.pytestPath` pointing to `.venv/bin/` so the VS Code Test Explorer uses the project virtual environment. Installed `pytest` and `pytest-cov` into `.venv` (were missing despite being declared in `[project.optional-dependencies] dev`).
- `.dockg/snapshots/manifest.json`: Snapshot updated for v0.15.3.

### Fixed
- `src/doc_kg/index.py`: `build_from_cache()` was not forwarding `similar_max_degree` to `_build_from_jsonl_cache()` — the JSONL cache path silently ignored the degree cap. Argument now threaded through correctly (mypy `call-arg` error).
- `src/doc_kg/dockg_thorough_analysis.py`: `DocKGAnalyzer._analyze_baseline()` was calling `self.kg.stats()` (KGRAG adapter contract — returns `node_count`/`edge_count`) instead of `self.store.stats()` (returns `total_nodes`/`total_edges`/`node_counts`). The analyzer was written against the store format; the two diverged when `DocKG.stats()` was introduced in v0.11.0. `dockg analyze` was silently reporting 0 nodes and 0 edges despite a fully built graph.

### Removed
- `generate_wiki.py`: Deleted — superseded by dedicated documentation tooling.
- `CHANGES_exclude_dir.md`: Deleted — temporary scratch file.
- `release-notes.md`: Deleted — content lives in `CHANGELOG.md`.

## [0.15.0] - 2026-05-16

### Added
- `src/doc_kg/cli/cmd_build.py`: Three new commands: `build-embeddings` (SQLite → embedding cache JSON/JSONL, gzip-capable), `build-index-from-cache` (cache → LanceDB without model inference), and `build-two-phase` (stable end-to-end pipeline using cache as intermediary). `build-index` gains `--device` (auto/cpu/mps/cuda) and `--index-kind` (repeatable, restricts embedded node kinds) options.
- `src/doc_kg/index.py`: `make_embedder()` factory function with `device` override; `build()` now streams nodes via `store.iter_nodes()` (avoids loading all node dicts into RAM) and pre-allocates a contiguous `(n_chunks × dim)` float32 ndarray for the SIMILAR_TO ANN pass; `_discover_similar_edges()` signature updated to accept separate `chunk_ids` + `chunk_vecs` arrays; `_is_jsonl_cache()` and `_open_text_auto()` helpers for cache I/O.
- `src/doc_kg/store.py`: `count_nodes()` — fast kind-filtered row count used for progress bars and pre-allocation; `iter_nodes()` — batch generator that streams node dicts without holding the full result set in RAM; `query_nodes()` gains `limit` and `offset` parameters for pagination.
- `src/doc_kg/chunker.py`: `VerseChunker` — new chunker for `chapter:verse`-structured sacred texts (KJV Bible, Quran, etc.). Auto-detects verse documents via `is_verse_document()` (>10% of non-blank lines match `^\d+:\d+\s`), skips TOC preambles, splits by book sections, enforces chapter boundaries, and emits chunk dicts with `content_type`, `book`, `chapter`, `verse_start`, `verse_end` metadata. Added `"verse"` strategy to `chunker_for()`.
- `src/doc_kg/discover_topics.py`: New `discover_topics()` function — corpus-driven topic discovery via K-means on chunk embeddings + within-cluster TF-IDF scoring. Writes a human-readable YAML catalog (`{cluster_NN: [kw, ...]}`) and a fitted `*.kmeans.joblib` model for embedding-based topic assignment during `build-graph`.
- `src/doc_kg/sacred_texts_topics.yaml`: Built-in 12-topic catalog for sacred-text corpora (Creation, Covenant, Law, Prophecy, Gospel, Epistle, Wisdom, Lament, Praise, Narrative, Apocalyptic, Ethics) with multi-word and single-word keywords.
- `src/doc_kg/dockg.py`: `parse_corpus()` gains `kmeans_model_path` and `topics_file_map` parameters. When `kmeans_model_path` is set, all chunks are batch-embedded per file and assigned to the nearest K-means centroid (near-100% topic coverage, overrides keyword matching). `topics_file_map` enables per-path topic catalog routing (first prefix match wins).
- `src/doc_kg/entry_chunk.py`: `SourceProvenance` gains five new optional fields: `content_type`, `book`, `chapter`, `verse_start`, `verse_end`; mirrored in `EntryChunk.to_node_dict()`.
- `src/doc_kg/store.py`: SQLite schema extended with five verse columns (`content_type TEXT`, `book TEXT`, `chapter INTEGER`, `verse_start INTEGER`, `verse_end INTEGER`). Includes `ALTER TABLE` migration for existing databases. All INSERT/SELECT/UPSERT statements updated to 14 columns.
- `src/doc_kg/cli/cmd_build.py`: `build` and `build-graph` gain `--chunk-strategy [semantic|sentence_group|fixed|verse]`, `--kmeans-model FILE`, and `--topics-prefix PREFIX=FILE` (repeatable) options. `_parse_topics_prefix()` helper parses the `PREFIX=FILE` pairs.
- `src/doc_kg/cli/cmd_pipeline.py`: New `dockg pipeline discover-topics` command — wraps `discover_topics()` with full Click decorator stack (`--n-clusters`, `--n-keywords`, `--chunk-strategy`, `--sentences`, `--model`, `--quiet`).
- `tests/test_verse_chunker.py`: 21 tests across 6 test classes covering `VerseChunker` detection, TOC skipping, chapter boundary enforcement, book section parsing, multi-book corpora, and `chunker_for("verse")` integration.
- `docs/verse_workflow.md`: New comprehensive verse ingestion workflow guide with five-phase pipeline walkthrough, actual KJV Bible benchmark numbers, k-selection guidance, verse chunk schema reference, per-path override patterns, and troubleshooting section. Includes infographic image-generation prompt.
- `docs/pipeline_visual.md`: New pipeline visual reference document.
- `assets/dockg_pipeline.png`: Pipeline architecture diagram asset.

### Changed
- `src/doc_kg/dockg.py`: `DocNode` dataclass gains five optional fields (`content_type`, `book`, `chapter`, `verse_start`, `verse_end`). `parse_corpus()` auto-detects verse documents and switches to `VerseChunker` when the file qualifies. Lazy chunker import expanded to include `TextChunker` and `SentenceGroupChunker` for correct mypy type annotations.
- `src/doc_kg/graph.py`: `DocGraph.__init__()` gains `kmeans_model_path` parameter; threaded through to `parse_corpus()` call in `extract()`.
- `src/doc_kg/kg.py`: `DocKG.__init__()` gains `kmeans_model_path` and `device` parameters; lazy `embedder` property now calls `make_embedder()` with device; `build_embeddings()` and `build_index_from_cache()` methods added.
- `src/doc_kg/cli/cmd_build.py`: `build-index` default LanceDB write batch size raised 256 → 8192 (fewer LanceDB fragments, faster scan on large tables).
- `src/doc_kg/embedder_worker.py`: Embedding cache supports gzip compression (`.json.gz`, `.jsonl.gz`); JSON serialized with compact separators (`ensure_ascii=False`) to reduce file size by ~20%.
- `src/doc_kg/pipeline.py`: `_phase2_chunk()` annotation updated to `TextChunker | SentenceGroupChunker | VerseChunker`; `VerseChunker` added to import.
- `src/doc_kg/topics.py`: `TopicExtractor.classify()` multi-word keyword fix — single-word keywords use set lookup on tokenized words; multi-word keywords use substring search on lowercased text (was broken: all multi-word phrases silently missed).
- `docs/CHEATSHEET.md`: New Section 9 — Verse Corpus Ingestion with condensed workflow, coverage comparison table, and link to `verse_workflow.md`. Section 10 (Multipass Pipeline) and Section 11 (Live Stats) renumbered. Node kinds table updated to include `.rst` and `.pdf` file types.
- `.dockg/snapshots/manifest.json`: Snapshot updated.
- `.claude/plans/verse-ingestion.md`: Implementation plan saved.

### Removed

### Fixed
- `src/doc_kg/discover_topics.py`: `import yaml` annotated with `# type: ignore[import-untyped]` (consistent with `topics.py`); `ck` variable given explicit union type annotation to satisfy mypy.
- `src/doc_kg/index.py`: Removed leftover `DEBUG` `print` statement from `index_nodes()` that was leaking to stderr during every build.

### Performance
- `src/doc_kg/index.py`: `_discover_similar_edges()` rewritten to use LanceDB HNSW ANN queries instead of batched numpy matmul. The old approach allocated an `(n_chunks × dim)` matrix for all nodes plus a `(row_batch × n_chunks)` temporary similarity matrix per batch — for 400 K chunks the temp alone reached ~1.6 GB, causing OOM on large sacred-text corpora. The new approach queries LanceDB for each chunk's top-k nearest neighbours via the existing HNSW index; peak RAM is O(n_chunks × dim) with no N×N allocation. `build()` and `index_nodes()` no longer pre-allocate `all_vecs_np`; instead they accumulate `chunk_pairs: list[tuple[str, vec]]` for chunk nodes only (smaller than the full node set). SQLite PRIMARY KEY on `(src, rel, dst)` continues to deduplicate edges emitted by both A→B and B→A ANN results.

## [0.14.0] - 2026-05-04

### Added
- `src/doc_kg/cli/cmd_build.py`: `dockg build` gains `--similar-k` (default `5`) and `--similar-threshold` (default `0.85`) options to bound SIMILAR_TO graph density. `--similar-k 0` disables the cap and restores the legacy "every pair above threshold" behavior.
- `src/doc_kg/kg.py`: `DocKG.build()`, `build_index()`, and `build_from_cache()` now accept `similar_k` and `similarity_edge_threshold` keyword arguments, threading the new caps through to `SemanticIndex`.

### Changed
- `src/doc_kg/index.py`: SIMILAR_TO edge discovery enforces a per-row top-`k` cap before threshold filtering (argpartition over each chunk's similarity row), preventing quadratic edge blow-up on stylistically homogeneous corpora where most pairs sit just above the threshold. Self-similarity is masked to `-inf` so it cannot occupy a top-k slot. Edges are now emitted in canonical undirected form (`src=min(a,b)`, `dst=max(a,b)`), so the SQLite `(src, rel, dst)` PRIMARY KEY deduplicates cross-batch pairs and the asymmetric top-k case where `A` picks `B` but `B` does not pick `A`.
- `.dockg/snapshots/manifest.json`: Refreshed snapshot for `main` at v0.14.0.

## [0.13.0] - 2026-05-03

### Added
- `tests/test_pack_dedup.py`: New test module (8 tests) covering `DocKG.pack()` deduplication, `_short_chunk_boost` micro-fragment guard, `TextChunker` and `chunker_for()` `min_chunk_chars` defaults, and `CrossSnippetPack.render()` micro-fragment filtering.

### Changed
- `src/doc_kg/chunker.py`: `TextChunker.__init__` and `chunker_for()` — `min_chunk_chars` default raised from 1 → 50; the old default of 1 allowed micro-fragments (e.g. `"see"`, `"cf."`) to be stored and indexed, polluting pack results.
- `src/doc_kg/kg.py`: Added `_MIN_CHUNK_CHARS = 50` module constant; `_short_chunk_boost()` now returns `0.0` for chunks shorter than `_MIN_CHUNK_CHARS` so micro-fragments cannot float to the top of `pack()` results via the short-chunk boost; `pack()` deduplication pre-pass now builds `seen_files_with_chunks` before the ranking loop so document/section nodes are always suppressed when their file's chunks are present (fixes edge case where chunks and coarse nodes shared the same rank).
- `pyproject.toml`: `kgdeps` and `all` extras now include `kg-rag @ git+https://github.com/Flux-Frontiers/KGRAG.git`; removed stale `[[tool.poetry.source]]` TestPyPI block; version bumped to 0.13.0.
- `.github/workflows/publish.yml`: Added `poetry publish` step so tag pushes automatically publish to PyPI via `PYPI_TOKEN` secret.
- `tests/test_chunker.py`, `tests/test_dockg.py`: Test fixture strings lengthened to meet the new 50-char `min_chunk_chars` floor so fixture chunks are not silently dropped during corpus parsing.

### Fixed
- `src/doc_kg/snapshots.py`: Docstring references corrected from `kg_snapshot.snapshots` → `kg_utils.snapshots` (the canonical package since v0.12.2).

## [0.12.3] - 2026-04-28

### Added
- `tests/test_cli.py`: Tests for the `download-model` command — verifies help text, already-cached path short-circuit, `--force` redownload, and save-to-path behaviour.

### Changed
- `src/doc_kg/index.py`: Removed duplicate `Embedder` and `SentenceTransformerEmbedder` definitions; both are now imported from `kg_utils.embedder` (shared KGModule embedding infrastructure). Removed `_local_model_path` helper — delegates to `kg_utils.embed.resolve_model_path`.
- `src/doc_kg/embedder_worker.py`: `PIPELINE_MODEL` switched from `nomic-ai/nomic-embed-text-v1` to `BAAI/bge-small-en-v1.5`, aligning with DocKG and PyCodeKG defaults. Replaced manual local/remote model loading logic with `load_sentence_transformer()` from `kg_utils.embedder`.
- `src/doc_kg/cli/cmd_model.py`: `download-model` command now resolves model cache path via `kg_utils.embed.resolve_model_path` instead of the removed local `_local_model_path`.
- `pyproject.toml`, `poetry.lock`: Version bumped to 0.12.3; major dependency updates — `transformers` 4.57.6→5.6.2, `huggingface-hub` 0.36.2→1.12.0, `safetensors` 0.5.3→0.7.0, `pycode-kg` 0.16.0→0.17.2, `kgmodule-utils` 0.2.0→0.2.2; removed `kg-snapshot` (absorbed into `kgmodule-utils`); added `typer`, `rich`, `shellingham` as transitive deps.
- `.dockg/snapshots/manifest.json`: New DocKG snapshot for `feat/viz3d` branch (v0.12.2, 2521 nodes / 18884 edges, coverage 0.908); v0.12.3 snapshot added (2576 nodes / 19466 edges, coverage 0.911).
- `tests/test_embedder_worker.py`: Replaced `_local_model_path` tests with a `resolve_model_path` availability check against `kg_utils.embed`; updated `_embed_shard` tests to patch `kg_utils.embedder.resolve_model_path`.
- `.claude/commands/pycodekg-rebuild.md`: Rewrote to use single `pycodekg build --repo` command (replaces stale two-step `pycodekg-build-sqlite`/`pycodekg-build-lancedb --wipe`); corrected artifact path from `.codekg/` to `.pycodekg/`.
- `.claude/commands/release.md`: Fixed `src/code_kg/__init__.py` → `src/doc_kg/__init__.py`; replaced stale `codekg-build-sqlite/lancedb --wipe` with `.venv/bin/pycodekg build`; corrected `.codekg/` → `.pycodekg/snapshots/`; removed `--wipe` from `dockg build`.
- `.claude/commands/setup-mcp.md`: Replaced stale `poetry run codekg-build-sqlite/lancedb --wipe` with `.venv/bin/pycodekg build`.
- `.claude/skills/dockg/SKILL.md`: Corrected build CLI semantics — default is full wipe-and-rebuild; `--update` is incremental. Removed all `--wipe` references (flag does not exist). Updated core build embedding model to `BAAI/bge-small-en-v1.5` (384-d).
- `.claude/skills/pycodekg/SKILL.md`, `clinerules.md`, `references/CHEATSHEET.md`: Removed stale `pycodekg build-lancedb --wipe` and `pycodekg build --repo . --wipe`; replaced with `pycodekg build --repo .`.

### Removed
- `src/doc_kg/index.py`: Removed `_local_model_path()`, `Embedder`, and `SentenceTransformerEmbedder` — now provided by `kg_utils`.
- `src/doc_kg/embedder_worker.py`: Removed `_local_model_path()` — replaced by `kg_utils.embed.resolve_model_path` via `load_sentence_transformer`.

### Fixed
- `src/doc_kg/embedder_worker.py`: Removed spurious `os.environ["TQDM_DISABLE"] = "1"` from `_embed_shard` — `transformers` ≥5.x ignores that env var and requires `hf_logging.disable_progress_bar()`, which `load_sentence_transformer()` in `kg_utils.embedder` now calls internally. The "Loading weights" tqdm bar during `dockg build` is suppressed correctly.

## [0.12.2] - 2026-04-27

### Changed
- `snapshots.py`: Migrated snapshot base imports from `kg-snapshot` to
  `kgmodule-utils` (`kg_utils.snapshots`); removed `kg-snapshot` from
  `pyproject.toml` dependencies.
- `snapshots.py`: `SnapshotManager.capture()` signature aligned with
  `kg_utils.snapshots.SnapshotManager` — legacy `coverage_score`,
  `issues_count`, `complexity_median` kwargs now accepted via `**extra_metrics`
  (fixes mypy `[override]` error).

## [0.12.1] - 2026-04-26

### Added
- `src/doc_kg/pdf_reader.py`: New module — `extract_pdf_markdown(path)` converts a PDF to Markdown via `pymupdf4llm`, inferring heading structure from font size/weight so PDFs flow into the existing `_chunk_markdown()` path and produce proper section nodes.
- `tests/test_pdf_reader.py`: 9 tests covering `extract_pdf_markdown` (returns string, extracts headings, raises `RuntimeError` on corrupt input), `TEXT_EXTENSIONS` inclusion, `iter_text_files` PDF discovery, chunker markdown dispatch, and `parse_corpus` end-to-end (document node, chunk nodes, section nodes from PDF headings).
- `tests/test_embedder_worker.py`: Added tests for `_local_model_path` (path type, `.dockg/models/` fallback, `KGRAG_MODEL_DIR` override) and `_embed_shard` model-resolution (local cache hit, cache miss, `OSError` network fallback, output shape).

### Changed
- `dockg.py`: `.pdf` added to `TEXT_EXTENSIONS`; `parse_corpus` branches on `.pdf` suffix to call `extract_pdf_markdown` before chunking, with `RuntimeError` caught and the file skipped gracefully; `_resolve_reference` exception narrowed from broad `Exception` to `(OSError, ValueError)`.
- `chunker.py`: `TextChunker.chunk()` and `SentenceGroupChunker.chunk()` now route `.pdf` through `_chunk_markdown` (since `pymupdf4llm` output is ATX-heading Markdown).
- `pyproject.toml`: `pymupdf4llm>=0.0.17` added as a core runtime dependency (not optional).
- `dockg.py`, `index.py`: `DEFAULT_MODEL` and model-path resolution extracted to `kg_utils.embed` — `DEFAULT_MODEL` is now re-exported from `kg_utils.embed.DEFAULT_MODEL`; `_local_model_path` delegates to `kg_utils.embed.resolve_model_path`, which checks `KGRAG_MODEL_DIR` first then falls back to `.dockg/models/`.
- `pyproject.toml`, `poetry.lock`: Added `kgmodule-utils` as a project dependency to centralise embedding constants and model-path resolution shared across KGModule packages.
- `README.md`: Replaced Contributing section with a Citation section containing the official Zenodo DOI (`10.5281/zenodo.19770973`) in APA and BibTeX formats; header DOI badge updated from GitHub repo-ID URL to direct Zenodo DOI link.
- `.dockg/snapshots/manifest.json`: Added six new DocKG snapshots captured during v0.11.0 and v0.12.0 development.
- `.pre-commit-config.yaml`: ruff hooks moved before local hooks (pylint/mypy/pytest) so auto-fixes run first; `pass_filenames: false` + `always_run: true` added to both `ruff` and `ruff-format` so they check the entire tree on every commit, not just staged files; `.codekg/` references updated to `.pycodekg/`; `article/` removed from large-file exclude (directory does not exist); redundant `.dockg/.*` detect-secrets exclude removed.
- `benchmarks/convomem_bench.py`, `benchmarks/locomo_bench.py`, `benchmarks/longmemeval_bench.py`, `benchmarks/membench_bench.py`: import blocks sorted; removed unused `socket` import; replaced `_socket.timeout` with built-in `TimeoutError`.
- `tests/test_chunker_sentence_group.py`: removed unused `intro_chunks`, `bg_chunks`, `impl_chunks` assignments.
- `tests/test_pipeline.py`: renamed ambiguous loop variable `l` → `line`.
- `tests/test_entry_chunk.py`, `tests/test_topics_hybrid.py`: removed unused imports and blank-line style fixes.

### Fixed
- `embedder_worker.py`: `_embed_shard` (multiprocessing worker) now checks the local model cache via `_local_model_path` before falling back to `local_files_only=True` and then network download — previously workers always fetched from HuggingFace, bypassing any cached model.
- `.github/workflows/ci.yml`: Removed duplicate `--extras dev` flag from `poetry install` command in the lint job.

## [0.12.0] - 2026-04-25

### Added
- `kg.py`: `DocKG.__init__` now accepts an optional `embedder: Embedder | None` parameter — allows callers to inject a pre-built embedding backend, bypassing lazy `SentenceTransformerEmbedder` initialization. Defaults to `None` (existing behaviour preserved).

## [0.11.0] - 2026-04-24

### Added
- `analysis/memory_kg_semantic_20260422.md`: MemoryKG semantic corpus analysis report (language profile, top entities, dominant themes, document signatures).
- `store.py`: `GraphStore.stamp_meta(builder_name, builder_version)` — writes the `_kgrag_meta` table into a built SQLite DB with `builder_name`, `builder_version`, and `built_at` (ISO-8601 UTC). Implements the KGRAG builder-version stamp contract so `kgrag info` can surface builder provenance. Uses `INSERT OR REPLACE` so repeated calls update `built_at` without creating duplicates.
- `kg.py`: `DocKG.build_graph()` now calls `store.stamp_meta()` immediately after writing nodes and edges, stamping `builder_name="doc_kg"` and `builder_version` from `importlib.metadata` into the database on every build.
- `kg.py`: `DocKG.stats()` upgraded from a thin `store.stats()` delegate to a flat dict conforming to the KGRAG adapter stats contract — returns `node_count`, `edge_count`, `document_count`, `chunk_count`, `section_count`, `topic_count`, `entity_count`, `keyword_count`. Wraps all queries in `try/except` so it never raises; returns zeros plus an `"error"` key on failure.
- `cli/cmd_status.py`: New `dockg status` command — reads `_kgrag_meta` and `GraphStore.stats()` and renders builder metadata (name, version, built-at, DB size in MB) plus side-by-side Rich tables of node kinds and edge relations. Exits non-zero if the database file is absent.
- `cli/main.py`: Registered `cmd_status` in the CLI group.
- `tests/test_store.py`: Tests for `stamp_meta` — verifies all three required keys land correctly and that a second call updates rather than duplicating.
- `tests/test_kg_stats.py`: Tests for `DocKG.stats()` — required keys, correct per-kind counts, no-raise on empty DB, and end-to-end verification that `build_graph()` stamps `_kgrag_meta`.
- `tests/test_cli.py`: Tests for `dockg status` — `status` appears in `--help`, output contains builder info and node kinds, exits non-zero on missing DB.

### Changed
- `dockg.py`, `index.py`: Default embedding model switched from `all-mpnet-base-v2` to `BAAI/bge-small-en-v1.5` — benchmarked winner across literary and technical retrieval; 384-dim, faster inference, same model used by PyCodeKG. Override via `DOCKG_MODEL` env var.
- `index.py`: `SemanticIndex.search()` now chains `.metric("cosine")` on the LanceDB query builder — ensures cosine distances are returned so the `1 - dist` similarity formula in `kg.py` maps correctly to [0, 1]. (`create_table()` does not accept a `metric` argument in LanceDB 0.30.x; the previous attempt to pass it there raised `TypeError`.)
- `index.py`: Removed debug `print` (tick/tock) statements from the SIMILAR_TO batch similarity loop.
- `kg.py`: Removed `min(base_dist, 1.0)` clamp from `seed_sim` in `DocKG.query()` and `DocKG.pack()` — cosine distances from `BAAI/bge-small-en-v1.5` are already in [0, 1]; the clamp was masking true score fidelity for distant hits.
- `pyproject.toml`: Development status classifier promoted from `3 - Alpha` to `4 - Beta`; author email updated to `suchanek@flux-frontiers.com`; `ftree-kg` and `memory-kg` removed from optional `kg` extras (now only `pycode-kg` and `agent-kg`); added install command hints as comments.
- `poetry.lock`: Removed `ftree-kg`, `kg-utils`, and `memory-kg` from the resolved dependency graph.

### Removed
- `.gitignore`: Removed `.dockg/cache/` and `.dockg/pipeline/` exclusions (no longer needed).

### Fixed

## [0.9.1] - 2026-04-22

### Added
- `kg.py`: `DocKG.query()` and `DocKG.pack()` now inject a `relevance` dict into every returned node — `{"score": float, "dist": float, "hop": int, "semantic_boost": float}` — where `score` is cosine similarity in [0, 1] (higher = more relevant). Previously nodes had no score field, causing all DocKG hits to register as `0.0` in federated KGRAG queries and sink below code hits regardless of semantic quality.

### Changed
- `kg.py`: `QueryResult` docstring updated to document the new `relevance` field on each node dict.
- `.claude/settings.json`: Additional `codekg-build-sqlite`, `pycodekg-build-sqlite`, `pycodekg-build-lancedb`, and `pycodekg-analyze` commands added to the allow list.

## [0.9.0] - 2026-04-20

### Added
- `store.py`: `GraphStore.nodes_batch()` — batch-fetch multiple nodes in a single SQL query via temp table JOIN; eliminates N individual lookups during graph query expansion
- `store.py`: `MEMORY_RELS` tuple for memory-layer edge types (`SUPPORTS`, `ABOUT`, `REFERS_TO`, `INVOLVES`, `DESCRIBES`, `SUPERSEDES`, `DERIVED_FROM`)
- `store.py`: Composite indexes `idx_edges_src_rel` and `idx_edges_dst_rel` for faster edge traversal
- `kg.py`: `_short_chunk_boost()` — ranking boost for short factual chunks (< 200 chars) to surface single-sentence asides that are diluted in longer chunks
- `relations.py`: `_VALUE_PATTERNS` — regex patterns for percentages, currency amounts, color phrases, and occupational role phrases; `extract_entities()` now captures these in addition to titlecase proper nouns
- `dockg.py`, `graph.py`, `kg.py`: `chunk_strategy` (`"semantic"` | `"sentence_group"` | `"fixed"`) and `sentences_per_chunk` parameters propagated through `DocKG` → `DocGraph` → `parse_corpus()`; uses new `chunker_for()` factory
- `benchmarks/build_dockg.py`: `--chunk-strategy` and `--sentences-per-chunk` CLI arguments for `build_kg()`
- `benchmarks/longmemeval_dockg.py`: `_normalize_question()` — deterministic regex pre-processing that strips interrogative framing (`"What degree did I graduate with?"` → `"degree graduate with"`) to bring embeddings closer to answer text; applied before each query

### Changed
- `store.py`: `GraphStore.expand()` now uses batched SQL per hop (temp table + UNION) instead of per-node queries; frontier capped at `max_frontier=5000` to prevent explosive expansion through hub nodes; `CO_OCCURS_WITH` removed from `DEFAULT_RELS` (moved to `MEMORY_RELS` conceptually; excluded from document-layer defaults due to ~8M edges causing query slowdowns)
- `kg.py`: `DocKG.query()` and `DocKG.pack()` switched to `nodes_batch()` for node materialisation; edge fetch in `query()` is now conditional (`len(all_ids) <= max_nodes * 10`) to skip expensive JOINs on large corpora; ranking key now includes `short_boost`
- `kg.py`: `DocKG.query()` and `DocKG.pack()` ranking key switched to score-first ordering (`base_dist` → `best_hop` → boosts → kind → id), backported from MemoryKG where this change yielded +8.8 pp R@5 on LongMemEval benchmarks
- `dockg.py`, `graph.py`, `kg.py`: `emit_cooccur` default changed from `True` to `False` — CO_OCCURS_WITH is noisy and dense; semantic memory should use MemoryKG instead
- `benchmarks/longmemeval_dockg.py`: `query_sessions()` return type changed from `list[SessionHit]` to `tuple[list[SessionHit], QueryResult]` to expose raw result diagnostics; default `--hop` reduced from 2 to 1; default `--rels` now excludes `CO_OCCURS_WITH` to prevent explosive expansion; per-query diagnostics printed (seeds, expanded, returned nodes, query time)
- `.codekg/` → `.pycodekg/`: Renamed CodeKG snapshot and artifact directory from `.codekg/` to `.pycodekg/` to distinguish from DocKG (`.dockg/`); `.gitignore` updated to reflect new path; existing snapshot migrated

### Added
- `cmd_snapshot.py`: `dockg snapshot prune` command — removes vestigial snapshots (metric-duplicates, broken manifest entries, orphaned JSON files) while always preserving the oldest and newest; supports `--dry-run`
- `snapshots.py`: Re-export `PruneResult` from `kg_snapshot.snapshots` in the public API
- `.mcp.json`: MCP server configuration (copilot-memory, skills-copilot, task-copilot, pycodekg, dockg) now tracked in git; `.gitignore` un-ignored it and added `.agentkg/` to ignored paths
- `pyproject.toml`: `kgdeps` optional group with `pycode-kg`, `ftree-kg`, `agent-kg` (moved out of dev group); `detect-secrets` and `pdoc` added to dev deps; `testpypi` source added
- `pyproject.toml`: `[tool.poe.tasks.docs]` task for generating API docs with pdoc
- `.claude/settings.json`: Agent-kg `UserPromptSubmit` and `Stop` hooks for automatic conversation ingestion

### Changed
- `pyproject.toml`: `kg-snapshot` dependency switched from git source to TestPyPI published package (`>=0.3.0`); pylint config refactored to opt-in only (cyclic-import, broad-exception-caught, cell-var-from-loop, undefined-variable, import-outside-toplevel); mypy upgraded to Python 3.13 with `mypy_path` and `explicit_package_bases`; ruff `E501` (line-length) suppressed; `types-pyyaml` removed from dev deps
- `.dockg/snapshots/`: Pruned vestigial metric-duplicate snapshots from the repository

### Fixed
- `cmd_pipeline.py`: Cast `strategy: str` to `Literal["sentence_group", "semantic"]` for `PipelineConfig.chunk_strategy` to resolve mypy `arg-type` error
- `topics.py`: Added `# type: ignore[import-untyped]` on `import yaml` to resolve mypy `import-untyped` error (stubs not installed)
- `snapshots.py`: Added Author/License/Last Revision docstring header

- `settings.json.template`: Claude Code hooks template for agent-kg conversation ingestion — captures `UserPromptSubmit` and `Stop` events to the local agent-kg store asynchronously
- `PipelineConfig.sampling_strategy`: configurable Phase 1 sampling strategy (default `"diversity"`); was previously hardcoded — now wired through from the `--sampling` CLI option in `pipeline_run`

### Changed
- `pyproject.toml`: dev group marked `optional = true`; `code-kg` dev dep replaced with `pycode-kg` (new repo `Flux-Frontiers/pycode_kg`); `agent-kg` dev dep added (`Flux-Frontiers/agent_kg`); pylint `invalid-name` and `no-member` globally suppressed (ML matrix naming conventions; `SnapshotMetrics` typed-accessor attrs are false positives against the base `dict` type)

### Fixed
- `pipeline.py`: added `TYPE_CHECKING` guard import for `SentenceTransformerEmbedder` and typed `self._embedder: SentenceTransformerEmbedder | None` to resolve mypy `attr-defined` error; moved `if TYPE_CHECKING:` block after regular imports to fix pylint `wrong-import-position` (C0413)
- `topics.py`: initialized `self._kmeans: Any` and `self._cluster_labels: list[str]` in `__init__` (fixes pylint `attribute-defined-outside-init`); typed `_kmeans` as `Any` to eliminate mypy `attr-defined` errors on `.fit()`, `.predict()`, and `.cluster_centers_`
- `sampler.py`: renamed ML matrix variables `X` / `X_scaled` → `features_arr` / `features_scaled` for pylint naming compliance
- `topics.py`: renamed `X` → `embeddings_arr` in `fit_clusters` for consistency
- `embedder_worker.py`: added missing docstring to `n_vectors` property (fixes pylint `missing-function-docstring`)
- `cmd_pipeline.py`: wired `sampling` CLI arg into `PipelineConfig` (was silently ignored, triggering pylint `unused-argument`)
- `tests/test_snapshots.py`: fixed three failing snapshot tests (`test_list_snapshots_limit_zero_returns_all`, `test_snapshot_manager_get_previous`, `test_snapshot_manager_get_baseline`) — all failed because `save_snapshot` deduplicates entries with identical `version` + `metrics`; fixed by passing distinct `nodes=` counts per snapshot

- `scripts/generate_wiki.py`: Script to generate and publish GitHub wiki pages from `docs/` markdown files
- `poetry.toml`: `in-project = true` Poetry virtualenv configuration
- `src/doc_kg/__init__.py`: Package-level `__init__` exporting `DocKG` for cleaner imports
- `cli/cmd_model.py`: `dockg download-model` command to download and cache embedding models for offline use; supports `--force` re-download and `trust_remote_code` for `nomic-ai/*` models
- `pyproject.toml`: `einops` dependency added (required by `nomic-embed-text-v1`)
- `generate_wiki.py`: Wiki generation script added to project root
- `analysis/doc_kg_analysis_20260320.md`: DocKG architectural analysis report (2026-03-20)

### Changed
- `cli/options.py`, `cli/cmd_build.py`, `cli/cmd_query.py`, `cli/cmd_snapshot.py`: `--sqlite` and `--lancedb` options now default to `None`; each command resolves the paths relative to `<repo>/.dockg/` when not supplied, so the CLI works correctly regardless of the caller's working directory
- `cli/cmd_build.py`: Build output redesigned with Rich — section `Rule` headers, per-kind node counts (no raw Python dict dumps), features listed inline; embedder model name and dimension shown in summary; all three build commands (`build`, `build-graph`, `build-index`) updated consistently
- `index.py`: `SemanticIndex.build()` now shows a Rich progress bar (transient, with count and elapsed time) during batch embedding when `quiet=False`; `build()` stats dict now includes `model_name`
- `cli/cmd_hooks.py`: Pre-commit hook reordered — snapshot capture now runs *before* quality checks so the tree hash reflects staged content; snapshot failure is now non-fatal (warning only, does not abort commit); skip env var renamed from `CODEKG_SKIP_SNAPSHOT` to `DOCKG_SKIP_SNAPSHOT`
- `cli/main.py`: Registered `cmd_model` subcommand; updated usage docstring with `download-model`
- `index.py`: `SentenceTransformerEmbedder.__init__` now suppresses HF logging via `hf_logging.set_verbosity_error()`, wraps model load with `TQDM_DISABLE=1`, and passes `trust_remote_code=True` for `nomic-ai/*` models
- `analysis/CodeKG_Agent_instructions.md` renamed to `analysis/DocKG_Agent_instructions.md`

### Changed
- `pyproject.toml`: `kg-snapshot` dependency switched from local path (`../kg_snapshot`) to published git source (`github.com/Flux-Frontiers/kg_snapshot`); `kg-rag` dev dependency removed
- `src/doc_kg/snapshots.py`: Updated docstring module references from `kg_rag.snapshots` to `kg_snapshot.snapshots`

### Fixed
- `dockg.py`: Changed `DEFAULT_MODEL` from `all-mpnet-base-v2` to `nomic-ai/nomic-embed-text-v1`; fixed the HuggingFace 404 error caused by the nonexistent `sentence-transformers/nomic-embed-text` model ID

## [0.4.1] - 2026-03-18

### Added
- `snapshots.py`: `_package_version()` helper that auto-detects the installed `doc-kg` version via `importlib.metadata`

### Changed
- `snapshots.py`: `Snapshot.version` field is now optional (default `""`); auto-populated from the installed package when not explicitly supplied
- `snapshots.py`: `SnapshotManager.capture()` `version` parameter is now optional (`None` by default); falls back to `_package_version()` when omitted
- `snapshots.py`: `Snapshot.from_dict()` now calls `data.setdefault("version", "")` for backward-compatible loading of snapshots that predate the optional field
- `cli/cmd_snapshot.py`: `VERSION` CLI argument for `dockg snapshot save` is now optional (default `""`)
- `cli/cmd_hooks.py`: pre-commit hook no longer reads version from `pyproject.toml`; calls `dockg snapshot save` without a version argument, relying on auto-detection
- `cli/cmd_hooks.py`: skip env var renamed from `DOCKG_SKIP_SNAPSHOT` to `CODEKG_SKIP_SNAPSHOT` for consistency with CodeKG convention
- `pyproject.toml`: `code-kg` (git) dependency moved from `main` to `dev` group; `ftree-kg` (git) dev dependency added

## [0.4.0] - 2026-03-14

### Added
- VS Code workspace file (`src/doc_kg/doc_kg.code-workspace`) for IDE integration
- `analysis/doc_kg_analysis_20260314.md`: CodeKG architectural analysis report (2026-03-14)
- `Snapshot.issues` field: list of issue-description strings now stored per snapshot
- `Snapshot.key` property: stable alias for `tree_hash`, used as the file key throughout

### Changed
- `src/doc_kg/snapshots.py`: replaced `commit` field with `tree_hash` as the stable snapshot key
  - `Snapshot.commit` removed; `Snapshot.tree_hash` is the new primary identifier
  - `Snapshot.key` property returns `tree_hash` for use as file key and manifest lookup
  - `SnapshotManager._get_current_commit()` renamed to `_get_current_tree_hash()`
  - `capture()` accepts `tree_hash` kwarg (was `commit`); auto-detects via `git write-tree` if omitted
  - `from_dict()` silently drops legacy `commit` field for backward-compatible loading
  - `load_snapshot()` now backfills `vs_previous` from manifest ordering when absent in the JSON file
  - Updated module docstring with full usage example and field-level inline comments
- `src/doc_kg/cli/cmd_snapshot.py`: `--commit` CLI option renamed to `--tree-hash`; issues list forwarded to `capture()`
- `.github/workflows/snapshots.yml`: updated `dockg snapshot save` invocation from `--commit` to `--tree-hash`
- `tests/test_snapshots.py`: full test suite rewrite — all tests ported to `tree_hash`-based API, helper `_make_snapshot` replaced by `_make_dockg_snapshot`, added new tests for git helpers, `vs_previous` backfill, and `issues` field
- `src/doc_kg/cli/group.py`: new module that houses the root Click group, extracted from `main.py` to eliminate circular imports between the entry-point and `cmd_*` submodules
- `pylint ^4.0.5` dev dependency with full `[tool.pylint.*]` configuration in `pyproject.toml` (design/format/similarities/messages_control sections)
- `code-kg` (git) dependency added to `pyproject.toml` for CodeKG integration
- All `cmd_*` CLI modules (`cmd_analyze`, `cmd_build`, `cmd_hooks`, `cmd_mcp`, `cmd_query`, `cmd_snapshot`, `cmd_viz`) now import `cli` from `doc_kg.cli.group` instead of `doc_kg.cli.main`, resolving circular import issues
- `src/doc_kg/cli/main.py`: reduced to re-exporting `cli` from `group.py` and registering submodule imports
- `src/doc_kg/cli/cmd_hooks.py`: Enhanced pre-commit hook with quality checks integration
  - Hook now runs `.pre-commit-config.yaml` checks (ruff, mypy, detect-secrets, etc.) before snapshot capture
  - Hook rebuilds local DocKG index (`dockg build --wipe`) to keep it in sync with commits
  - Changed success message from `✓` emoji to `OK` prefix
- `.github/workflows/snapshots.yml`: Refactored snapshot workflow for consistency
  - Simplified build phase to use unified `dockg build --wipe` instead of separate `build-graph` and `build-index` commands
  - Changed snapshot keying from short commit hash (`SHORT_COMMIT`) to full tree hash (`TREE_HASH` via `git write-tree`)
  - Replaced ad-hoc `dockg analyze` output with structured `dockg snapshot save` command
  - Workflow now commits and pushes snapshots directly to repository instead of uploading as artifacts
- `.pre-commit-config.yaml`: Fixed pylint hook to run via `poetry run` for access to project dependencies (was failing with import errors)
- `pyproject.toml`: Updated `pre-commit` dependency to `^4.5.1`
- `src/doc_kg/relations.py`: split overlong regex literal across multiple lines; simplified `cooccur_pairs` to `list(itertools.combinations(...))` directly
- Code quality: added missing public-method docstrings in `kg.py`, `snapshots.py`, `app.py`; added targeted `pylint: disable` annotations in `dockg.py`, `index.py`, `mcp_server.py`, `topics.py`; fixed bare `except ImportError` chain in `cmd_mcp.py`

## [0.3.0] - 2026-03-12

### Added
- `dockg install-hooks` CLI command: installs a DocKG pre-commit hook that captures a metrics snapshot (keyed by tree hash) and stages it atomically — mirrors CodeKG hook pattern; skip with `DOCKG_SKIP_SNAPSHOT=1` env var
- `src/doc_kg/cli/cmd_hooks.py`: hook installation module with embedded pre-commit hook script
- Documentation updates:
  - `docs/CHEATSHEET.md`: rewritten for DocKG MCP tools (`graph_stats`, `query_docs`, `pack_docs`, `get_node`)
  - `docs/SNAPSHOTS.md`: updated from CodeKG to DocKG snapshots (metrics for document corpora, not code)
  - `docs/deployment.md`: rewritten for DocKG deployment options (PyPI, Streamlit Cloud, Fly.io, MCP server)
  - `docs/dockg_workflow.md`: new practical workflow guide showing `dockg build`, `query`, `pack`, `analyze`, `viz`, `snapshot` commands
- `scripts/install-hooks.sh`: installs a DocKG pre-commit hook that captures a metrics snapshot (keyed by tree hash) and stages it atomically — mirrors CodeKG hook pattern; skip with `DOCKG_SKIP_SNAPSHOT=1`
- `--exclude-dir` CLI option on `build` and `build-graph` commands: exclude directory names at every depth during file walk (repeatable, merged with config)
- `src/doc_kg/config.py`: new module with `load_exclude_dirs()` to read `[tool.dockg].exclude` from pyproject.toml — mirrors CodeKG pattern
- `.dockg/snapshots/`: initial 6-commit snapshot history (migrated from `.codekg/snapshots/` where bad hook was writing them)
- MCP server (`src/doc_kg/mcp_server.py`): `dockg mcp` / `dockg-mcp` entry point exposing `graph_stats`, `query_docs`, `pack_docs`, and `get_node` tools for MCP-compatible agents (Claude Code, Claude Desktop, GitHub Copilot, Cursor, Continue)
- Streamlit visualizer (`src/doc_kg/app.py`): interactive PyVis-based graph explorer with per-node-kind colour/shape coding and per-relation-kind edge colours
- CLI subcommands: `dockg mcp`, `dockg analyze`, `dockg viz`, `dockg build-graph`, `dockg build-index`
- `DocKGAnalyzer` (`src/doc_kg/dockg_thorough_analysis.py`): nine-phase corpus analysis engine (baseline metrics, semantic coverage, top documents, hot chunks, strengths/weaknesses)
- Snapshot management (`src/doc_kg/snapshots.py`, `src/doc_kg/cli/cmd_snapshot.py`): `dockg snapshot save|list|show|diff` for temporal tracking of metrics across versions (commits, branches, coverage)
- GitHub workflows and actions: CI pipeline, publish workflow, snapshot CI, and DocKG reusable action for automated knowledge graph building
- `mcp>=1.0.0` dependency
- `types-pyyaml^6.0.12.20250915` for type hints
- CLI smoke tests (`tests/test_cli.py`): verify all subcommands are registered via Click `CliRunner`

### Changed
- All CLI commands now use `--repo` (named option) instead of a positional `corpus_root` argument, matching the CodeKG CLI pattern; `repo_option` shared decorator added to `src/doc_kg/cli/options.py`; affected commands: `build`, `build-graph`, `build-index`, `analyze`, `query`, `pack`, `mcp`
- `src/doc_kg/dockg.py`: `SKIP_DIRS` documented with per-entry comments and a block comment explaining the additive exclusion contract
- `pyproject.toml`: removed redundant `[tool.dockg].exclude` list (all entries duplicated `SKIP_DIRS`); replaced with template comment; removed contradictory `ignore = ["E501"]`; cleaned up stale blank lines
- `.gitignore`: generalized `.dockg/*.sqlite*` glob to cover all SQLite files (was only excluding `graph.sqlite`, missing `docs.sqlite` and future DBs); removed stale `.dockg/docs_lancedb/` entry; consolidated lancedb pattern to `lancedb*`
- `DocKG.__init__` now accepts `exclude: set[str] | None` parameter, forwarded to DocGraph for file walk filtering
- `src/doc_kg/cli/cmd_build.py`: `build` and `build-graph` commands now merge `--exclude-dir` flags with `[tool.dockg].exclude` from pyproject.toml
- `docs/MCP.md` rewritten as a DocKG-specific MCP setup guide covering all supported clients; added example of excluding directories
- `README.md`: documented `--exclude-dir` option and exclude priority order (built-in SKIP_DIRS + pyproject.toml + CLI flags)
- `src/doc_kg/cli/main.py`: registers `cmd_analyze`, `cmd_mcp`, `cmd_viz` subcommands
- `src/doc_kg/cli/cmd_build.py`: extended with `build-graph` and `build-index` split commands
- `analysis/doc_kg_analysis_20260308.md`: replaced with fresh DocKG-native analysis (1 537 nodes, 8 358 edges; 97.4% topic coverage)

### Removed

### Fixed
- `Snapshot.from_dict()` crashes on legacy snapshot JSON files that use old field names (`docstring_coverage`, `critical_issues`); added migration shim that renames them to `coverage_score` / `issues_count` on load

## [0.2.0] - 2026-03-08

### Added
- `dockg install-hooks` CLI command
- MCP server, Streamlit visualizer, `analyze`, `viz`, `build-graph`, `build-index` subcommands
- Snapshot management (`dockg snapshot save|list|show|diff`)

## [0.1.0] - 2026-03-08

### Added
- Initial DocKG implementation — document knowledge graph from `.md` / `.txt` files
- `dockg build`, `dockg query`, `dockg pack` CLI commands
- Hybrid semantic + structural graph (SQLite + LanceDB)
- Default embedding model: `all-mpnet-base-v2`

### Changed

### Removed

### Fixed
