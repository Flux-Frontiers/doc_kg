DocKG — Command Workflow
===

Document-centric knowledge graph building and querying.

## Build the Graph

```bash
dockg build docs --wipe
```

Build the authoritative SQLite knowledge graph from your documentation corpus (`.md` and `.txt` files).
This runs corpus parsing, SQLite persistence, and LanceDB vector indexing in one step.

**Granular steps (for large corpora):**

```bash
# Step 1 — parse corpus and write SQLite graph
dockg build-graph docs --wipe

# Step 2 — build LanceDB vector index from existing SQLite
dockg build-index --wipe
```

## Query the Graph

```bash
dockg query "authentication flow JWT tokens" --top 8
```

Run a hybrid semantic + graph query to retrieve structurally related document chunks and topics.

Returns a summary of ranked nodes and relationships.

## Extract and Read

```bash
dockg pack "authentication flow JWT tokens" --top 8
```

Execute the query and emit a ranked, deduplicated, excerpt pack in Markdown.

Returns actual document text with file paths and context.

## Analyze Coverage

```bash
dockg analyze docs
```

Full corpus analysis:
- Topic coverage across documents
- Entity density and mentions
- Orphaned sections (unreferenced content)
- Semantic clustering statistics

## Visualize the Graph

```bash
dockg viz
```

Launch Streamlit graph visualizer (PyVis network).
Shows documents, sections, topics, entities, and their relationships interactively.

## Manage Snapshots

```bash
dockg snapshot save "v0.2.0"
```

Capture current metrics snapshot (commit, branch, version).

```bash
dockg snapshot list
```

List all snapshots in reverse chronological order.

```bash
dockg snapshot show abc1234
```

Full details for a snapshot (by commit hash).

```bash
dockg snapshot diff abc1234 def5678
```

Compare two snapshots side-by-side.

## MCP Server

```bash
dockg mcp --repo /absolute/path/to/repo
```

Start the MCP server (stdio transport) for use with Claude Code, GitHub Copilot, or other MCP clients.

## Workflow Example

```bash
# 1. Build the graph from documentation
dockg build docs --wipe

# 2. Analyze coverage before publishing
dockg analyze docs

# 3. Explore topics interactively
dockg viz

# 4. Query for specific content
dockg query "API authentication methods"

# 5. Extract markdown pack for a topic
dockg pack "error handling patterns" --top 5

# 6. Capture a snapshot at a milestone
dockg snapshot save "documentation-v1.0"

# 7. Start MCP server for IDE integration
dockg mcp --repo .
```
