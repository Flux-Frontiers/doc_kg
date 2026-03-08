# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
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
- `docs/MCP.md` rewritten as a DocKG-specific MCP setup guide covering all supported clients
- `src/doc_kg/cli/main.py`: registers `cmd_analyze`, `cmd_mcp`, `cmd_viz` subcommands
- `src/doc_kg/cli/cmd_build.py`: extended with `build-graph` and `build-index` split commands
- `README.md`: added MCP Quickstart section
- `analysis/doc_kg_analysis_20260308.md`: replaced with fresh DocKG-native analysis (1 537 nodes, 8 358 edges; 97.4% topic coverage)

### Removed

### Fixed

## [0.1.0] - 2026-03-08

### Added
- Initial DocKG implementation — document knowledge graph from `.md` / `.txt` files
- `dockg build`, `dockg query`, `dockg pack` CLI commands
- Hybrid semantic + structural graph (SQLite + LanceDB)
- Default embedding model: `all-mpnet-base-v2`

### Changed

### Removed

### Fixed
