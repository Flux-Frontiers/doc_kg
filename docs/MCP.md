# DocKG MCP Setup Guide

Integrating DocKG with MCP-compatible agents (Claude Code, GitHub Copilot, Claude Desktop, Cursor, Continue).

## Overview

DocKG includes an MCP server exposed by:

- `dockg mcp`
- `dockg-mcp`

Once configured, agents get the fleet's five canonical tools, under the same
names as every other KG server built on `kg_utils.mcp`:

- `stats()`
- `query(q, k, hop, max_nodes, rels)`
- `pack(q, k, hop, max_nodes, rels, max_chars, traced)`
- `get_node(node_id)`
- `neighbors(node_id, rels, direction, limit)`

The list is generated, not kept by hand: `dockg mcp --manifest` prints it as
JSON without opening the graph.

## Quick Start

1. Build the DocKG graph artifacts.
2. Add MCP config for your client.
3. Restart the client.

```bash
# From repo root (wipe is the default)
dockg build docs

# Or build any corpus directory
# dockg build /absolute/path/to/corpus

# Exclude specific directories during build
# dockg build docs --exclude-dir archive --exclude-dir vendor

# Incremental update — keep existing data
# dockg build docs --update
```

## Start Server Manually

```bash
dockg mcp --repo /absolute/path/to/repo
```

Equivalent:

```bash
dockg-mcp --repo /absolute/path/to/repo
```

Optional flags (the standard set every fleet server takes):

- `--db .dockg/graph.sqlite`
- `--vectors .dockg/vectors.sqlite`
- `--model all-mpnet-base-v2`
- `--transport stdio|streamable-http` (with `--host` / `--port` for HTTP)
- `--manifest` — print the tool list as JSON and exit

A relative `--db` or `--vectors` is taken from `--repo`. On startup each
session prints the store it is actually serving to stderr, and a corpus with
no graph is refused rather than served empty.

## Claude Code Or Kilo Code (.mcp.json)

Create `.mcp.json` in project root. `dockg` here is the globally installed
tool (`uv tool install doc-kg`), resolved from `PATH`; it is not a path into
any repo's `.venv`:

```json
{
  "mcpServers": {
    "dockg": {
      "command": "dockg",
      "args": [
        "mcp",
        "--repo",
        "/absolute/path/to/repo",
        "--db",
        "/absolute/path/to/repo/.dockg/graph.sqlite",
        "--vectors",
        "/absolute/path/to/repo/.dockg/vectors.sqlite"
      ]
    }
  }
}
```

## GitHub Copilot (.vscode/mcp.json)

Create `.vscode/mcp.json`:

```json
{
  "servers": {
    "dockg": {
      "type": "stdio",
      "command": "dockg",
      "args": [
        "mcp",
        "--repo",
        "/absolute/path/to/repo",
        "--db",
        "/absolute/path/to/repo/.dockg/graph.sqlite",
        "--vectors",
        "/absolute/path/to/repo/.dockg/vectors.sqlite"
      ]
    }
  }
}
```

## Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "dockg": {
      "command": "dockg",
      "args": [
        "mcp",
        "--repo",
        "/absolute/path/to/repo",
        "--db",
        "/absolute/path/to/repo/.dockg/graph.sqlite",
        "--vectors",
        "/absolute/path/to/repo/.dockg/vectors.sqlite"
      ]
    }
  }
}
```

## Excluding Directories from Indexing

By default, DocKG skips common directories (`.git`, `.venv`, `__pycache__`, `.dockg`, etc.). To exclude additional directories:

**Configuration (`pyproject.toml`, persistent — recommended):**

```toml
[tool.dockg]
exclude = ["archive", "vendor", "generated"]
```

**CLI flags (per-command override):**

```bash
dockg build docs --exclude-dir archive --exclude-dir vendor
dockg build-graph docs --exclude-dir node_modules
```

Both options are additive — CLI flags extend `pyproject.toml` excludes. Excluded directory names are matched at every depth in the file walk.

## Tool Semantics

- `stats()`
Returns node and edge totals and breakdowns by kind and relation.

- `query(...)`
Hybrid search: dense and keyword (BM25) seeds, then graph expansion. Returns
JSON. `rels` is a list, e.g. `["HAS_TOPIC", "SIMILAR_TO"]`; omit it for every
relation.

- `pack(...)`
Same hybrid retrieval, returns a Markdown context pack. `max_chars` caps each
excerpt; `traced=true` attaches the provenance path that retrieved it.

- `get_node(node_id)`
Returns one node record as JSON.

- `neighbors(node_id, rels, direction, limit)`
The edges touching one node and the nodes at their other ends. Graph only; no
model is loaded.

## Troubleshooting

- `mcp package not found`
Install dependencies in the active environment (`poetry install`) and retry.

- `no graph at ...`
Run `dockg build <corpus_root>` first.

- `no such option: --vectors-path` / `--lancedb`
Rename the flag to `--vectors` in the MCP config (doc-kg 0.29.0).

- No tools visible in client
Verify absolute paths in MCP config and restart the client.

- Wrong corpus queried
Ensure `--repo`, `--db`, and `--vectors` all point to the same repository.
