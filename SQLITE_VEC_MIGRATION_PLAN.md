# sqlite-vec Migration Plan — LanceDB → SQLite across the KG fleet

**Status:** ✅ Phases 0–5 DONE (working trees, uncommitted) · RunPod push
(Phase 5 last step) intentionally deferred · 2026-07-14
**Driver repo:** this one (`doc_kg`). Touches `../KG_utils` (kgmodule-utils),
`doc_kg`, and `../gutenberg_kg`. DiaryKG needs **no changes** (it delegates all
vector work to `doc_kg.kg.DocKG`).

## Why (evidence)

Benchmark on the real consolidated Gutenberg corpus
(`../gutenberg_kg/benchmarks/bench_sqlite_vec.py`, results in
`../gutenberg_kg/benchmarks/SQLITE_VEC_RESULTS.md`), 361,521 chunk/section
vectors, 384-dim bge-small, 12 golden queries vs exact NumPy ground truth:

| Engine | mean recall@10 | median latency | store size |
|---|---|---|---|
| LanceDB IvfFlat (production defaults) | **0.825** | 77 ms | 2.5 GB |
| vec0 fp32 (exact brute force) | **1.000** | 132 ms | 636 MB |
| vec0 int8 (exact) | 0.942 (MAE 0.002) | 85 ms | 218 MB |

Production LanceDB is *dropping real hits* ("pillar of salt": 0.4 recall).
sqlite-vec is exact, comparable latency, 9–11× smaller, and unifies the stack
on one storage engine (FTS5 + graph + vectors all SQLite). It also unblocks
the native macOS/iOS app (`../gutenberg_kg/docs/APP_ARCHITECTURE.md`) — Swift
reads SQLite; it cannot read LanceDB.

**Migration is a conversion, not a rebuild** — vectors are read out of
existing LanceDB tables and written to vec0 (~3 s for 361K vectors). No
re-embedding, ever.

## Ground truth — every LanceDB touchpoint

| Where | What | Role |
|---|---|---|
| `../KG_utils/src/kg_utils/semantic.py` (342 lines) | `SemanticIndex` — `build` L152, `search` L213 (no `where` param), `_open_table` L247, `_get_table` L281 | Fleet-wide simple index (pycode_kg re-exports it) |
| `../KG_utils/src/kg_utils/{module,pipeline,__init__}.py` | path plumbing / re-exports only | mechanical |
| `src/doc_kg/index.py` (1,541 lines) | Heavy `SemanticIndex`: `build` L252, `_existing_index_ids` L506, `prune` L539, `precompute_embeddings` L566, `build_from_cache` L841, `_discover_similar_edges` L1128, `search(query,k,where)` L1330, `_open_table` L1379, `_get_table` L1406, `_maybe_create_ann_index` L1418, `_table_has_ann_index` L1480 | Corpus-scale workhorse |
| `src/doc_kg/kg.py` | `DocKG` — scope prefilter builder ~L499 (emits LanceDB SQL `where` strings), lazy index ~L729, RRF fusion ~L1051 | Query orchestration |
| `src/doc_kg/cli/{options,cmd_build,cmd_query,…}.py` | `--lancedb` path options | mechanical |
| `../gutenberg_kg/src/gutenberg_kg/serve/handler.py` | `_open_dockg_table` L245, `_table_search` L369 (raw lancedb, bypasses DocKG) | serving |
| `../gutenberg_kg/runpod/handler.py` | `_open_dockg_table` L202, `_table_search` L272 | serving |

Write-path concurrency is already safe for SQLite: builds use
cache-then-single-writer (`precompute_embeddings` → `build_from_cache`);
embed workers never write to the vector store directly.

## Settled design

- **Backend seam, not a rewrite.** A `VectorBackend` protocol lives in
  `kg_utils`; `LanceDBBackend` wraps the existing code unchanged;
  `SqliteVecBackend` is new. Both `SemanticIndex` classes take a backend.
- **Default stays `lancedb`** until the parity gate is green; flip per-KG via
  config/CLI (`vector_backend: lancedb | sqlite-vec`).
- **Store layout (v1): sidecar file** `.dockg/vectors.sqlite` next to
  `graph.sqlite`, containing:
  - `vec_meta(id TEXT PRIMARY KEY, kind, name, title, file_path)` — the same
    columns LanceDB rows carry today, so `SeedHit` hydration is a join;
  - `vec_nodes` — `vec0(embedding float[<dim>] distance_metric=cosine)`
    row-aligned with `vec_meta` (same rowid).
  Merging into `graph.sqlite` (single-file KG) is a later, optional phase —
  `ATTACH` makes the two-file form equivalent for readers.
- **Prefilter strategy: reuse the existing `where` strings.** The SQL dialect
  DocKG emits (`kind IN (...)`, `file_path LIKE/NOT LIKE ...`) is valid
  SQLite. The sqlite backend compiles
  `search(qvec, k, where)` into:
  `... WHERE embedding MATCH ? AND k = ? AND rowid IN
  (SELECT rowid FROM vec_meta WHERE <where>)` — true prefilter semantics.
- **fp32 vectors in v1.** int8 (3× smaller, recall 0.94 raw) is a converter
  flag; adopt later with oversample-and-rescore if size matters (it does for
  iOS, not for servers).
- **ANN machinery is deleted, not ported**: `_maybe_create_ann_index`,
  `_table_has_ann_index`, nprobes/refine plumbing become lancedb-backend
  internals; the sqlite backend is always exact.
- **Pin `sqlite-vec` exactly** (`sqlite-vec ==0.1.9` to start) — pre-1.0,
  breaking minors possible. Prebuilt wheels for macOS arm64 + Linux x86_64
  exist; no compile step; Poetry-compatible.

### Known gotchas (learned in the benchmark — do not rediscover)

1. **int8 blobs must be wrapped**: `INSERT ... VALUES (?, vec_int8(?))` and
   `embedding MATCH vec_int8(?)`. A raw 384-byte blob is silently parsed as
   float32 and errors (or worse, mis-searches) on int8 columns.
2. KNN queries require the `k = ?` constraint in the WHERE clause and
   `ORDER BY distance`.
3. `conn.enable_load_extension(True)` before `sqlite_vec.load(conn)`, then
   disable. Verify the target Python builds support extension loading
   (poetry envs here do; stock macOS system Python may not).
4. vec0 distance is *distance* (1 − cosine); convert to similarity at the
   same place `_extract_distance` does today.

---

## Phase 0 — spikes & stopgap (½ day) — ✅ DONE 2026-07-14

Verifications that gate design details. Do these first; they are cheap.

- [x] **Spike: TEXT-PK filtered KNN.** ✅ PASS. Went straight to **explicit
  integer rowid alignment** (the plan's fallback), which is cleaner than a
  TEXT PK on the vec0 table: `vec_meta(id TEXT PRIMARY KEY, kind, name, title,
  file_path)` with an explicit integer `rowid`, and a sibling
  `vec_nodes USING vec0(embedding float[384] distance_metric=cosine)` inserted
  with the *same* explicit `rowid`. Then
  `... WHERE embedding MATCH ? AND k = ? AND vec_nodes.rowid IN
  (SELECT rowid FROM vec_meta WHERE <where>) ORDER BY distance` is a **true
  prefilter**: on the real 361,521-row store, `kind = 'chunk'` (353,790 rows ≫
  k=10) returned exactly 10 hits, *all* chunks. `file_path NOT LIKE
  '%reference.md'` also returned 10 — the DocKG SQL dialect is valid SQLite.
- [x] **Spike: latency with subquery filter** on the 361K table. ✅ PASS —
  **177 ms warm median** (min 173, max 181), under the ~200 ms gate. (Bare vec0
  without the join/subquery was 132 ms in the benchmark; the prefilter join
  adds ~45 ms — acceptable.)
- [x] **Spike: upsert/delete.** ✅ PASS. `DELETE FROM vec_nodes WHERE rowid IN
  (...)` + `DELETE FROM vec_meta WHERE rowid IN (...)` removed the rows (absent
  from results), and re-inserting restored them (present again, count back to
  361,521). `prune()`/incremental-embed semantics are sound.
- [x] **Stopgap (independent, shipped in working tree — NOT yet committed):**
  added `.nprobes(128)` to `_table_search` in
  `../gutenberg_kg/src/gutenberg_kg/serve/handler.py` and
  `../gutenberg_kg/runpod/handler.py`. **⚠️ Correction to the plan: nprobes=64
  only reaches recall 0.925, below the 0.95 target. Use 128.** Sweep vs exact
  ground truth on the consolidated bundle (12 golden queries):

  | config | mean recall@10 | median ms |
  |---|---|---|
  | default (index) | 0.825 | 75 |
  | nprobes=32 | 0.875 | 76 |
  | nprobes=64 | 0.925 | 77 |
  | nprobes=64 + refine_factor=4 | 0.925 | 77 |
  | **nprobes=128** | **0.992** | 80 |

  `refine_factor` added nothing over nprobes alone; 128 costs only ~+5 ms.

**Store size:** the twin-table fp32 store was **685 MB** for 361,521 vectors
(plan estimated ~636 MB; the delta is the `vec_meta` table + WAL). Build time
**5.0 s** — confirms "conversion, not rebuild".

**Verify:** ✅ all three spike scripts pass; nprobes sweep confirms LanceDB
recall 0.992 at nprobes=128. Spike scripts:
`scratchpad/spike_phase0.py`, `scratchpad/nprobes_sweep.py`.

## Phase 1 — `VectorBackend` seam in KG_utils (1–2 days) — ✅ DONE 2026-07-14

**Status:** landed in `../KG_utils` working tree (not committed). Full suite
green: **457 passed, 1 skipped**; 18 new backend tests. Verify gate met —
`test_backends_agree_on_topk` confirms LanceDB & sqlite-vec return identical
top-k ids on 3 sample queries. Version bumped 0.4.9 → **0.5.0**; CHANGELOG
updated. **Design refinement vs plan:** one shared backend parametrized by
`meta_columns` (no per-domain backend duplication); sqlite mirrors LanceDB's
fresh-table dedup fast-path; `delete_ids` returns *actual* rows removed on both.
Follow-up logged to collapse the two `SemanticIndex` classes later (separate
refactor, out of scope here).

- [x] Add `src/kg_utils/vector_backend.py`: protocol with
  `open(wipe)`, `upsert(rows, batch_size) -> int`, `delete_ids(ids) -> int`,
  `existing_ids() -> set[str]`,
  `search(qvec, k, where: str | None) -> list[dict]`, `count() -> int`.
  Rows carry `{id, kind, name, title, file_path, text, vector}` (today's
  LanceDB row shape).
- [ ] `LanceDBBackend`: move the bodies of `semantic.py::_open_table` /
  `_get_table` / search plumbing behind the protocol **unchanged** (byte-for-
  byte behavior; keep ANN gating inside this backend).
- [ ] `SqliteVecBackend`: vec_meta + vec0 twin tables per the settled design;
  batched inserts in one transaction; WAL mode; `where` compiled to the
  rowid-subquery form from Phase 0.
- [ ] `kg_utils.semantic.SemanticIndex` takes `backend=` (default lancedb);
  `search()` grows the `where: str | None = None` param (doc_kg's already
  has it; this unifies the signatures).
- [ ] Add `sqlite-vec ==0.1.9` as an optional extra
  (`kgmodule-utils[sqlite-vec]`) so lancedb-only consumers don't pull it.
- [ ] Tests: parametrize the existing semantic-index tests over both
  backends; add a filtered-search test and an int8 round-trip test
  (covers gotcha #1).
- [ ] Bump kgmodule-utils → 0.5.0; changelog entry.

**Verify:** `cd ../KG_utils && poetry run pytest` green with both backends in
the matrix; a tiny corpus indexed with each backend returns identical top-k
ids on 3 sample queries.

## Phase 2 — doc_kg adoption (2–3 days, the big one) — ✅ DONE 2026-07-14

**Status:** landed in doc_kg working tree (not committed). kg_utils 0.5.0
installed editable into doc_kg `.venv` (+ sqlite-vec). Full suites green:
**doc_kg 388 passed / 1 skipped**, **kg_utils 471 passed / 1 skipped**.

**What landed:**
- `index.py::SemanticIndex` fully routed through `VectorBackend`: `build`,
  `build_from_cache`, `_build_from_jsonl_cache` → `backend.upsert()`;
  `search(query,k,where)` → `backend.search()`; `_existing_index_ids` →
  `backend.existing_ids()`; `prune` → `backend.delete_ids()`. Added
  `_get_backend()`, `_lance_table()`, `_finalize_backend()` (LanceDB compaction
  + IVF, no-op on sqlite). New `backend=` param (defaults to LanceDB).
- ANN machinery **deleted** from doc_kg (`_open_table`, `_get_table`,
  `_maybe_create_ann_index`, `_table_has_ann_index`, `_pq_subvectors`,
  `_escape`) — relocated to `LanceDBBackend`. `_discover_similar_edges` was
  already a backend-independent BLAS matmul (plan's per-node-kNN concern moot;
  `tbl` arg now passed `None`).
- `make_backend()` / `sqlite_vectors_path()` factory in `index.py`.
- Config/CLI: `DocKG(vector_backend=...)` + `DOCKG_VECTOR_BACKEND` env +
  `dockg build/query --vector-backend {lancedb|sqlite-vec}`. Sidecar path
  derived as `.dockg/vectors.sqlite`.
- `DocKG.stats()` reports `vector_backend` + `vector_count` (no model load).
- Tests: kg_utils gained backend-parity + ANN-gate + `_pq_subvectors` +
  int8-roundtrip tests; doc_kg's `test_ann_index.py` rewritten to test
  delegation + sqlite no-op path; new `test_vector_backend_e2e.py` builds a
  real GraphStore through both backends with a fake embedder and asserts
  top-k parity + prefilter + sidecar-not-lancedb.
- Dep bumped `kgmodule-utils>=0.5.0`; optional `doc-kg[sqlite-vec]` extra;
  CHANGELOG Unreleased entry. **Version number bump deferred to the release
  flow** (user controls versioning via /release).
- **Caught + fixed a real porting bug:** `_pq_subvectors` in the backend
  returned the wrong divisor (96 vs 24 for dim 384); now matches doc_kg's
  ~16-dims-per-subvector algorithm exactly.

**Verify:** ✅ `pytest` green both repos. ✅ End-to-end with the **real
bge-small model**: `dockg build --vector-backend sqlite-vec` +
`dockg query` on a 3-file corpus returns **identical top-3 hits** to a
LanceDB build; sqlite build writes only `vectors.sqlite` (no lancedb dir).
Scratch proof: `scratchpad/e2e_backends.py`.



- [ ] Bump dep to `kgmodule-utils >= 0.5.0`.
- [ ] Refactor `src/doc_kg/index.py::SemanticIndex` to hold a
  `VectorBackend` and route through it:
  - [ ] `_open_table`/`_get_table` → `backend.open()` / lazy handle
  - [ ] `_existing_index_ids` (L506) → `backend.existing_ids()`
  - [ ] `prune` (L539) → `backend.delete_ids()`
  - [ ] `build` / `build_from_cache` / `_build_from_jsonl_cache` batch
        writes → `backend.upsert()` (keep the streaming/batching structure;
        only the sink changes)
  - [ ] `search` (L1330) → `backend.search(qvec, k, where)`; keep
        `SeedHit` shaping and `_extract_distance` here
  - [ ] `_discover_similar_edges` (L1128) → per-node kNN via
        `backend.search` (verify batch performance on a per-book KG;
        cap-8 behavior unchanged)
  - [ ] ANN config (`ann_threshold`, `ann_nprobes`, `ann_refine_factor`)
        passes through to LanceDBBackend only; no-op warning on sqlite-vec
- [ ] Config + CLI: `vector_backend` key (KG config / env / flag) threaded
  through `kg.py` lazy-index construction (~L729) and
  `cli/options.py`; `lancedb_dir` option kept, plus `vectors.sqlite` path
  derivation for the new backend.
- [ ] `DocKG.stats()` reports backend + vector count for either store.
- [ ] Tests: run the DocKG suite (`test_dockg.py`, `test_query_scope.py`,
  `test_kg_ranking.py`, `test_ann_index.py`) with
  `vector_backend=sqlite-vec` fixtures; `test_ann_index.py` asserts the
  no-op path for sqlite-vec.
- [ ] Version bump + changelog.

**Verify:** `poetry run pytest` green; then end-to-end on a real small
corpus: `dockg pipeline run` (or `build`) with `vector_backend=sqlite-vec`
in a scratch repo → `dockg query "<known phrase>"` returns the same top hits
as a lancedb build of the same corpus.

## Phase 3 — converter + parity gate (~1 day) — ✅ DONE 2026-07-14

**Status:** landed (doc_kg working tree). `convert_lancedb_to_sqlite()` in
`index.py` + `dockg convert-index --to sqlite-vec [--dtype fp32|int8]
[--vectors-path] [--wipe]` CLI. Projects only id+meta+vector (drops the `text`
blob; falls back to full `to_arrow()` when this lancedb lacks `columns=`).
Committed test `test_convert_lancedb_to_sqlite_matches` (build lancedb →
convert → top-k parity). **doc_kg 389 passed.**

**Real-data verify:**
- ✅ Converted the consolidated bundle: **688,852 vectors in 46 s → 1.1 GB**
  vectors.sqlite (vs 2.5 GB LanceDB, 2.3× smaller), validated=True. (Plan's
  ~650 MB estimate was for the 361K *searched subset*; this is the full index
  incl document/topic/entity/keyword kinds.)
- ✅ Converted all **4 diary KGs** (`corpus/diaries/*/.diarykg/`): 10,409 /
  10,846 / 13,034 / 44,331 vectors, all validated (18–72 MB each).
- ✅ **Golden parity gate GREEN**: all 12 golden queries at **recall@10 = 1.0**
  through `SqliteVecBackend.search(where=<handler prefilter>)` vs exact NumPy
  ground truth over the eligible subset — including "pillar of salt" (LanceDB
  dropped it to 0.4). Script: `scratchpad/parity_gate.py`.



- [ ] `dockg convert-index --to sqlite-vec [--dtype fp32|int8] [--wipe]`:
  reads the existing LanceDB table (ids, kind, name, title, file_path,
  vector — **not** text), writes `vectors.sqlite`. Adapt from
  `../gutenberg_kg/benchmarks/bench_sqlite_vec.py::build_vec0`.
- [ ] Converter validates: row count matches source; 5 random ids return
  identical vectors (cosine of stored vs source ≥ 0.9999).
- [ ] Golden parity gate as a doc_kg script/test: N queries → NumPy exact
  ground truth from source vectors → assert sqlite-vec recall@10 == 1.0
  (fp32) and LanceDB recall reported (informational).
- [ ] Run converter on the real consolidated bundle
  (`../gutenberg_kg/bundles/gutenberg-all/.dockg/`) and all 4 diary KGs
  (`corpus/diaries/*/.diarykg/`).

**Verify:** converter exits 0 on all 5 real stores; parity gate green;
converted consolidated store ≈ 650 MB fp32.

## Phase 4 — gutenberg_kg handlers (~1 day) — ✅ DONE 2026-07-14

**Status:** handler code migrated + confirmed in-process; docker image build is
the one remaining step (see decision below).

**What landed:**
- `serve/handler.py` + `runpod/handler.py`: new `_open_vector_source(dockg_dir)`
  opens `vectors.sqlite` (SqliteVecBackend, `check_same_thread=False` for the
  threaded worker) when present, else falls back to LanceDB (transition safety).
  `_open_dockg_table` and the diary bootstrap both use it. `_table_search`
  dispatches: `SqliteVecBackend.search(qvec,k,where)` vs the LanceDB
  `nprobes(128)` path. The lexical-rescue `id IN (...)` clause is valid over
  `vec_meta`, so it ports unchanged. `_rows_to_hits` input shape is identical
  (id/kind/name/title/file_path/_distance).
- Added `check_same_thread` to `SqliteVecBackend` (kg_utils).
- Converted the bundle's 4 diary stores too — the whole
  `bundles/gutenberg-all/` bundle is now sqlite-vec.
- **Default flipped to `"auto"`** (user request): sqlite-vec for fresh/converted
  corpora, lancedb only for un-migrated ones. Fleet default (kg_utils) stays
  lancedb (pycode_kg et al. not yet migrated). `--delete-lancedb` cleanup flag
  added to `convert-index`.

**Verify:**
- ✅ **In-process real-handler confirm** against the converted bundle
  (`GUTENBERG_ROOT=bundles/gutenberg-all`): startup logs
  `DocKG: sqlite-vec store (688852 vectors)`, `_DOCKG_TABLE` is a
  `SqliteVecBackend`, and `handler()` served the golden queries correctly
  ("whiteness of the whale" → Moby Dick 0.834, "time travel" → The Time
  Machine). Script: `scratchpad/handler_confirm.py`.
- ✅ **Local docker deploy CONFIRMED.** Built `corpus-gutenberg-sqlite:latest`
  from `docker/Dockerfile.sqlite` (installs local kg_utils 0.5.0 + doc_kg
  wheels from `docker/wheels/` + `sqlite-vec==0.1.9`; bakes **sqlite-vec only** —
  consolidated LanceDB omitted, per-diary lancedb stripped). **Image 5.27 GB vs
  the old 19.3 GB.** Container startup logged `DocKG: sqlite-vec store (688852
  vectors)` + all 4 diaries on sqlite-vec + FTS5. Golden queries POSTed to
  `http://localhost:8000/runsync` returned `status=COMPLETED` with correct hits
  (whale→Moby Dick 0.834, Hell→Divine Comedy 0.749, time-travel→Time Machine).
  Build-from-local approach chosen so no PyPI publish was needed.


- [ ] `serve/handler.py`: `_open_dockg_table` opens
  `vectors.sqlite` (sqlite3 + `sqlite_vec.load`) when present, else falls
  back to LanceDB (transition safety); `_table_search` gains the vec0 SQL
  path. `_rows_to_hits` input shape unchanged (id/kind/name/title/
  file_path/distance from the vec_meta join).
- [ ] Same for `runpod/handler.py` (+ its diary table opens).
- [ ] The lexical-rescue hydration in `_semantic_search`
  (`id IN (...)` re-search) ports to a vec_meta-scoped vec0 query.
- [ ] Golden queries through the actual worker HTTP API: start the local
  worker on the converted bundle, POST the 12 benchmark queries, diff hit
  ids/scores against the LanceDB worker (expect *better* — the 0.825 →
  1.0 recall delta shows up here).
- [ ] `gutenkg chat` smoke test: "pillar of salt" now surfaces the Genesis
  passage in the top hits.

**Verify:** worker responds on all 12 golden queries with recall@10 = 1.0
vs ground truth; chat renders hits + synthesis normally.

## Phase 5 — deploy & flip (~½ day) — ✅ DONE (minus RunPod push) 2026-07-14

Per user: everything **except the actual RunPod push/redeploy**. The push is a
one-liner away when they're ready.

- [x] **Bundle layout is sqlite-vec-only.** `runpod/push_indices.sh` now rsyncs
  with `--exclude 'lancedb'` (drops ~2.3 GB) and its documented remote layout
  shows `vectors.sqlite` instead of `lancedb/`. **Not pushed** (no RunPod).
- [x] **gutenberg_kg builds flipped to sqlite-vec.** `build_corpus.py`'s
  index-building `DocKG(...)` now passes `vector_backend="sqlite-vec"` (writes
  `<bundle>/.dockg/vectors.sqlite`); progress/dry-run strings updated.
  `build-diaries` needs no change — DiaryKG delegates to DocKG and the new
  `"auto"` default resolves fresh rebuilds to sqlite-vec. Fleet default
  (kg_utils) stays lancedb (pycode_kg et al. not migrated).
- [x] **Docs updated.** `docs/APP_ARCHITECTURE.md` §1 (worker now sqlite-vec;
  size table shows 1.1 GB `vectors.sqlite`) + §3.3 (server migration landed →
  app reads the *same* `vectors.sqlite` the worker serves, macOS conversion
  step gone). README §"Indexed" now says "SQLite (FTS5 + sqlite-vec)".
- [x] **nprobes stopgap — KEPT, not removed (deviation from plan, deliberate).**
  It lives on the LanceDB branch of `_table_search`, which is the live
  **fallback** for any un-converted corpus — not dead code. Removing it would
  silently drop fallback recall from ~0.99 back to 0.825. Retained as a
  quality guard; delete only if/when the LanceDB fallback path itself is removed.
- [ ] **RunPod push/redeploy — NOT DONE (intentionally skipped).**

**Verify:** ✅ build_corpus threads `vector_backend`; handlers + push script +
docs updated; ruff clean. RunPod production verification deferred.

## Phase 6 (optional, later) — single-file KGs

Merge `vec_meta`/`vec_nodes` into `graph.sqlite` so a KG is literally one
file (build-time change + reader `ATTACH` removal). Do only when the macOS
app work starts consuming stores directly.

## Rollback

Every phase is additive behind the `vector_backend` flag; LanceDB code paths
remain intact until Phase 5's flip (and even then the backend is selectable).
Rollback = set `vector_backend: lancedb`. The converter never mutates source
LanceDB data.
