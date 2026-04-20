# Release Notes — v0.9.0

> Released: 2026-04-20

### Added
- `store.py`: `GraphStore.nodes_batch()` — batch-fetch multiple nodes in a single SQL query via temp table JOIN; eliminates N individual lookups during graph query expansion
- `store.py`: `MEMORY_RELS` tuple for memory-layer edge types (`SUPPORTS`, `ABOUT`, `REFERS_TO`, `INVOLVES`, `DESCRIBES`, `SUPERSEDES`, `DERIVED_FROM`)
- `store.py`: Composite indexes `idx_edges_src_rel` and `idx_edges_dst_rel` for faster edge traversal
- `kg.py`: `_short_chunk_boost()` — ranking boost for short factual chunks (< 200 chars) to surface single-sentence asides that are diluted in longer chunks
- `relations.py`: `_VALUE_PATTERNS` — regex patterns for percentages, currency amounts, color phrases, and occupational role phrases; `extract_entities()` now captures these in addition to titlecase proper nouns
- `dockg.py`, `graph.py`, `kg.py`: `chunk_strategy` (`"semantic"` | `"sentence_group"` | `"fixed"`) and `sentences_per_chunk` parameters propagated through `DocKG` → `DocGraph` → `parse_corpus()`; uses new `chunker_for()` factory
- `benchmarks/build_dockg.py`: `--chunk-strategy` and `--sentences-per-chunk` CLI arguments for `build_kg()`
- `benchmarks/longmemeval_dockg.py`: `_normalize_question()` — deterministic regex pre-processing that strips interrogative framing (`"What degree did I graduate with?"` → `"degree graduate with"`) to bring embeddings closer to answer text; applied before each query
- `cmd_snapshot.py`: `dockg snapshot prune` command — removes vestigial snapshots (metric-duplicates, broken manifest entries, orphaned JSON files) while always preserving the oldest and newest; supports `--dry-run`
- `snapshots.py`: Re-export `PruneResult` from `kg_snapshot.snapshots` in the public API
- `.mcp.json`: MCP server configuration (copilot-memory, skills-copilot, task-copilot, pycodekg, dockg) now tracked in git; `.gitignore` un-ignored it and added `.agentkg/` to ignored paths
- `pyproject.toml`: `kgdeps` optional group with `pycode-kg`, `ftree-kg`, `agent-kg` (moved out of dev group); `detect-secrets` and `pdoc` added to dev deps; `testpypi` source added
- `pyproject.toml`: `[tool.poe.tasks.docs]` task for generating API docs with pdoc
- `.claude/settings.json`: Agent-kg `UserPromptSubmit` and `Stop` hooks for automatic conversation ingestion
- `settings.json.template`: Claude Code hooks template for agent-kg conversation ingestion — captures `UserPromptSubmit` and `Stop` events to the local agent-kg store asynchronously
- `PipelineConfig.sampling_strategy`: configurable Phase 1 sampling strategy (default `"diversity"`); was previously hardcoded — now wired through from the `--sampling` CLI option in `pipeline_run`
- `scripts/generate_wiki.py`: Script to generate and publish GitHub wiki pages from `docs/` markdown files
- `poetry.toml`: `in-project = true` Poetry virtualenv configuration
- `src/doc_kg/__init__.py`: Package-level `__init__` exporting `DocKG` for cleaner imports
- `cli/cmd_model.py`: `dockg download-model` command to download and cache embedding models for offline use; supports `--force` re-download and `trust_remote_code` for `nomic-ai/*` models
- `pyproject.toml`: `einops` dependency added (required by `nomic-embed-text-v1`)
- `generate_wiki.py`: Wiki generation script added to project root
- `analysis/doc_kg_analysis_20260320.md`: DocKG architectural analysis report (2026-03-20)

### Changed
- `store.py`: `GraphStore.expand()` now uses batched SQL per hop (temp table + UNION) instead of per-node queries; frontier capped at `max_frontier=5000` to prevent explosive expansion through hub nodes; `CO_OCCURS_WITH` removed from `DEFAULT_RELS` (moved to `MEMORY_RELS` conceptually; excluded from document-layer defaults due to ~8M edges causing query slowdowns)
- `kg.py`: `DocKG.query()` and `DocKG.pack()` switched to `nodes_batch()` for node materialisation; edge fetch in `query()` is now conditional (`len(all_ids) <= max_nodes * 10`) to skip expensive JOINs on large corpora; ranking key now includes `short_boost`
- `kg.py`: `DocKG.query()` and `DocKG.pack()` ranking key switched to score-first ordering (`base_dist` → `best_hop` → boosts → kind → id), backported from MemoryKG where this change yielded +8.8 pp R@5 on LongMemEval benchmarks
- `dockg.py`, `graph.py`, `kg.py`: `emit_cooccur` default changed from `True` to `False` — CO_OCCURS_WITH is noisy and dense; semantic memory should use MemoryKG instead
- `benchmarks/longmemeval_dockg.py`: `query_sessions()` return type changed from `list[SessionHit]` to `tuple[list[SessionHit], QueryResult]` to expose raw result diagnostics; default `--hop` reduced from 2 to 1; default `--rels` now excludes `CO_OCCURS_WITH` to prevent explosive expansion; per-query diagnostics printed (seeds, expanded, returned nodes, query time)
- `.codekg/` → `.pycodekg/`: Renamed CodeKG snapshot and artifact directory from `.codekg/` to `.pycodekg/` to distinguish from DocKG (`.dockg/`); `.gitignore` updated to reflect new path; existing snapshot migrated
- `pyproject.toml`: `kg-snapshot` dependency switched from git source to TestPyPI published package (`>=0.3.0`); pylint config refactored to opt-in only; mypy upgraded to Python 3.13; ruff `E501` suppressed; `types-pyyaml` removed from dev deps
- `.dockg/snapshots/`: Pruned vestigial metric-duplicate snapshots from the repository
- `pyproject.toml`: dev group marked `optional = true`; `code-kg` dev dep replaced with `pycode-kg`; `agent-kg` dev dep added; pylint `invalid-name` and `no-member` globally suppressed
- `cli/options.py`, `cli/cmd_build.py`, `cli/cmd_query.py`, `cli/cmd_snapshot.py`: `--sqlite` and `--lancedb` options now default to `None`; commands resolve paths relative to `<repo>/.dockg/` when not supplied
- `cli/cmd_build.py`: Build output redesigned with Rich — section `Rule` headers, per-kind node counts, features listed inline; embedder model name and dimension shown in summary
- `index.py`: `SemanticIndex.build()` now shows a Rich progress bar during batch embedding; `build()` stats dict includes `model_name`
- `cli/cmd_hooks.py`: Pre-commit hook reordered — snapshot capture runs before quality checks; snapshot failure is non-fatal; skip env var renamed to `DOCKG_SKIP_SNAPSHOT`
- `cli/main.py`: Registered `cmd_model` subcommand; updated usage docstring
- `index.py`: `SentenceTransformerEmbedder.__init__` suppresses HF logging, wraps model load with `TQDM_DISABLE=1`, passes `trust_remote_code=True` for `nomic-ai/*` models
- `analysis/CodeKG_Agent_instructions.md` renamed to `analysis/DocKG_Agent_instructions.md`
- `pyproject.toml`: `kg-snapshot` switched from local path to published git source; `kg-rag` dev dependency removed
- `src/doc_kg/snapshots.py`: Updated docstring module references from `kg_rag.snapshots` to `kg_snapshot.snapshots`
- `sentence-transformers` pinned to `^5.4.1` (was `>=2.7.0`) to align with pycode-kg and ensure `get_embedding_dimension()` API is always available

### Fixed
- `cmd_pipeline.py`: Cast `strategy: str` to `Literal["sentence_group", "semantic"]` for `PipelineConfig.chunk_strategy`
- `topics.py`: Added `# type: ignore[import-untyped]` on `import yaml`; initialized `self._kmeans` and `self._cluster_labels` in `__init__`; renamed `X` → `embeddings_arr`
- `snapshots.py`: Added Author/License/Last Revision docstring header
- `pipeline.py`: Added `TYPE_CHECKING` guard import for `SentenceTransformerEmbedder`; moved `if TYPE_CHECKING:` block after regular imports
- `sampler.py`: Renamed ML matrix variables `X` / `X_scaled` → `features_arr` / `features_scaled`
- `embedder_worker.py`: Added missing docstring to `n_vectors` property
- `cmd_pipeline.py`: Wired `sampling` CLI arg into `PipelineConfig`
- `tests/test_snapshots.py`: Fixed three failing snapshot tests by passing distinct `nodes=` counts to work around `save_snapshot` deduplication
- `dockg.py`: Changed `DEFAULT_MODEL` from `all-mpnet-base-v2` to `nomic-ai/nomic-embed-text-v1`; fixed HuggingFace 404 error

---

_Full changelog: [CHANGELOG.md](CHANGELOG.md)_
