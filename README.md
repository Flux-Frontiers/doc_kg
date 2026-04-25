[![CI](https://github.com/Flux-Frontiers/doc_kg/actions/workflows/publish.yml/badge.svg)](https://github.com/Flux-Frontiers/doc_kg/actions/workflows/publish.yml)
[![Python](https://img.shields.io/badge/python-3.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![License: Elastic-2.0](https://img.shields.io/badge/License-Elastic%202.0-blue.svg)](https://www.elastic.co/licensing/elastic-license)
[![Version](https://img.shields.io/badge/version-0.12.0-blue.svg)](https://github.com/Flux-Frontiers/doc_kg/releases)
[![Poetry](https://img.shields.io/endpoint?url=https://python-poetry.org/badge/v0.json)](https://python-poetry.org/)
[![DOI](https://zenodo.org/badge/1176162360.svg)](https://zenodo.org/badge/latestdoi/1176162360)

**DocKG** — A Hybrid Knowledge Graph for Document Corpora
with Semantic Indexing and Source-Grounded Passage Packing

*Author: Eric G. Suchanek, PhD*
*Flux-Frontiers, Liberty TWP, OH*

---

## Overview

DocKG constructs a **deterministic, explainable knowledge graph** from a corpus of Markdown and plain-text documents. It semantically chunks text, discovers structural and semantic relationships between sections and chunks, stores them in SQLite, and augments retrieval with vector embeddings via LanceDB.

Structure is treated as **ground truth**; semantic search is strictly an acceleration layer. The result is a searchable, auditable representation of a document corpus that supports precise navigation, contextual passage extraction, and downstream reasoning — making it an ideal retrieval engine for LLMs and a practical foundation for **Knowledge-Graph RAG (KRAG)**, in contrast to embedding-only approaches.

DocKG uses the same architecture as [CodeKG](https://github.com/Flux-Frontiers/code_kg) but targets natural-language documents rather than Python source code.

---

## Features

- **Semantic chunking** — Splits `.md` and `.txt` files into semantically coherent chunks by heading and paragraph structure
- **Deterministic knowledge graph** — SQLite-backed canonical store with typed nodes and provenance-tracked edges
- **Relation extraction** — Topics, named entities, and keywords extracted from each chunk; co-occurrence and similarity edges built automatically
- **Hybrid query model** — Semantic seeding (LanceDB embeddings) + structural expansion (graph traversal)
- **Passage packing** — Extract context-rich text passages grounded to source documents with headings
- **Semantic coverage analysis** — Per-document metrics, hot chunks, orphan detection, and overall corpus health report
- **Temporal snapshots** — Save and diff graph metrics over time; compare coverage across corpus versions
- **MCP server** — Four tools for AI agent integration (`graph_stats`, `query_docs`, `pack_docs`, `get_node`)
- **Streamlit web app** — Interactive graph browser, hybrid query UI, and passage pack explorer
- **Configurable extraction** — Toggle topic/entity/keyword extraction per build

---

## Quick Start

```bash
# Index a document corpus (SQLite + LanceDB in one step)
dockg build docs/

# Natural-language query — returns ranked document chunks
dockg query "authentication flow"

# Source-grounded passage pack — paste straight into an LLM prompt
dockg pack "configuration reference" --format md --out context.md
```

---

## Usage Examples

### Build the knowledge graph

```bash
# Full pipeline: parse documents → SQLite graph → LanceDB semantic index
dockg build docs/

# Build only the SQLite graph (no embeddings)
dockg build-graph docs/

# Build only the LanceDB index from an existing graph
dockg build-index

# Rebuild from scratch (wipe is the default)
dockg build docs/

# Incremental update — keep existing data
dockg build docs/ --update

# Exclude specific directories
dockg build docs/ --exclude-dir dir1 --exclude-dir dir2
```

### Query and pack passages

```bash
# Hybrid query — semantic seed + graph expansion
dockg query "deployment configuration"

# Increase top-K and expansion hops
dockg query "API authentication" --k 12 --hop 2

# Pack passages as Markdown for LLM context injection
dockg pack "error handling strategies" --format md --out context.md

# Pack as JSON
dockg pack "database schema" --format json
```

### Analyze corpus health

```bash
# Full analysis report (Markdown + JSON snapshot)
dockg analyze docs/

# Output to a specific file
dockg analyze docs/ --output analysis/report.md

# Quiet mode for CI — exits non-zero on issues
dockg analyze docs/ --quiet
```

### Snapshot the knowledge graph over time

```bash
# Save a snapshot tagged with a version
dockg snapshot save 0.1.0

# List all saved snapshots
dockg snapshot list

# Show detail for a specific snapshot
dockg snapshot show 0.1.0

# Diff two snapshots
dockg snapshot diff 0.1.0 0.2.0
```

### Launch the Streamlit visualizer

```bash
# Requires [viz] extra: pip install 'doc-kg[viz]'
dockg viz

# Custom port, suppress browser launch
dockg viz --port 8510 --no-browser
```

### Start the MCP server

```bash
# Serve via stdio (default — for Claude Code, Cline, Copilot)
dockg mcp --repo docs/

# Serve via SSE (for web clients)
dockg mcp --repo docs/ --transport sse
```

### Use via MCP in Claude Code / GitHub Copilot

Once the MCP server is running, your AI agent has four tools:

```
graph_stats()                        # node/edge counts by kind
query_docs("authentication flow")    # hybrid semantic + structural search
pack_docs("configuration reference") # source-grounded passages as Markdown
get_node("chunk:intro:overview")     # fetch a single node by ID
```

---

## Installation

**Requirements:** Python ≥ 3.12, < 3.14

### pip

```bash
# From PyPI (recommended)
pip install doc-kg

# With Streamlit web visualizer
pip install 'doc-kg[viz]'

# Latest from GitHub
pip install 'doc-kg @ git+https://github.com/Flux-Frontiers/doc_kg.git'
```

### Poetry (existing project)

```bash
# From PyPI
poetry add doc-kg

# With Streamlit visualizer
poetry add 'doc-kg[viz]'

# From GitHub source
poetry add 'doc-kg @ git+https://github.com/Flux-Frontiers/doc_kg.git'
```

Or declare in `pyproject.toml`:

```toml
[tool.poetry.dependencies]
doc-kg = "^0.11.0"
# or with visualizer:
doc-kg = {version = "^0.11.0", extras = ["viz"]}
```

> **Note for DocKG developers:** Clone the repo and use `poetry install -E viz` for a full local development environment including the Streamlit visualizer.

### Verify the installation

```bash
dockg --help
dockg status --repo .
```

`dockg status` shows the knowledge graph builder metadata, node/edge counts, and DB size. It exits non-zero if no graph has been built yet — useful for CI health checks.

### First build

```bash
# Build a knowledge graph from a directory of .md and .txt files
dockg build --repo /path/to/docs/

# Verify the result
dockg status --repo /path/to/docs/

# Run a query
dockg query --repo /path/to/docs/ "your search topic"
```

### Git hooks (optional)

Install a pre-commit hook that automatically captures a graph metrics snapshot before each commit:

```bash
# Via the CLI (recommended — uses the full quality-check pipeline)
dockg install-hooks

# Via the standalone script
bash scripts/install-hooks.sh

# Skip the hook for a specific commit
DOCKG_SKIP_SNAPSHOT=1 git commit -m "message"
```

### Download embedding model for offline use

The default model (`BAAI/bge-small-en-v1.5`) is fetched from HuggingFace on first use. To pre-download it for air-gapped or offline environments:

```bash
dockg download-model
# or a specific model:
dockg download-model --model BAAI/bge-small-en-v1.5
```

### AI agent integration (MCP)

After installing, wire DocKG into your AI agent by adding it as an MCP server. See [docs/MCP.md](docs/MCP.md) for the full setup guide, or run the installer script to configure all providers automatically:

```bash
# Configure Claude Code, GitHub Copilot, and Cline in one step
bash scripts/install-skill.sh

# Claude Code only
bash scripts/install-skill.sh --providers claude

# Dry-run to see what would be changed
bash scripts/install-skill.sh --dry-run
```

---

## CLI Reference

All commands are available via the unified `dockg` CLI:

```bash
dockg --help
```

Every subcommand also ships as a dedicated `dockg-<name>` script — useful for shell scripts, `Makefile` targets, and CI pipelines with no `poetry run` required.

| Script alias | Equivalent subcommand | Description |
|---|---|---|
| `dockg-build` | `dockg build` | Full pipeline: parse → SQLite → LanceDB |
| `dockg-build-graph` | `dockg build-graph` | SQLite graph only |
| `dockg-build-index` | `dockg build-index` | LanceDB index only |
| `dockg-query` | `dockg query` | Hybrid semantic + structural query |
| `dockg-pack` | `dockg pack` | Source-grounded passage extraction |
| `dockg-analyze` | `dockg analyze` | Corpus health analysis + report |
| `dockg-snapshot` | `dockg snapshot` | Save / list / show / diff snapshots |
| `dockg-viz` | `dockg viz` | Launch Streamlit visualizer |
| `dockg-mcp` | `dockg mcp` | Start MCP server |

### `dockg build` — Full pipeline

```bash
dockg build CORPUS_ROOT [--db PATH] [--lancedb PATH] [--model NAME]
            [--update] [--no-similar] [--exclude-dir DIR]...
```

| Option | Default | Description |
|---|---|---|
| `CORPUS_ROOT` | required | Root directory of documents to index |
| `--db` | `.dockg/graph.sqlite` | SQLite database path |
| `--lancedb` | `.dockg/lancedb` | LanceDB index directory |
| `--model` | `BAAI/bge-small-en-v1.5` | Sentence-transformer embedding model |
| `--update` | off | Incremental update — keep existing data instead of wiping |
| `--no-similar` | off | Skip computing `SIMILAR_TO` edges |
| `--exclude-dir` | — | Exclude a directory at every depth (repeatable); merged with `[tool.dockg].exclude` |

### `dockg build-graph` — SQLite only

```bash
dockg build-graph CORPUS_ROOT [--db PATH] [--update] [--exclude-dir DIR]...
```

Parses documents, extracts nodes (documents, sections, chunks, topics, entities, keywords), and writes the SQLite graph. No embedding model required.

| Option | Default | Description |
|---|---|---|
| `--exclude-dir` | — | Exclude a directory at every depth (repeatable); merged with `[tool.dockg].exclude` |

### `dockg build-index` — LanceDB only

```bash
dockg build-index [--db PATH] [--lancedb PATH] [--model NAME] [--no-similar]
```

Reads an existing SQLite graph and builds (or rebuilds) the LanceDB vector index. Use after `build-graph` or when reindexing with a different model.

### `dockg query` — Hybrid search

```bash
dockg query QUERY [--db PATH] [--lancedb PATH] [--k N] [--hop N] [--rels TYPES]
```

| Option | Default | Description |
|---|---|---|
| `QUERY` | required | Natural-language search string |
| `--k` | `8` | Top-K semantic seed hits |
| `--hop` | `1` | Graph expansion hops |
| `--rels` | `CONTAINS,NEXT,REFERENCES,SIMILAR_TO` | Edge types to traverse |

### `dockg pack` — Passage extraction

```bash
dockg pack QUERY [--db PATH] [--lancedb PATH] [--k N] [--hop N]
           [--format md|json] [--out PATH] [--max-chars N] [--max-nodes N]
```

| Option | Default | Description |
|---|---|---|
| `--k` | `8` | Top-K semantic seed hits |
| `--hop` | `1` | Graph expansion hops |
| `--format` | `md` | Output format: `md` or `json` |
| `--out` | stdout | Output file path |
| `--max-chars` | `12000` | Max total characters in pack |
| `--max-nodes` | `50` | Max nodes included |

### `dockg analyze` — Corpus health report

```bash
dockg analyze [CORPUS_ROOT] [--db PATH] [--lancedb PATH]
              [--output PATH] [--json] [--quiet]
```

Runs the full `DocKGAnalyzer` pipeline:

1. Baseline graph statistics (node/edge counts by kind)
2. Per-document structure metrics (sections, chunks, depth)
3. Semantic coverage (% of chunks with topic/entity/keyword annotations)
4. Orphan detection (isolated nodes with no edges)
5. Hot chunks (highest connectivity / most referenced)
6. Actionable insights and improvement suggestions

Writes a Markdown report and optionally a JSON snapshot.

### `dockg snapshot` — Temporal snapshots

```bash
dockg snapshot save VERSION   # capture current metrics
dockg snapshot list           # list all saved snapshots
dockg snapshot show COMMIT    # full detail + delta vs previous
dockg snapshot diff A B       # side-by-side comparison
```

Snapshots are stored in `.dockg/snapshots/`. Use them to track documentation coverage trends across iterations.

```bash
# Save snapshots at key milestones
dockg snapshot save 0.1.0
# ... add more docs, rebuild ...
dockg snapshot save 0.2.0

# See what changed
dockg snapshot diff 0.1.0 0.2.0
```

### `dockg viz` — Streamlit visualizer

```bash
dockg viz [--db PATH] [--port PORT] [--no-browser]
```

Launches a Streamlit web app with three tabs:

- **Graph** — Interactive pyvis graph browser with node kind / edge type filters
- **Query** — Hybrid search UI with result ranking and provenance
- **Pack** — Passage pack explorer for LLM context injection

Requires the `[viz]` extra: `pip install 'doc-kg[viz]'`.

### `dockg mcp` — MCP server

```bash
dockg mcp [--repo PATH] [--db PATH] [--lancedb PATH] [--model NAME]
          [--transport stdio|sse]
```

Starts the FastMCP server. Default transport is `stdio` for AI agent integration; use `sse` for web clients.

---

## Knowledge Graph Schema

### Node kinds

| Kind | Description |
|---|---|
| `document` | A source `.md` or `.txt` file |
| `section` | A heading-delimited section within a document |
| `chunk` | A semantically coherent text passage within a section |
| `topic` | A topic extracted from chunk text |
| `entity` | A named entity (person, place, organization, concept) |
| `keyword` | A keyword or key phrase from a chunk |

### Edge types

| Type | Description |
|---|---|
| `CONTAINS` | Parent → child (document→section, section→chunk) |
| `NEXT` | Sequential ordering between same-level nodes |
| `REFERENCES` | A chunk references another document or section |
| `SIMILAR_TO` | Semantic similarity between chunks (LanceDB-derived) |
| `HAS_TOPIC` | Chunk → topic association |
| `MENTIONS_ENTITY` | Chunk → named entity association |
| `HAS_KEYWORD` | Chunk → keyword association |
| `CO_OCCURS_WITH` | Co-occurrence between topics/entities within a chunk |

---

## MCP Integration

See [docs/MCP.md](docs/MCP.md) for the full setup guide covering Claude Code, GitHub Copilot, Claude Desktop, and Cline.

### Quick MCP setup

**Claude Code / Kilo Code** — add to `.mcp.json` in your repo root:

```json
{
  "mcpServers": {
    "dockg": {
      "command": "dockg-mcp",
      "args": ["--repo", "."]
    }
  }
}
```

**GitHub Copilot** — add to `.vscode/mcp.json`:

```json
{
  "servers": {
    "dockg": {
      "type": "stdio",
      "command": "dockg-mcp",
      "args": ["--repo", "."]
    }
  }
}
```

### MCP tools reference

| Tool | Description |
|---|---|
| `graph_stats()` | Node and edge counts by kind |
| `query_docs(q, k, hop, rels, max_nodes)` | Hybrid semantic + structural search |
| `pack_docs(q, k, hop, rels, max_chars, max_nodes)` | Source-grounded passages as Markdown |
| `get_node(node_id)` | Fetch a single node by ID |

---

## Python API

```python
from doc_kg import DocKG

kg = DocKG(corpus_root="docs/")
kg.build(wipe=True)

# Hybrid query
result = kg.query("deployment configuration", k=8, hop=1)
for node in result.nodes:
    print(node["id"], node["name"])

# Passage pack for LLM context
pack = kg.pack("authentication flow")
pack.save("context.md")
```

---

## Configuration

Add to your project's `pyproject.toml` to persist common settings:

```toml
[tool.dockg]
exclude = ["archive", "vendor", "generated"]
```

### Exclude priority order

Exclusions are **additive** across three levels:

1. **Built-in** — hardcoded in `dockg.py`: `.git`, `.venv`, `__pycache__`, `.dockg`, `.codekg`, etc.
2. **Config** — `[tool.dockg].exclude` from `pyproject.toml` (auto-loaded from corpus root)
3. **CLI** — `--exclude-dir` flags (merged at call time)

All three are unioned—there is no override, only additive exclusion. Example:

```bash
# pyproject.toml has: exclude = ["archive", "vendor"]
# This adds to those:
dockg build docs/ --exclude-dir node_modules --exclude-dir dist
# Result: archive + vendor + node_modules + dist are all excluded (plus built-ins)
```

---

## Storage Layout

After running `dockg build`, the following files are created:

```
.dockg/
  graph.sqlite      # SQLite knowledge graph (nodes + edges)
  lancedb/          # LanceDB vector index
  snapshots/        # Temporal snapshots (JSON)
    manifest.json
    <version>.json
```

---

## Contributing

1. Fork the repository and create a feature branch
2. Install dev dependencies: `poetry install`
3. Run the test suite: `pytest`
4. Submit a pull request

```bash
# Install with viz extras for full local development
poetry install -E viz

# Run all tests
pytest

# Lint and format
ruff check src/ tests/
ruff format src/ tests/
```

---

## License

[Elastic License 2.0](LICENSE) — free for non-commercial and internal use; commercial redistribution requires a license from Flux-Frontiers.
