DocKG — Command Workflow
===

Document-centric knowledge graph building and querying.

## Build the Graph

```bash
dockg build docs
```

Build the authoritative SQLite knowledge graph from your documentation corpus (`.md`, `.txt`, `.rst`, and `.pdf` files).
This runs corpus parsing, SQLite persistence, and sqlite-vec vector indexing in one step.
Existing data is wiped by default; pass `--update` to keep existing data instead.

**Granular steps (for large corpora):**

```bash
# Step 1 — parse corpus and write SQLite graph
dockg build-graph docs

# Step 2 — build the sqlite-vec vector index from existing SQLite
dockg build-index
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

## Multipass Analysis Pipeline

```bash
dockg pipeline run --repo docs --batch 20
```

Run the diary_kg-style 5-phase NLP transformation pipeline:
1. **Diversity Sampling** — K-means clustering on NLP features, representative batch
2. **Sentence-Group Chunking** — 4 sentences per chunk, natural boundaries
3. **Hybrid Topic Classification** — supervised keyword matching + unsupervised K-means fallback
4. **Memory Creation** — EntryChunk objects with full source provenance
5. **Structured Output** — pipe-delimited `.psv` with run parameters and statistics

Output: `.dockg/pipeline/PipelineRun_<id>_<timestamp>.psv`

### Corpus Embedding

```bash
dockg pipeline embed --repo docs --workers 4
```

Multi-process corpus embedding using `nomic-ai/nomic-embed-text-v1` (768-d).
Produces a JSON cache at `.dockg/pipeline/embeddings.json`.

### Manifold Analysis

```bash
dockg pipeline manifold
```

Analyze embedding geometry:
- PCA elbow (90/95/99% explained variance)
- Participation Ratio (effective dimensionality)
- TwoNN intrinsic dimensionality
- MRL truncation quality (MRR@10 at 32/64/128/256/512/768 dims)

## MCP Server

```bash
dockg mcp --repo /absolute/path/to/repo
```

Start the MCP server (stdio transport) for use with Claude Code, GitHub Copilot, or other MCP clients.

## Workflow Example

```bash
# 1. Build the graph from documentation
dockg build docs

# 2. Analyze coverage before publishing
dockg analyze docs

# 3. Explore topics interactively
dockg viz

# 4. Query for specific content
dockg query "API authentication methods"

# 5. Extract markdown pack for a topic
dockg pack "error handling patterns" --top 5

# 6. Run multipass analysis pipeline
dockg pipeline run --repo docs --batch 30

# 7. Embed corpus for manifold analysis
dockg pipeline embed --repo docs

# 8. Analyze embedding quality
dockg pipeline manifold

# 9. Capture a snapshot at a milestone
dockg snapshot save "documentation-v1.0"

# 10. Start MCP server for IDE integration
dockg mcp --repo .
```

## Full Ingestion Architecture

See `docs/ingestion.md` for the complete ingestion path documentation covering both the core build pipeline and the multipass analysis pipeline.
