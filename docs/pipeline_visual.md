# DocKG Pipeline — Visual Description for Image Generation

## One-sentence summary

**DocKG converts a raw document corpus into a hybrid semantic + structural knowledge graph through two parallel ingestion pipelines, storing results in SQLite and LanceDB, and exposing them via a CLI and MCP server.**

> **Supported input formats:** `.md`, `.txt`, `.rst`, `.pdf`

---

## Image Generation Prompt (text-to-image / illustration brief)

> A clean, high-contrast technical architecture diagram on a dark navy background. Left side shows a stack of labeled document files (.md, .txt, .rst, .pdf) flowing downward through a branching arrow into two parallel vertical pipeline columns. The left column, labeled "Core Build Pipeline," contains two stacked rectangular process boxes connected by downward arrows: "Corpus Parsing" (subdivided into sub-steps: heading extraction → section nodes → semantic chunking → entity/topic/keyword extraction) and "Semantic Indexing" (subdivided into: batch embedding with all-mpnet-base-v2 → LanceDB vector store → SIMILAR_TO edge discovery). The right column, labeled "Multipass Analysis Pipeline," contains five sequential boxes: "Diversity Sampling," "Chunking," "Hybrid Topic Classification," "Memory Creation," and "Structured Output." Both columns converge at the bottom into a single output layer showing three artifacts side by side: a cylinder labeled "SQLite graph.sqlite," a cylinder labeled "LanceDB vectors," and a folder labeled ".dockg/pipeline/*.psv." Below that, two final output boxes: "MCP Server (query_docs / pack_docs)" and "CLI (dockg query / pack / analyze)." Connecting lines use thin white arrows with labeled edge types (CONTAINS, NEXT, SIMILAR_TO, HAS_TOPIC, MENTIONS_ENTITY, HAS_KEYWORD) rendered as small annotation bubbles on the arrows. Color coding: structural edges in blue, semantic edges in amber, topic/entity edges in teal. Style: flat design, sans-serif labels, IBM Plex Mono for code names, minimal drop shadows.

---

## Structured Component Description

### Inputs

| Source | Description |
|--------|-------------|
| Document corpus | `.md`, `.txt`, `.rst`, `.pdf` files on the local filesystem |
| Config options | `--chunk-size`, `--model`, `--topics-file`, `--exclude-dir` |

---

### Core Build Pipeline (`dockg build`)

A two-pass, deterministic ingestion path producing a hybrid SQLite + LanceDB knowledge graph.

#### Pass 1 — Corpus Parsing (`parse_corpus`)

For every `.md`, `.txt`, `.rst`, or `.pdf` file in the corpus:

1. Parse Markdown headings → **section hierarchy**
2. Emit `document` and `section` nodes with `CONTAINS` edges
3. Segment text into semantic **chunks** (~512 chars, embedding-based or fixed-size boundaries)
4. Emit `chunk` nodes with `CONTAINS` (parent section) and `NEXT` (sequential order) edges
5. Detect hyperlinks → `REFERENCES` edges to other documents
6. Classify topic → `HAS_TOPIC` edges to `topic` nodes
7. Extract named entities (titlecase/acronym heuristic) → `MENTIONS_ENTITY` edges
8. Extract keywords → `HAS_KEYWORD` edges
9. Build co-occurrence pairs → `CO_OCCURS_WITH` edges

**Output:** SQLite (`graph.sqlite`) with nodes + structural/semantic edges

#### Pass 2 — Semantic Indexing (`SemanticIndex.build`)

1. Read all nodes from SQLite
2. Batch-embed chunks with `all-mpnet-base-v2` (768-dim)
3. Write vectors to LanceDB
4. k-NN search per chunk; emit `SIMILAR_TO` edge when cosine similarity ≥ 0.85
5. Write `SIMILAR_TO` edges back to SQLite

**Output:** LanceDB vector index + `SIMILAR_TO` edges in SQLite

---

### Multipass Analysis Pipeline (`dockg pipeline run`)

A five-phase NLP transformation pipeline for deep corpus analysis with diversity sampling and structured provenance.

#### Phase 1 — Diversity Sampling (`CorpusSampler`)

- Extract NLP features per document: token count, sentence count, unique words, entity count, text length, temporal index
- Fit K-means on feature vectors (StandardScaler)
- Proportional sampling from each cluster (default: 20 representative documents)
- Pickle cache with SHA-256 hash validation

**Output:** Representative file sample for downstream phases

#### Phase 2 — Chunking (`SentenceGroupChunker`)

- Group N consecutive sentences (default: 4) into chunks (~400–500 chars)
- Respect Markdown section boundaries as hard splits
- Alternative: embedding-based semantic boundary detection (cosine similarity drop → new chunk)

**Output:** Chunk dicts with text, section label, and character offsets

#### Phase 3 — Hybrid Topic Classification (`TopicExtractor.classify_hybrid`)

| Path | Mechanism | Threshold |
|------|-----------|-----------|
| Supervised (primary) | Keyword catalog matching; score = 0.75 × coverage + 0.25 × density | confidence ≥ 0.3 |
| Unsupervised (fallback) | Embed all chunks → K-means (n=8 clusters) → centroid distance confidence | — |
| Keyword fallback | Synthesize pseudo-topic from top keywords | — |

**Output:** `(topics, method, confidence)` per chunk

#### Phase 4 — Memory Creation (`EntryChunk`)

Build structured `EntryChunk` objects containing:
- `chunk_id`: stable content-addressed hash
- `text`: chunk content
- `provenance`: `SourceProvenance` (file path, section heading, char offsets)
- `topics`: `[(name, score)]` with classification method
- `keywords` and `entities`
- `embedding`: optional float32 vector
- `run_id`: links chunk to pipeline run

**Output:** `list[EntryChunk]` with full source provenance

#### Phase 5 — Structured Output

- Pipe-delimited `.psv` files with run parameters and statistics
- `embeddings.json` for corpus embedding layer
- Pickle feature caches under `.dockg/cache/`

**Output:** `.dockg/pipeline/*.psv`, `embeddings.json`, optional manifold analysis

---

### Node Taxonomy

| Kind | ID Pattern | Role in Graph |
|------|-----------|---------------|
| `document` | `doc:<file_path>` | One node per source file |
| `section` | `sec:<file_path>:<slug>` | Markdown heading block |
| `chunk` | `chunk:<file_path>:<0000>` | Semantic text block (~512 chars) |
| `topic` | `topic:<slug>` | Classified topic label |
| `entity` | `entity:<slug>` | Named entity (titlecase / acronym) |
| `keyword` | `keyword:<slug>` | Extracted keyword |

### Edge Taxonomy

| Relation | Direction | Visual Color | Meaning |
|----------|-----------|-------------|---------|
| `CONTAINS` | doc → sec → chunk | **Blue** | Structural containment hierarchy |
| `NEXT` | chunk → chunk | **Blue** | Sequential reading order |
| `REFERENCES` | chunk → doc | **Blue** | Cross-document hyperlink |
| `SIMILAR_TO` | chunk ↔ chunk | **Amber** | Cosine similarity ≥ 0.85 |
| `HAS_TOPIC` | chunk → topic | **Teal** | Topic classification result |
| `MENTIONS_ENTITY` | chunk → entity | **Teal** | Named entity mention |
| `HAS_KEYWORD` | chunk → keyword | **Teal** | Keyword salience |
| `CO_OCCURS_WITH` | semantic ↔ semantic | **Teal** | Same-chunk co-occurrence |

---

### Storage Layer

| Store | Technology | Contents |
|-------|-----------|----------|
| `graph.sqlite` | SQLite | All nodes, structural edges, topic/entity/keyword edges, SIMILAR_TO edges |
| `lancedb/` | LanceDB | 768-dim float32 vectors for hybrid semantic search |
| `pipeline/*.psv` | Flat files | Structured EntryChunk records with run provenance |
| `cache/*.pkl` | Pickle | Per-document NLP feature vectors (hash-validated) |

---

### Query & Serving Layer

```
LanceDB (ANN seed)
        │
        ▼
  Hybrid search: top-k semantic seeds
        │
        ▼
  Graph expansion (CONTAINS, REFERENCES, SIMILAR_TO, NEXT, hop=1)
        │
        ▼
  Deduplicate coarser nodes when chunks already present
        │
        ▼
  Ranked passage pack with source attribution (file + heading + char range)
        │
  ┌─────┴─────┐
  ▼           ▼
CLI         MCP server
(dockg      (query_docs
 pack)       pack_docs
             get_node)
```

---

### Embedding Models Reference

| Context | Model | Dims | Purpose |
|---------|-------|------|---------|
| Core build (`dockg build`) | `all-mpnet-base-v2` | 768 | Strong general-text sentence model |
| Pipeline embedding | `nomic-ai/nomic-embed-text-v1` | 768 | Asymmetric retrieval with task prefix |
| Code knowledge graphs | `BAAI/bge-small-en-v1.5` | 384 | Benchmark winner for code + metadata |

---

### Design Philosophy

> **Structure is ground truth; embeddings are an acceleration layer.**

Vanilla RAG embeds chunks in isolation and retrieves by cosine similarity alone — no awareness of document hierarchy, cross-references, or structural redundancy. DocKG uses the vector index for semantic *seeding*, then expands through a typed graph so that containment, sequencing, citation, and similarity all shape what gets returned. When graph and vector index disagree, the graph wins. Every result is traceable to a specific file, heading, and character offset.
