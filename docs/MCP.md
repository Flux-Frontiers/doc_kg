# CodeKG MCP Installation Guide

**Integrating CodeKG with Claude Code and Claude Desktop**

*Author: Eric G. Suchanek, PhD*

---

## Overview

CodeKG ships a built-in MCP server (`codekg mcp`) that exposes the full hybrid query and snippet-pack pipeline as structured tools consumable by any MCP-compatible AI agent — Claude Code, Claude Desktop, Cursor, Continue, or any custom agent that speaks the Model Context Protocol.

Once configured, the agent gains five tools:

| Tool | Purpose |
|---|---|
| `graph_stats()` | Codebase size and shape — good first call |
| `query_codebase(q)` | Semantic + structural graph exploration |
| `pack_snippets(q)` | Source-grounded code snippets for implementation detail |
| `get_node(node_id)` | Single node metadata lookup by stable ID |
| `callers(node_id, rel)` | Precise fan-in lookup — find all callers of a node, resolving through sym: stubs |

---

## Quick Start (TL;DR)

```bash
# 1. Install code-kg (MCP server is included in the standard install)
poetry add 'code-kg @ git+https://github.com/Flux-Frontiers/code_kg.git'

# 2. Build the knowledge graph
codekg build-sqlite  --repo . --db .codekg/graph.sqlite
codekg build-lancedb --sqlite .codekg/graph.sqlite

# 3. Add per-repo config for your agent (see Section 4–6)
#    • Claude Code + Kilo Code  → .mcp.json
#    • GitHub Copilot           → .vscode/mcp.json
#    • Claude Desktop           → claude_desktop_config.json (global)

# 4. Restart your agent — the codekg tools are now active
```

Or use the automated setup command inside Claude Code / Kilo Code:

```
/setup-mcp
```

---

## Bootstrap: New Machine Setup

On a **brand-new machine** the Claude skill doesn't exist yet, so Claude won't know how to help you set up CodeKG. Install the skill first with a single command — no clone required:

```bash
curl -fsSL https://raw.githubusercontent.com/Flux-Frontiers/code_kg/main/scripts/install-skill.sh | bash
```

Or, if you already have the repo cloned:

```bash
bash scripts/install-skill.sh
```

This installs `~/.claude/skills/codekg/` so that any Claude Code session (with `skills-copilot` running) will automatically have expert CodeKG knowledge available. Then proceed with the normal installation steps below.

---

## Table of Contents

1. [Installation](#1-installation)
2. [Building the Knowledge Graph](#2-building-the-knowledge-graph)
3. [Smoke-Testing the Pipeline](#3-smoke-testing-the-pipeline)
4. [Configuring Claude Code / Kilo Code](#4-configuring-claude-code--kilo-code)
5. [Configuring GitHub Copilot](#5-configuring-github-copilot)
6. [Configuring Claude Desktop](#6-configuring-claude-desktop)
7. [Configuring Cline](#7-configuring-cline)
8. [Installing the CodeKG Skill](#8-installing-the-codekg-skill)
9. [Automated Setup with `/setup-mcp`](#9-automated-setup-with-setup-mcp)
10. [Claude Copilot Integration](#10-claude-copilot-integration)
11. [Available Tools Reference](#11-available-tools-reference)
12. [Query Strategy Guide](#12-query-strategy-guide)
13. [Rebuilding After Code Changes](#13-rebuilding-after-code-changes)
14. [Troubleshooting](#14-troubleshooting)

---

## 1. Installation

### 1a. Install from GitHub (recommended until PyPI release)

In the target project's directory:

```bash
# Standard install (MCP server included — no extra needed)
poetry add 'code-kg @ git+https://github.com/Flux-Frontiers/code_kg.git'

# With 3D visualizer (optional)
poetry add 'code-kg[viz3d] @ git+https://github.com/Flux-Frontiers/code_kg.git'
```

This adds the following to your `pyproject.toml`:

```toml
[tool.poetry.dependencies]
# Standard
code-kg = {git = "https://github.com/Flux-Frontiers/code_kg.git"}

# With 3D visualizer
code-kg = {git = "https://github.com/Flux-Frontiers/code_kg.git", extras = ["viz3d"]}
```

Then run:

```bash
poetry lock && poetry install
```

### 1b. Pin to a specific commit

```toml
code-kg = { git = "https://github.com/Flux-Frontiers/code_kg.git", rev = "66d565f" }
```

### 1c. Verify the install

```bash
# Confirm the entry point is available
poetry run which codekg

# Confirm the mcp package is importable
poetry run python -c "import mcp; print('mcp OK')"
```

---

## 2. Building the Knowledge Graph

The MCP server is **read-only**. Two artifacts must be built before starting the server:

| Artifact | Built by | Contains |
|---|---|---|
| `.codekg/graph.sqlite` | `codekg build-sqlite` | AST-extracted nodes and edges |
| `.codekg/lancedb/` | `codekg build-lancedb` | Sentence-transformer vector embeddings |

### Step 1 — Static analysis: repo → SQLite

```bash
codekg build-sqlite \
  --repo /absolute/path/to/repo \
  --db   /absolute/path/to/repo/.codekg/graph.sqlite
```

Add `--wipe` to rebuild from scratch (safe to re-run):

```bash
codekg build-sqlite --repo . --db .codekg/graph.sqlite --wipe
```

**Output:** `OK: nodes=<N> edges=<M> db=.codekg/graph.sqlite`

### Step 2 — Semantic indexing: SQLite → LanceDB

> **Note:** The flag is `--sqlite`, not `--db`.

```bash
codekg build-lancedb \
  --sqlite /absolute/path/to/repo/.codekg/graph.sqlite
```

Add `--wipe` to rebuild the vector index:

```bash
codekg build-lancedb --sqlite .codekg/graph.sqlite --wipe
```

**Output:** `OK: indexed_rows=<V> dim=384 table=codekg_nodes lancedb_dir=.codekg/lancedb kinds=module,class,function,method`

Both steps are idempotent. Re-run them whenever the codebase changes significantly.

### CLI flags reference

**`codekg build-sqlite`**

| Flag | Required | Default | Description |
|---|---|---|---|
| `--repo` | ✓ | — | Repository root path |
| `--db` | ✓ | — | SQLite output path |
| `--wipe` | | false | Delete existing graph first |

**`codekg build-lancedb`**

| Flag | Required | Default | Description |
|---|---|---|---|
| `--sqlite` | ✓ | — | Path to the SQLite graph |
| `--lancedb` | | `.codekg/lancedb` | LanceDB output directory |
| `--table` | | `codekg_nodes` | LanceDB table name |
| `--model` | | `all-MiniLM-L6-v2` | Sentence-transformer model |
| `--wipe` | | false | Delete existing vectors first |
| `--kinds` | | `module,class,function,method` | Node kinds to embed |
| `--batch` | | `256` | Embedding batch size |

---

## 3. Smoke-Testing the Pipeline

Before configuring any agent, verify the full pipeline works end-to-end:

```bash
# Check graph stats
poetry run python -c "
from code_kg import CodeKG
import json
kg = CodeKG(repo_root='.', db_path='.codekg/graph.sqlite', lancedb_dir='.codekg/lancedb')
print(json.dumps(kg.stats(), indent=2))
"

# Run a sample query
codekg query "module structure"
```

Expected output from `kg.stats()`:

```json
{
  "total_nodes": 412,
  "total_edges": 1087,
  "node_counts": { "module": 18, "class": 34, "function": 201, "method": 143 },
  "edge_counts": { "CONTAINS": 378, "CALLS": 512, "IMPORTS": 147, "INHERITS": 50 },
  "db_path": ".codekg/graph.sqlite"
}
```

If this succeeds, the MCP server will work correctly.

---

## 4. Configuring Claude Code / Kilo Code

Both **Claude Code** and **Kilo Code** read MCP servers from **`.mcp.json`** in the project root — this is the canonical per-project MCP config for `codekg`.

> ⚠️ **Per-repo only.** Do NOT add `codekg` to any global settings file (Kilo Code's `mcp_settings.json` or Claude Code's `~/.claude/settings.json`). Global files are shared across all windows — hardcoded paths will point every window to the same repo.

> **Note:** If your project uses Claude Copilot, the copilot servers (`copilot-memory`, `skills-copilot`, `task-copilot`) live in `.claude/claude_code_config.json` — separate from `codekg`. See [Section 10](#10-claude-copilot-integration) for the full layout.

### 4a. Create or update `.mcp.json`

```json
{
  "mcpServers": {
    "codekg": {
      "command": "codekg-mcp",
      "args": ["--repo", "/absolute/path/to/repo"]
    }
  }
}
```

> **Always use absolute paths.** MCP clients do not inherit your shell's working directory.
>
> `--db` and `--lancedb` are optional — they default to `.codekg/graph.sqlite` and `.codekg/lancedb` relative to `--repo`.

### 4b. Merging with an existing `.mcp.json`

If you already have other MCP servers in `.mcp.json`, add `codekg` to the existing `mcpServers` object — do not overwrite other entries:

```json
{
  "mcpServers": {
    "other-server": { "...": "existing entry" },
    "codekg": {
      "command": "codekg-mcp",
      "args": ["--repo", "/absolute/path/to/repo"]
    }
  }
}
```

### 4c. Activate

Restart Claude Code / reload the Kilo Code MCP panel. The `codekg` server will appear in the MCP tools list.

---

## 5. Configuring GitHub Copilot

GitHub Copilot in VS Code reads MCP servers from `.vscode/mcp.json` in the **workspace root**. Note the key differences from `.mcp.json`:

- Uses `"servers"` (not `"mcpServers"`)
- Requires `"type": "stdio"` for local process servers
- Can be committed to source control to share the config with your team

### 5a. Create or update `.vscode/mcp.json`

```json
{
  "servers": {
    "codekg": {
      "type": "stdio",
      "command": "codekg",
      "args": [
        "mcp",
        "--repo", "/absolute/path/to/repo",
        "--db",   "/absolute/path/to/repo/.codekg/graph.sqlite"
      ],
      "env": {
        "POETRY_VIRTUALENVS_IN_PROJECT": "false"
      }
    }
  }
}
```

### 5b. Activate

After saving, VS Code will display a prompt to **Trust** the MCP server — click Trust to activate it. The `codekg` tools will then be available in GitHub Copilot Chat.

---

## 6. Configuring Claude Desktop

Claude Desktop does not have Poetry on its PATH, so you must use the **absolute path to the venv binary**.

### 6a. Find the venv binary path

```bash
# In the project directory
poetry env info --path
# → /Users/you/Library/Caches/pypoetry/virtualenvs/my-project-abc123-py3.11
```

The `codekg` binary is at `<venv_path>/bin/codekg`.

### 6b. Edit `claude_desktop_config.json`

| OS | Config path |
|---|---|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |

Add the `codekg` entry:

```json
{
  "mcpServers": {
    "codekg": {
      "command": "/Users/you/Library/Caches/pypoetry/virtualenvs/my-project-abc123-py3.11/bin/codekg",
      "args": [
        "mcp",
        "--repo", "/absolute/path/to/repo",
        "--db",   "/absolute/path/to/repo/.codekg/graph.sqlite"
      ]
    }
  }
}
```

### 6c. Activate

Restart Claude Desktop. The `codekg` server will appear in the tool panel.

---

## 7. Configuring Cline

> ⚠️ **Cline does NOT support per-repo MCP config.** Its settings file is global and shared across all VS Code windows.

### Options

**Option A — Use Kilo Code instead** (recommended): Kilo Code is a drop-in replacement for Cline that supports per-repo `.mcp.json`. Switch to Kilo Code and follow Section 4.

**Option B — Named entry per repo**: Add a uniquely-named entry to Cline's global settings file and toggle it via the Cline MCP panel when switching repos.

Config path (macOS):
```
~/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json
```

Add a repo-specific named entry:

```json
{
  "mcpServers": {
    "codekg-myproject": {
      "command": "/path/to/venv/bin/codekg",
      "args": [
        "mcp",
        "--repo", "/absolute/path/to/myproject",
        "--db",   "/absolute/path/to/myproject/.codekg/graph.sqlite"
      ]
    }
  }
}
```

Use the absolute venv binary path (from `poetry env info --path`) — Cline does not have Poetry on its PATH.

---

## 8. Installing the CodeKG Skill

The CodeKG skill gives AI agents expert knowledge about CodeKG installation and usage. It must be installed to the correct directory for each agent type.

| Agent | Skill directory |
|---|---|
| **Claude Code** | `~/.claude/skills/codekg/` (served by `skills-copilot` MCP server) |
| **Kilo Code** | `~/.kilocode/skills/codekg/` |
| **Other agents** | `~/.agents/skills/codekg/` |

### Install to all locations at once (recommended)

```bash
# From the code_kg repo root
bash scripts/install-skill.sh

# Or without cloning (one-liner)
curl -fsSL https://raw.githubusercontent.com/Flux-Frontiers/code_kg/main/scripts/install-skill.sh | bash
```

The script installs `SKILL.md` and `references/installation.md` to all three skill directories and generates the appropriate MCP config files in the current project directory:
- `.mcp.json` (Claude Code + Kilo Code — contains the `codekg` entry)
- `.vscode/mcp.json` (GitHub Copilot)

### Manual install

```bash
# Claude Code
mkdir -p ~/.claude/skills/codekg/references
cp .claude/skills/codekg/SKILL.md ~/.claude/skills/codekg/SKILL.md
cp .claude/skills/codekg/references/installation.md ~/.claude/skills/codekg/references/installation.md

# Kilo Code
mkdir -p ~/.kilocode/skills/codekg/references
cp .claude/skills/codekg/SKILL.md ~/.kilocode/skills/codekg/SKILL.md
cp .claude/skills/codekg/references/installation.md ~/.kilocode/skills/codekg/references/installation.md
```

After installing for Kilo Code, reload VS Code (`Cmd+Shift+P` → **Developer: Reload Window**) to pick up the new skill.

---

## 9. Automated Setup with `/setup-mcp`


If your project uses **Claude Copilot**, the `/setup-mcp` command automates the entire installation and configuration process.

### Usage

```
/setup-mcp                        # Interactive — prompts for repo path
/setup-mcp /path/to/repo          # Non-interactive — uses provided path
```

### What it does

The command runs six steps automatically:

| Step | Action |
|---|---|
| 0 | Resolves the target repository path and verifies Python files exist |
| 1 | Verifies `codekg mcp` is installed; installs `code-kg` if missing |
| 2 | Builds the SQLite knowledge graph (asks before wiping existing data) |
| 3 | Builds the LanceDB vector index (asks before wiping existing data) |
| 4 | Smoke-tests the full query pipeline |
| 5 | Writes/updates MCP configs: `.mcp.json` (Claude Code + Kilo Code), `.vscode/mcp.json` (GitHub Copilot), `claude_desktop_config.json` (Claude Desktop) |
| 6 | Prints a final summary with node/edge/vector counts and next steps |

### Example output

```
✓ Repository indexed:    /path/to/repo
✓ SQLite graph:          /path/to/repo/.codekg/graph.sqlite  (412 nodes, 1087 edges)
✓ LanceDB index:         /path/to/repo/.codekg/lancedb  (378 vectors)
✓ Smoke test:            passed
✓ Claude Code config:    /path/to/repo/.mcp.json
✓ Claude Desktop config: ~/Library/Application Support/Claude/claude_desktop_config.json

Restart Claude Code / Claude Desktop to activate the codekg MCP server.

Available tools once active:
  • graph_stats()          — codebase size and shape
  • query_codebase(q)      — semantic + structural exploration
  • pack_snippets(q)       — source-grounded code snippets
  • get_node(node_id)      — single node metadata lookup

Suggested first query after restart:
  graph_stats()
```

---

## 10. Claude Copilot Integration

If your project uses [Claude Copilot](https://github.com/Everyone-Needs-A-Copilot/claude-copilot), CodeKG integrates naturally with the agent framework.

### Setting up Claude Copilot in a new project

Claude Copilot provides the agent infrastructure (Memory Copilot, Task Copilot, Skills, Agents). To set it up alongside CodeKG:

```
/setup-project          # Initialize Claude Copilot
/setup-mcp              # Then set up CodeKG MCP
```

### Project structure with both installed

```
your-project/
├── .mcp.json                    ← MCP server config (codekg — read by Claude Code + Kilo Code)
├── .claude/
│   ├── claude_code_config.json  ← Claude Code MCP config (copilot servers only)
│   ├── settings.local.json      ← Claude Code settings
│   ├── agents/                  ← Agent definitions (ta, me, qa, doc, etc.)
│   ├── commands/
│   │   ├── protocol.md          ← /protocol command
│   │   ├── continue.md          ← /continue command
│   │   └── setup-mcp.md         ← /setup-mcp command
│   └── skills/                  ← Local skills (empty until populated)
├── .codekg/                     ← Knowledge graph + index (gitignored)
│   ├── graph.sqlite
│   └── lancedb/
```

### Recommended `.mcp.json`

Contains `codekg` — read by both Claude Code and Kilo Code:

```json
{
  "mcpServers": {
    "codekg": {
      "command": "codekg-mcp",
      "args": ["--repo", "/absolute/path/to/your-project"]
    }
  }
}
```

### Recommended `.claude/claude_code_config.json` with Copilot stack

Contains the Claude Copilot servers (Claude Code-specific — Kilo Code does not read this file):

```json
{
  "mcpServers": {
    "copilot-memory": {
      "command": "node",
      "args": ["/Users/you/.claude/copilot/mcp-servers/copilot-memory/dist/index.js"],
      "env": {
        "MEMORY_PATH": "/Users/you/.claude/memory",
        "WORKSPACE_ID": "your-project"
      }
    },
    "skills-copilot": {
      "command": "node",
      "args": ["/Users/you/.claude/copilot/mcp-servers/skills-copilot/dist/index.js"],
      "env": {
        "LOCAL_SKILLS_PATH": "./.claude/skills"
      }
    },
    "task-copilot": {
      "command": "node",
      "args": ["/Users/you/.claude/copilot/mcp-servers/task-copilot/dist/index.js"],
      "env": {
        "TASK_DB_PATH": "/Users/you/.claude/tasks",
        "WORKSPACE_ID": "your-project"
      }
    }
  }
}
```

### Using CodeKG tools within the Agent-First Protocol

When working under `/protocol`, agents can call CodeKG tools directly. The recommended workflow:

```
1. Start session:
   /protocol

2. Agent orientation (agent calls automatically):
   graph_stats()                          → understand codebase shape

3. Investigation (agent calls):
   query_codebase("authentication flow")  → find relevant nodes
   pack_snippets("JWT validation logic")  → read implementation

4. Implementation:
   @agent-me implements changes with full source context from pack_snippets
```

The `@agent-doc` agent is particularly well-suited to use `pack_snippets` when generating documentation — it gets accurate source-grounded snippets rather than hallucinating implementations.

---

## 11. Available Tools Reference

### `graph_stats()`

Return node and edge counts broken down by kind and relation.

**When to use:** First call in any session — understand the codebase size and shape before querying.

**Parameters:** None.

**Returns:**

```json
{
  "total_nodes": 412,
  "total_edges": 1087,
  "node_counts": {
    "module": 18, "class": 34, "function": 201, "method": 143, "symbol": 16
  },
  "edge_counts": {
    "CONTAINS": 378, "CALLS": 512, "IMPORTS": 147, "INHERITS": 50
  },
  "db_path": ".codekg/graph.sqlite"
}
```

---

### `query_codebase(q, k, hop, rels, include_symbols)`

Hybrid semantic + structural query. Returns ranked nodes and edges as JSON.

**When to use:** Exploring the graph — finding what classes, functions, and modules are relevant to a topic, understanding call relationships, tracing imports.

**Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `q` | `str` | — | Natural-language query |
| `k` | `int` | `8` | Semantic seed count (top-K from vector search) |
| `hop` | `int` | `1` | Graph expansion hops from each seed |
| `rels` | `str` | `"CONTAINS,CALLS,IMPORTS,INHERITS"` | Comma-separated edge types to follow |
| `include_symbols` | `bool` | `false` | Include low-level `sym:` nodes |

**Returns:** JSON with keys: `query`, `seeds`, `expanded_nodes`, `returned_nodes`, `hop`, `rels`, `nodes`, `edges`.

---

### `pack_snippets(q, k, hop, rels, include_symbols, context, max_lines, max_nodes)`

Hybrid query + source-grounded snippet extraction. Returns a Markdown context pack.

**When to use:** Any time you need to read actual source code — understanding an implementation, debugging, writing tests, reviewing logic. **Prefer this over `query_codebase` when implementation details matter.**

**Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `q` | `str` | — | Natural-language query |
| `k` | `int` | `8` | Semantic seed count |
| `hop` | `int` | `1` | Graph expansion hops |
| `rels` | `str` | `"CONTAINS,CALLS,IMPORTS,INHERITS"` | Edge types to follow |
| `include_symbols` | `bool` | `false` | Include symbol nodes |
| `context` | `int` | `5` | Extra context lines around each definition |
| `max_lines` | `int` | `160` | Maximum lines per snippet block |
| `max_nodes` | `int` | `50` | Maximum nodes in the pack |

**Returns:** Markdown string with ranked, deduplicated code snippets and line numbers.

---

### `get_node(node_id)`

Fetch a single node by its stable ID.

**When to use:** You have a node ID from a previous query result and want its full metadata.

**Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `node_id` | `str` | Stable node ID, e.g. `fn:src/auth/jwt.py:JWTValidator.validate` |

**Node ID format:** `<kind>:<module_path>:<qualname>`

| Prefix | Kind |
|---|---|
| `mod:` | module |
| `cls:` | class |
| `fn:` | function / method |
| `sym:` | unresolved external symbol |

**Returns:** JSON object with all node fields, or `{"error": "Node not found: '...'"}`.

---

### `callers(node_id, rel)`

Find all callers of a specific node by inverting a relation — fan-in analysis.

**When to use:** Finding all callers of a specific function/method/class — fan-in analysis. More precise than `query_codebase` for this use case because it resolves cross-module callers through `sym:` import stubs.

**Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `node_id` | `str` | — | Stable node ID, e.g. `fn:src/auth/jwt.py:JWTValidator.validate` |
| `rel` | `str` | `"CALLS"` | Relation type to invert |

**Returns:** JSON with `node_id`, `rel`, `caller_count`, `callers` (list of node dicts).

**Example return shape:**

```json
{
  "node_id": "fn:src/code_kg/store.py:GraphStore.expand",
  "rel": "CALLS",
  "caller_count": 7,
  "callers": [
    { "id": "m:src/code_kg/kg.py:CodeKG.query", "kind": "method", ... },
    ...
  ]
}
```

> **Note:** `sym:` nodes are resolved automatically — callers from other modules that import the target function are included even when they reference it via an alias.

---

## 12. Query Strategy Guide

### Choosing `k` and `hop`

| Goal | Recommended settings |
|---|---|
| Narrow, precise lookup | `k=4, hop=0` — seeds only, no expansion |
| Standard exploration | `k=8, hop=1` — default; good for most queries |
| Broad context sweep | `k=12, hop=2` — pulls in more of the call graph |
| Deep dependency trace | `k=8, hop=2, rels="CALLS,IMPORTS"` — follow execution paths |

Higher `hop` values expand the result set geometrically. Use `max_nodes` in `pack_snippets` to keep output manageable.

### Choosing `rels`

| Relation | Meaning | When to include |
|---|---|---|
| `CONTAINS` | Module/class contains a definition | Almost always — provides structural context |
| `CALLS` | Function A calls function B | Tracing execution flow, finding callers/callees |
| `IMPORTS` | Module A imports from module B | Dependency analysis |
| `INHERITS` | Class A inherits from class B | OOP hierarchy exploration |

### Typical agent workflow

```
1. graph_stats()
   → understand codebase size and shape

2. query_codebase("authentication flow", k=8, hop=1)
   → identify relevant classes and functions, note their IDs

3. pack_snippets("JWT token validation", k=6, hop=1)
   → read the actual implementation

4. get_node("fn:src/auth/jwt.py:JWTValidator.validate")
   → fetch metadata for a specific node

5. callers("fn:src/auth/jwt.py:JWTValidator.validate")
   → find every caller, including cross-module callers via import aliases

6. pack_snippets("JWT token validation error handling", k=4, hop=2, rels="CALLS")
   → follow the call graph deeper into error paths
```

---

## 13. Rebuilding After Code Changes

When the codebase changes, rebuild both artifacts (safe to re-run, idempotent):

```bash
codekg build-sqlite  --repo . --db .codekg/graph.sqlite --wipe
codekg build-lancedb --sqlite .codekg/graph.sqlite --wipe
```

The `.mcp.json` entry does not need to change after rebuilds — it points to the same file paths.

### Gitignore recommendations

Add this to `.gitignore` to avoid committing large binary artifacts:

```gitignore
.codekg/
```

This ignores the SQLite graph, LanceDB vector index, and snapshots — all are local artifacts. Commit snapshots manually at milestones if you want git history.

---

## 14. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ERROR: 'mcp' package not found` | Package not installed correctly | `poetry add 'code-kg @ git+https://github.com/Flux-Frontiers/code_kg.git'` |
| `WARNING: SQLite database not found` | Graph not built yet | Run `codekg build-sqlite` then `codekg build-lancedb` |
| `codekg build-lancedb: error: the following arguments are required: --sqlite` | Wrong flag name | Use `--sqlite`, not `--db`, for the lancedb builder |
| Empty results from `query_codebase` | LanceDB index missing or stale | Run `codekg build-lancedb --wipe` |
| Node IDs in results don't resolve with `get_node` | Graph rebuilt since last query | Rebuild both SQLite and LanceDB |
| `RuntimeError: CodeKG not initialised` | Server called without `main()` | Always start via `codekg mcp` CLI |
| Snippets show wrong line numbers | Source files changed since build | Rebuild with `codekg build-sqlite --wipe` |
| MCP server not appearing in Claude Code | `.mcp.json` not in project root, or relative paths used | Use absolute paths; restart Claude Code |
| MCP server not appearing in Claude Desktop | Wrong binary path or relative paths | Use `poetry env info --path` to get absolute venv path |
| `codekg` command not found | Package not installed or venv not active | `poetry install` or use absolute venv path |

---

## Summary

| Concern | Answer |
|---|---|
| What does the MCP server expose? | 5 tools: `graph_stats`, `query_codebase`, `pack_snippets`, `get_node`, `callers` |
| What must exist before starting? | `.codekg/graph.sqlite` + `.codekg/lancedb/` directory |
| How do I build those? | `codekg build-sqlite` then `codekg build-lancedb --sqlite ...` |
| Is the server stateful? | Yes — one `CodeKG` instance per server process |
| Can it modify the graph? | No — strictly read-only |
| What transport should I use? | `stdio` for Claude Code / Claude Desktop; `sse` for HTTP clients |
| Which tool should I call first? | `graph_stats()` for orientation |
| How do I automate setup? | `/setup-mcp` command (requires Claude Copilot) |
