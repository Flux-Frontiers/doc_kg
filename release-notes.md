# Release Notes — v0.11.0

> Released: 2026-04-24

## What is DocKG?

DocKG is a hybrid semantic + structural knowledge graph for document corpora. Given a directory of Markdown or plain-text files, it builds a queryable graph of chunks, sections, topics, and entities connected by structural edges (CONTAINS, SIMILAR_TO, CO_OCCURS_WITH, ABOUT, etc.). Retrieval uses vector similarity (LanceDB) seeded into graph expansion (SQLite) — the same hybrid architecture as PyCodeKG but for natural-language documents instead of source code.

The core use case is MCP-based AI integration: DocKG ships an MCP server (`dockg mcp`) that exposes `graph_stats`, `query_docs`, `pack_docs`, and `get_node` tools to any MCP-compatible agent (Claude Code, Claude Desktop, Cursor, Continue). Document packs are pre-formatted for LLM context windows, with relevance scores and hop distances on every returned node.

---

## What's New in v0.11.0

### KGRAG Federation Support

DocKG now fully participates in the KGRAG federated query layer. Two contracts are implemented:

**Builder stamp.** Every `dockg build` call writes a `_kgrag_meta` table into the SQLite database recording `builder_name="doc_kg"`, `builder_version` (from the installed package), and `built_at` (ISO-8601 UTC). The `INSERT OR REPLACE` strategy means rebuilds update the timestamp without creating duplicates. This stamp is the KGRAG adapter-version contract — `kgrag info` and `kgrag status` can surface DocKG provenance alongside PyCodeKG and MemoryKG.

**Stats contract.** `DocKG.stats()` now returns a flat dict conforming to the KGRAG adapter stats contract: `node_count`, `edge_count`, `document_count`, `chunk_count`, `section_count`, `topic_count`, `entity_count`, `keyword_count`. It wraps all queries in `try/except` and returns zeros plus an `"error"` key on failure — never raises — so the federated `kgrag stats` aggregator always gets a response.

### New `dockg status` Command

`dockg status` is a new Rich-formatted CLI command that shows the state of a built knowledge graph at a glance:

- Builder metadata from `_kgrag_meta`: name, version, built-at timestamp, DB size in MB
- Side-by-side tables of node kinds (chunks, sections, topics, entities, keywords) and edge relations
- Exits non-zero if the database file is absent — safe to use in CI

### Relevance Scores on Every Result

`DocKG.query()` and `DocKG.pack()` now inject a `relevance` dict into every returned node:

```python
{"score": float, "dist": float, "hop": int, "semantic_boost": float}
```

`score` is cosine similarity in [0, 1] (higher = more relevant). Previously all DocKG hits registered as `0.0` in federated KGRAG queries, causing them to rank below code hits regardless of semantic quality. This fix brings DocKG nodes into fair competition with PyCodeKG results in cross-KG retrieval.

### Embedding Model: `BAAI/bge-small-en-v1.5`

The default embedding model is now `BAAI/bge-small-en-v1.5` (384-dim), replacing `all-mpnet-base-v2` (768-dim). BGE-small was benchmarked across both literary and technical retrieval corpora and outperformed the previous default. It is the same model used by PyCodeKG, which improves cross-KG vector alignment in federated queries. The model can be overridden via the `DOCKG_MODEL` environment variable.

Cosine distance is now explicitly chained on every LanceDB query (`.metric("cosine")`), ensuring `1 − dist` maps correctly to [0, 1] similarity. The previous `min(base_dist, 1.0)` clamp — which was masking score fidelity for distant hits — has been removed.

### MemoryKG Semantic Analysis

A new corpus analysis report (`analysis/memory_kg_semantic_20260422.md`) documents DocKG applied to a MemoryKG conversation corpus: language profile, top entities, dominant themes, and document signatures. This serves as both a validation artifact and a usage example for non-technical corpora.

---

## Current Capabilities (v0.11.0)

| Capability | Details |
|---|---|
| Supported formats | `.md`, `.txt` |
| Chunking strategies | `semantic` (default), `sentence_group`, `fixed` |
| Embedding model | `BAAI/bge-small-en-v1.5` (384-dim); override via `DOCKG_MODEL` |
| Vector store | LanceDB (cosine metric) |
| Graph store | SQLite with composite indexes |
| Query mode | Hybrid: vector seed → graph expansion (hop=0/1/2) |
| Relevance signal | Cosine similarity + short-chunk boost + semantic boost |
| MCP tools | `graph_stats`, `query_docs`, `pack_docs`, `get_node` |
| CLI commands | `build`, `build-graph`, `build-index`, `query`, `pack`, `analyze`, `viz`, `status`, `snapshot`, `mcp`, `download-model`, `install-hooks` |
| KGRAG integration | Builder stamp, stats contract, relevance scores |
| Snapshot tracking | Temporal metrics via `dockg snapshot save/list/show/diff` |

---

## Installation

```bash
pip install doc-kg
# or
poetry add doc-kg
```

Build a knowledge graph:

```bash
dockg build --repo /path/to/docs/
dockg status --repo /path/to/docs/
dockg query --repo /path/to/docs/ "semantic search architecture"
```

Add as an MCP server (Claude Code):

```json
{
  "mcpServers": {
    "dockg": {
      "command": "dockg-mcp",
      "args": ["--repo", "/path/to/docs/"]
    }
  }
}
```

---

_Full changelog: [CHANGELOG.md](CHANGELOG.md)_
