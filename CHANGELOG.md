# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

### Changed

### Removed

### Fixed

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
