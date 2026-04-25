# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

### Changed

### Removed

### Fixed

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
