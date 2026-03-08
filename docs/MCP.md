# DocKG MCP Setup Guide

Integrating DocKG with MCP-compatible agents (Claude Code, GitHub Copilot, Claude Desktop, Cursor, Continue).

## Overview

DocKG includes an MCP server exposed by:

- `dockg mcp`
- `dockg-mcp`

Once configured, agents get these tools:

- `graph_stats()`
- `query_docs(q, k, hop, rels, max_nodes)`
- `pack_docs(q, k, hop, rels, max_chars, max_nodes)`
- `get_node(node_id)`

## Quick Start

1. Build the DocKG graph artifacts.
2. Add MCP config for your client.
3. Restart the client.

```bash
# From repo root
dockg build docs --wipe

# Or build any corpus directory
# dockg build /absolute/path/to/corpus --wipe
```

## Start Server Manually

```bash
dockg mcp --repo /absolute/path/to/repo
```

Equivalent:

```bash
dockg-mcp --repo /absolute/path/to/repo
```

Optional flags:

- `--db .dockg/graph.sqlite`
- `--lancedb .dockg/lancedb`
- `--model all-mpnet-base-v2`
- `--transport stdio|sse`

## Claude Code Or Kilo Code (.mcp.json)

Create `.mcp.json` in project root:

```json
{
  "mcpServers": {
    "dockg": {
      "command": "/absolute/path/to/repo/.venv/bin/dockg",
      "args": [
        "mcp",
        "--repo",
        "/absolute/path/to/repo",
        "--db",
        "/absolute/path/to/repo/.dockg/graph.sqlite",
        "--lancedb",
        "/absolute/path/to/repo/.dockg/lancedb"
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
      "command": "/absolute/path/to/repo/.venv/bin/dockg",
      "args": [
        "mcp",
        "--repo",
        "/absolute/path/to/repo",
        "--db",
        "/absolute/path/to/repo/.dockg/graph.sqlite",
        "--lancedb",
        "/absolute/path/to/repo/.dockg/lancedb"
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
      "command": "/absolute/path/to/repo/.venv/bin/dockg",
      "args": [
        "mcp",
        "--repo",
        "/absolute/path/to/repo",
        "--db",
        "/absolute/path/to/repo/.dockg/graph.sqlite",
        "--lancedb",
        "/absolute/path/to/repo/.dockg/lancedb"
      ]
    }
  }
}
```

## Tool Semantics

- `graph_stats()`
Returns node and edge totals and breakdowns by kind and relation.

- `query_docs(...)`
Hybrid semantic and graph expansion query. Returns JSON.

- `pack_docs(...)`
Same hybrid retrieval, returns a Markdown context pack.

- `get_node(node_id)`
Returns one node record as JSON.

## Troubleshooting

- `mcp package not found`
Install dependencies in the active environment (`poetry install`) and retry.

- `SQLite database not found`
Run `dockg build <corpus_root>` first.

- No tools visible in client
Verify absolute paths in MCP config and restart the client.

- Wrong corpus queried
Ensure `--repo`, `--db`, and `--lancedb` all point to the same repository.
