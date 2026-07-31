# DocKG — Knowledge Graph Schema

## Node kinds

| Kind | Description |
|---|---|
| `document` | A source `.md`, `.txt`, `.rst`, or `.pdf` file |
| `section` | A heading-delimited region within a document |
| `chunk` | A semantically coherent text passage (≥ 50 chars) |
| `topic` | A topic extracted from chunk text |
| `entity` | A named entity (person, place, org, concept) |
| `keyword` | A keyword or key phrase |

Chunks are the primary retrieval unit. Document and section nodes are suppressed from pack results when chunks from the same file are already present — you always get the most specific evidence available.

---

## Edge types

| Type | Description |
|---|---|
| `CONTAINS` | Parent → child (document→section, section→chunk) |
| `NEXT` | Sequential ordering between same-level nodes |
| `REFERENCES` | Chunk cites another document or section |
| `SIMILAR_TO` | Semantic similarity between chunks (vector-derived) |
| `HAS_TOPIC` | Chunk → topic |
| `MENTIONS_ENTITY` | Chunk → named entity |
| `HAS_KEYWORD` | Chunk → keyword |
| `CO_OCCURS_WITH` | Co-occurrence between topics/entities within a chunk |

`CONTAINS` and `NEXT` are structural — derived directly from heading hierarchy and document order, with no inference. `SIMILAR_TO` is the only edge type that involves the vector index; it is built once during `dockg build` and stored in SQLite like everything else.

---

## Storage layout

```
.dockg/
  graph.sqlite        # SQLite knowledge graph (nodes + edges)
  vectors.sqlite      # sqlite-vec vector index
  snapshots/          # Temporal metric snapshots (JSON)
    manifest.json
    <sha>.json        # one file per captured snapshot
```

The SQLite store is the canonical source of truth. The vector index is a pure acceleration layer — it can be rebuilt at any time with `dockg build` without losing any structural information. Snapshots are append-only; `manifest.json` is the index.

---

## Node ID format

Node IDs are stable across rebuilds for the same corpus:

| Kind | Format |
|---|---|
| `document` | `doc:<relative_path>` |
| `section` | `section:<relative_path>:<heading_slug>` |
| `chunk` | `chunk:<relative_path>:<zero_padded_index>` |
| `topic` | `topic:<slug>` |
| `entity` | `entity:<slug>` |
| `keyword` | `keyword:<slug>` |

Use node IDs with `dockg-mcp`'s `get_node` tool or the Python API's `DocKG.get_node()` for direct retrieval.
