[![CI](https://github.com/Flux-Frontiers/doc_kg/actions/workflows/publish.yml/badge.svg)](https://github.com/Flux-Frontiers/doc_kg/actions/workflows/publish.yml)
[![Python](https://img.shields.io/badge/python-3.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![License: Elastic-2.0](https://img.shields.io/badge/License-Elastic%202.0-blue.svg)](https://www.elastic.co/licensing/elastic-license)
[![Version](https://img.shields.io/badge/version-0.12.3-blue.svg)](https://github.com/Flux-Frontiers/doc_kg/releases)
[![Poetry](https://img.shields.io/endpoint?url=https://python-poetry.org/badge/v0.json)](https://python-poetry.org/)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.19770973.svg)](https://doi.org/10.5281/zenodo.19770973)

**DocKG** — A Hybrid Knowledge Graph for Document Corpora
with Semantic Indexing and Source-Grounded Passage Packing

*Author: Eric G. Suchanek, PhD*
*Flux-Frontiers, Liberty TWP, OH*

---

## Overview

DocKG constructs a **deterministic, explainable knowledge graph** from a corpus of Markdown, plain-text, and PDF documents. It semantically chunks text, discovers structural and semantic relationships between sections and chunks, stores them in SQLite, and augments retrieval with vector embeddings via LanceDB.

Structure is treated as **ground truth**; semantic search is strictly an acceleration layer. The result is a searchable, auditable representation of a document corpus — an ideal retrieval engine for LLMs and a practical foundation for **Knowledge-Graph RAG (KRAG)**.

DocKG uses the same architecture as [CodeKG](https://github.com/Flux-Frontiers/code_kg) but targets natural-language documents rather than Python source code.

---

## Features

- **Multi-format ingestion** — `.md`, `.txt`, `.rst`, and `.pdf` (native — no inference)
- **Semantic chunking** — Heading-structure and paragraph-aware segmentation
- **Deterministic knowledge graph** — SQLite-backed canonical store with typed nodes and provenance-tracked edges
- **Relation extraction** — Topics, named entities, and keywords per chunk; co-occurrence and similarity edges built automatically
- **Hybrid query model** — Semantic seeding (LanceDB embeddings) + structural expansion (graph traversal)
- **Passage packing** — Context-rich text passages grounded to source documents with headings
- **Corpus health analysis** — Per-document metrics, hot chunks, orphan detection, coverage report
- **Temporal snapshots** — Save and diff graph metrics over time
- **MCP server** — Four tools for AI agent integration (`graph_stats`, `query_docs`, `pack_docs`, `get_node`)
- **Streamlit web app** — Interactive graph browser, hybrid query UI, and passage pack explorer

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

## Installation

**Requirements:** Python ≥ 3.12, < 3.14

```bash
# pip
pip install doc-kg

# With Streamlit web visualizer
pip install 'doc-kg[viz]'

# Poetry
poetry add doc-kg
```

> For advanced deployment options (Streamlit Cloud, Fly.io, offline model cache, git hooks) see [docs/deployment.md](docs/deployment.md).

---

## Usage

### Build and query

```bash
dockg build docs/                                    # full pipeline
dockg build docs/ --update                           # incremental (keep existing)
dockg build docs/ --exclude-dir archive              # skip directories
dockg query "deployment configuration"               # hybrid search
dockg pack "error handling" --format md --out ctx.md # passage pack
```

### Analyze corpus health

```bash
dockg analyze docs/             # full report + JSON snapshot
dockg analyze docs/ --quiet     # CI mode — exits 1 on issues
```

### Snapshots

```bash
dockg snapshot save 0.12.0      # capture current metrics
dockg snapshot diff 0.11.0 0.12.0  # compare two versions
```

> Full flag reference for every command: [docs/CLI.md](docs/CLI.md)
> Query patterns and MCP examples: [docs/CHEATSHEET.md](docs/CHEATSHEET.md)

---

## MCP Integration

Start the MCP server, then wire it into your AI agent:

```bash
dockg mcp --repo docs/
```

**Claude Code / Kilo Code** — add to `.mcp.json`:

```json
{
  "mcpServers": {
    "dockg": { "command": "dockg-mcp", "args": ["--repo", "."] }
  }
}
```

**GitHub Copilot** — add to `.vscode/mcp.json`:

```json
{
  "servers": {
    "dockg": { "type": "stdio", "command": "dockg-mcp", "args": ["--repo", "."] }
  }
}
```

| Tool | Description |
|------|-------------|
| `graph_stats()` | Node and edge counts by kind |
| `query_docs(q, k, hop)` | Hybrid semantic + structural search |
| `pack_docs(q, k, hop)` | Source-grounded passages as Markdown |
| `get_node(node_id)` | Fetch a single node by ID |

> Full provider setup (Claude Desktop, Cline, SSE transport): [docs/MCP.md](docs/MCP.md)

---

## Python API

```python
from doc_kg import DocKG

kg = DocKG(corpus_root="docs/")
kg.build(wipe=True)

result = kg.query("deployment configuration", k=8, hop=1)
for node in result.nodes:
    print(node["id"], node["name"])

pack = kg.pack("authentication flow")
pack.save("context.md")
```

---

## Knowledge Graph Schema

### Node kinds

| Kind       | Description                                         |
|------------|-----------------------------------------------------|
| `document` | A source `.md`, `.txt`, or `.pdf` file              |
| `section`  | A heading-delimited region within a document        |
| `chunk`    | A semantically coherent text passage                |
| `topic`    | A topic extracted from chunk text                   |
| `entity`   | A named entity (person, place, org, concept)        |
| `keyword`  | A keyword or key phrase                             |

### Edge types

| Type               | Description                                          |
|--------------------|------------------------------------------------------|
| `CONTAINS`         | Parent → child (document→section, section→chunk)     |
| `NEXT`             | Sequential ordering between same-level nodes         |
| `REFERENCES`       | Chunk references another document or section         |
| `SIMILAR_TO`       | Semantic similarity between chunks (LanceDB-derived) |
| `HAS_TOPIC`        | Chunk → topic                                        |
| `MENTIONS_ENTITY`  | Chunk → named entity                                 |
| `HAS_KEYWORD`      | Chunk → keyword                                      |
| `CO_OCCURS_WITH`   | Co-occurrence between topics/entities within a chunk |

---

## Storage Layout

```
.dockg/
  graph.sqlite      # SQLite knowledge graph (nodes + edges)
  lancedb/          # LanceDB vector index
  snapshots/        # Temporal metric snapshots (JSON)
    manifest.json
    <commit>.json
```

---

## Citation

If you use DocKG in research or a project, please cite it:

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.19770973.svg)](https://doi.org/10.5281/zenodo.19770973)

**APA**

> Suchanek, E. G. (2026). *DocKG: Hybrid Knowledge Graph for Document Corpora* (Version 0.12.1) [Software]. Flux-Frontiers. https://doi.org/10.5281/zenodo.19770973

**BibTeX**

```bibtex
@software{suchanek_doc_kg,
  author    = {Suchanek, Eric G.},
  title     = {{DocKG}: Hybrid Knowledge Graph for Document Corpora},
  version   = {0.12.1},
  year      = {2026},
  publisher = {Flux-Frontiers},
  url       = {https://github.com/Flux-Frontiers/doc_kg},
  doi       = {10.5281/zenodo.19770973},
}
```

## License

[Elastic License 2.0](LICENSE) — free for non-commercial and internal use; commercial redistribution requires a license from Flux-Frontiers.
