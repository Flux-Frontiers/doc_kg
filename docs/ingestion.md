# DocKG — Complete Ingestion Architecture

**Two complementary pipelines for building semantically searchable knowledge graphs from document corpora.**

DocKG offers two ingestion paths: the **Core Build Pipeline** for fast, deterministic graph construction, and the **Multipass Analysis Pipeline** for deeper NLP analysis with diversity sampling, hybrid topic classification, corpus embedding, and manifold analysis. Both produce artifacts under `.dockg/` and can be used independently or together.

---

## Pipeline Overview

```
                          ┌─────────────────────────────────────────┐
                          │            DOCUMENT CORPUS              │
                          │    (.md, .txt, .rst, .pdf files)        │
                          └─────────────┬───────────────────────────┘
                                        │
                  ┌─────────────────────┼─────────────────────┐
                  │                                           │
                  ▼                                           ▼
     ┌────────────────────────┐              ┌────────────────────────────────┐
     │   CORE BUILD PIPELINE  │              │  MULTIPASS ANALYSIS PIPELINE   │
     │     (dockg build)      │              │     (dockg pipeline run)       │
     │                        │              │                                │
     │  Fast, deterministic   │              │  Deep NLP, diary_kg-style      │
     │  SQLite + LanceDB      │              │  5-phase transformation        │
     └────────────┬───────────┘              └──────────────┬─────────────────┘
                  │                                         │
                  ▼                                         ▼
     ┌────────────────────────┐              ┌────────────────────────────────┐
     │  .dockg/graph.sqlite   │              │  .dockg/pipeline/*.psv         │
     │  .dockg/lancedb/       │              │  .dockg/pipeline/embeddings.json│
     │                        │              │  .dockg/cache/*.pkl            │
     │  → MCP server          │              │                                │
     │  → query / pack        │              │  → manifold analysis           │
     │  → analyze             │              │  → corpus embedding            │
     └────────────────────────┘              └────────────────────────────────┘
```

---

## 1. Core Build Pipeline (`dockg build`)

The standard ingestion path. Parses a corpus into a hybrid SQLite + LanceDB knowledge graph in a single command.

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│             RAW CORPUS (.md / .txt / .rst / .pdf)           │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│          PASS 1: CORPUS PARSING  (parse_corpus)             │
│                                                             │
│  For each file:                                             │
│    1. Parse Markdown headings → section hierarchy           │
│    2. Emit document + section nodes + CONTAINS edges        │
│    3. Semantic chunking within each section                 │
│       (embedding-based boundary detection or fixed-size)    │
│    4. Emit chunk nodes + CONTAINS + NEXT edges              │
│    5. Detect hyperlinks → REFERENCES edges                  │
│    6. Topic classification → HAS_TOPIC edges                │
│    7. Entity extraction → MENTIONS_ENTITY edges             │
│    8. Keyword extraction → HAS_KEYWORD edges                │
│    9. Co-occurrence pairs → CO_OCCURS_WITH edges            │
│                                                             │
│  Output: (nodes, edges) → GraphStore.write() → SQLite      │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│       PASS 2: SEMANTIC INDEXING  (SemanticIndex.build)      │
│                                                             │
│  1. Read all nodes from SQLite                              │
│  2. Batch-embed via SentenceTransformerEmbedder             │
│     Model: all-mpnet-base-v2 (768-dim)                      │
│  3. Write vectors to LanceDB                                │
│  4. SIMILAR_TO edge discovery:                              │
│     - k-NN search per chunk                                 │
│     - Emit edge when cosine similarity ≥ 0.85              │
│     - Write SIMILAR_TO edges back to SQLite                 │
│                                                             │
│  Output: LanceDB index + SIMILAR_TO edges in SQLite         │
└─────────────────────────────────────────────────────────────┘
```

### Key Components

| Component | File | Role |
|-----------|------|------|
| `DocKG` | `kg.py` | Top-level orchestrator: `build()`, `query()`, `pack()` |
| `parse_corpus()` | `dockg.py` | Deterministic extraction: files → nodes + edges |
| `TextChunker` | `chunker.py` | Semantic text segmentation (embedding-based boundaries) |
| `GraphStore` | `store.py` | SQLite persistence layer |
| `SemanticIndex` | `index.py` | LanceDB vector index + SIMILAR_TO discovery |
| `TopicExtractor` | `topics.py` | Supervised keyword-based topic classification |
| `extract_entities()` | `relations.py` | Deterministic entity extraction (titlecase/acronym) |

### Node Kinds

| Kind | ID Pattern | Description |
|------|-----------|-------------|
| `document` | `doc:<file_path>` | One per `.md`/`.txt`/`.rst`/`.pdf` file |
| `section` | `sec:<file_path>:<slug>` | Markdown heading block |
| `chunk` | `chunk:<file_path>:<0000>` | Semantic text block (~512 chars) |
| `topic` | `topic:<slug>` | Classified topic label |
| `entity` | `entity:<slug>` | Named entity (titlecase/acronym) |
| `keyword` | `keyword:<slug>` | Extracted keyword |

### Edge Types

| Relation | Direction | Meaning |
|----------|-----------|---------|
| `CONTAINS` | doc → sec → chunk | Structural hierarchy |
| `NEXT` | chunk → chunk | Sequential reading order |
| `REFERENCES` | chunk → doc | Cross-document hyperlinks |
| `SIMILAR_TO` | chunk ↔ chunk | Cosine similarity ≥ 0.85 |
| `HAS_TOPIC` | chunk → topic | Topic classification |
| `MENTIONS_ENTITY` | chunk → entity | Entity mention |
| `HAS_KEYWORD` | chunk → keyword | Keyword salience |
| `CO_OCCURS_WITH` | semantic ↔ semantic | Same-chunk co-occurrence |

### Usage

```bash
# Full build (parse + index + SIMILAR_TO)
dockg build docs --wipe

# Granular steps
dockg build-graph docs --wipe     # Step 1: parse → SQLite only
dockg build-index --wipe          # Step 2: SQLite → LanceDB + SIMILAR_TO

# With custom options
dockg build docs --wipe \
    --chunk-size 512 \
    --model all-mpnet-base-v2 \
    --enable-topics --enable-entities --enable-keywords \
    --topics-file custom_topics.yaml \
    --exclude-dir archive --exclude-dir vendor
```

### Embedding Model

| Model | Dims | Context | Notes |
|-------|------|---------|-------|
| `all-mpnet-base-v2` | 768 | General text | Default for core build |
| `BAAI/bge-small-en-v1.5` | 384 | Code + metadata | Canonical for CodeKG |

Override via `--model` or `DOCKG_MODEL` environment variable.

---

## 2. Multipass Analysis Pipeline (`dockg pipeline`)

Deep NLP transformation pipeline inspired by diary_kg. Implements a 5-phase transformation plus corpus embedding and manifold analysis stages. Designed for thorough analysis of large corpora with diversity sampling, hybrid topic classification, and structured provenance tracking.

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│             RAW CORPUS (.md / .txt / .rst / .pdf)           │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│            PHASE 1: DIVERSITY SAMPLING                      │
│            (sampler.py → CorpusSampler)                     │
│                                                             │
│  • NLP feature extraction per document:                     │
│    - Token count, sentence count, unique words              │
│    - Entity count (titlecase/acronym heuristic)             │
│    - Text length, temporal index (file sort order)          │
│  • K-means clustering on feature vectors (StandardScaler)   │
│  • Proportional sampling from each cluster                  │
│  • Pickle-based feature cache with SHA-256 hash validation  │
│                                                             │
│  Output: Representative file sample (default: 20 docs)      │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│            PHASE 2: CHUNKING                                │
│            (chunker.py → SentenceGroupChunker)              │
│                                                             │
│  • Sentence-group strategy (default):                       │
│    - Group N consecutive sentences (default: 4)             │
│    - Natural sentence boundaries (no mid-sentence breaks)   │
│    - Predictable chunk size (~400-500 chars)                │
│    - Fast: no embedding required                            │
│    - Respects Markdown section boundaries as hard splits     │
│  • Semantic strategy (alternative):                         │
│    - Embedding-based boundary detection                     │
│    - Cosine similarity drop → new chunk                     │
│                                                             │
│  Output: Chunk dicts with text + section + char offsets      │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│            PHASE 3: HYBRID TOPIC CLASSIFICATION             │
│            (topics.py → TopicExtractor.classify_hybrid)     │
│                                                             │
│  Supervised path (primary):                                 │
│    • Keyword catalog matching (built-in or custom YAML)     │
│    • Score = 0.75 × coverage + 0.25 × density               │
│    • Accept if confidence ≥ supervised_threshold (0.3)      │
│                                                             │
│  Unsupervised path (fallback):                              │
│    • Embed all chunks via SentenceTransformer               │
│    • Fit K-means on embedding vectors (n_clusters=8)        │
│    • Assign cluster label, confidence from centroid distance │
│                                                             │
│  Fallback path:                                             │
│    • Synthesize pseudo-topic from top keywords              │
│                                                             │
│  Output: (topics, method, confidence) per chunk              │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│            PHASE 4: MEMORY CREATION                         │
│            (entry_chunk.py → EntryChunk)                    │
│                                                             │
│  Build structured EntryChunk objects:                       │
│    • chunk_id: stable content-addressed hash                │
│    • text: chunk content                                    │
│    • provenance: SourceProvenance (file, offsets, section)   │
│    • topics: [(name, score)] from Phase 3                   │
│    • topic_method: "supervised" | "unsupervised" | "fallback│
│    • keywords: extracted keywords                           │
│    • entities: extracted entities                            │
│    • embedding: optional float32 vector                     │
│    • run_id: links to pipeline run                          │
│                                                             │
│  Output: list[EntryChunk] with full provenance              │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│            PHASE 5: STRUCTURED OUTPUT                       │
│            (pipeline.py → _phase5_output)                   │
│                                                             │
│  Pipe-delimited .psv file:                                  │
│    • Header: run parameters (strategy, batch, seed, etc.)   │
│    • Source tracking: file-grouped with section comments     │
│    • Rows: chunk_id | topic | confidence | method | kw | text│
│    • Footer: classification statistics                      │
│                                                             │
│  Output: .dockg/pipeline/PipelineRun_<id>_<timestamp>.psv   │
└────────────────────────────┬────────────────────────────────┘
                             │
                      ┌──────┴──────┐
                      ▼             ▼
┌─────────────────────────┐  ┌────────────────────────────────┐
│  STAGE 3: CORPUS        │  │  STAGE 4: MANIFOLD ANALYSIS    │
│  EMBEDDING              │  │  (manifold.py)                 │
│  (embedder_worker.py)   │  │                                │
│                         │  │  • PCA elbow (90/95/99%)       │
│  • nomic-embed-text-v1  │  │  • Participation Ratio         │
│    (768-d, asymmetric)  │  │  • TwoNN intrinsic dim         │
│  • search_document:     │  │  • MRL truncation quality      │
│    task prefix           │  │    (MRR@10 at 32/64/128/      │
│  • Spawn-safe workers   │  │     256/512/768 dims)          │
│  • JSON cache output    │  │                                │
│  • Temporal sampling    │  │  Input: embeddings.json        │
│                         │  │  Output: ManifoldReport        │
│  Output: embeddings.json│  │                                │
└─────────────────────────┘  └────────────────────────────────┘
```

### Key Components

| Component | File | Role |
|-----------|------|------|
| `AnalysisPipeline` | `pipeline.py` | 5-phase orchestrator |
| `PipelineConfig` | `pipeline.py` | All configuration in one dataclass |
| `CorpusSampler` | `sampler.py` | Phase 1: feature extraction + K-means sampling |
| `SentenceGroupChunker` | `chunker.py` | Phase 2: N-sentence-per-chunk strategy |
| `TopicExtractor.classify_hybrid()` | `topics.py` | Phase 3: supervised + unsupervised |
| `EntryChunk` / `SourceProvenance` | `entry_chunk.py` | Phase 4: structured output dataclasses |
| `CorpusEmbedder` | `embedder_worker.py` | Stage 3: parallel embedding |
| `ManifoldAnalyzer` | `manifold.py` | Stage 4: dimensionality analysis |

### Usage

```bash
# Full 5-phase pipeline
dockg pipeline run --repo docs --batch 20 --strategy sentence_group

# With custom options
dockg pipeline run --repo docs \
    --batch 30 \
    --strategy sentence_group \
    --sentences 4 \
    --sampling diversity \
    --n-clusters 8 \
    --supervised-threshold 0.3 \
    --topics-file custom_topics.yaml \
    --seed 42

# Corpus embedding (Stage 3)
dockg pipeline embed --repo docs --workers 4 --batch-size 64

# With temporal sampling (evenly spaced subset)
dockg pipeline embed --repo docs --sample-n 500

# Manifold analysis (Stage 4)
dockg pipeline manifold --repo docs

# With custom PCA components
dockg pipeline manifold --cache .dockg/pipeline/embeddings.json --max-pca 128
```

### Embedding Model

| Model | Dims | Task Prefix | Context |
|-------|------|-------------|---------|
| `nomic-ai/nomic-embed-text-v1` | 768 | `search_document: <text>` | Pipeline default — asymmetric retrieval, matches diary_kg |

Override via `--model` on any pipeline command.

### Sampling Strategies

| Strategy | Method | When to Use |
|----------|--------|-------------|
| `diversity` | K-means on NLP features, sample per cluster | Default — ensures thematic coverage |
| `random` | Simple random sample | Quick exploration |
| `temporal` | Evenly spaced by file-sort index | Chronological corpora |

### Output Format (.psv)

```
# DocKG Multipass Analysis Pipeline - Run Parameters
# Run ID: a26f95a69fd5
# Generated: 2026-04-05T22:20:21+00:00
# Chunk strategy: sentence_group
# Batch size: 20
# Sampling strategy: diversity
# ...
#
# ======== ENTRIES ========

# === Source: docs/authentication.md ===
# Section: OAuth2 Flow
pchunk:docs/authentication.md:3f8a2b1c | authentication | 0.44 | supervised | oauth,token,jwt | The OAuth2 flow begins with...

# ======== STATISTICS ========
# Supervised classifications: 45
# Unsupervised classifications: 12
# Fallback classifications: 20
# Supervised rate: 58.4%
```

### Feature Caching

Phase 1 caches extracted NLP features per-file using pickle:
- Cache key: `{sha256(file_path)[:12]}_{content_hash[:8]}.pkl`
- Stored in: `.dockg/cache/`
- Invalidation: automatic when file content changes (SHA-256 hash mismatch)
- Speedup: 5-10x on subsequent runs

### Manifold Report

```
Manifold Analysis Report
========================================
Vectors:          500
Ambient dim:      768

PCA Explained Variance:
  90% at:         42 dims
  95% at:         87 dims
  99% at:         210 dims

Participation Ratio: 23.45
TwoNN dimension:    18.72

MRL Truncation Quality (MRR@10):
    32-dim: 0.6234
    64-dim: 0.7891
   128-dim: 0.8945
   256-dim: 0.9567
   512-dim: 0.9912
   768-dim: 1.0000
```

---

## 3. Analysis Pipelines (Post-Build)

After building the core graph, two analysis engines provide multi-pass structural and semantic insight.

### Structural Analysis (`dockg analyze`)

Six sequential phases reading the SQLite graph:

1. **Baseline stats** — node/edge counts by kind and relation
2. **Document metrics** — per-doc: chunks, sections, references, semantic links
3. **Semantic coverage** — fraction of chunks with topic/entity/keyword edges
4. **Orphan detection** — semantic nodes without incoming edges
5. **Hot chunk ranking** — top 15 chunks by connectivity
6. **Insight generation** — heuristic issues and strengths

Output: Markdown report + JSON at `~/.claude/dockg_analysis_latest.json`

### Semantic Analysis (`dockg semantic-analyze`)

Eight sequential phases:

1. **Themes** — topics ranked by cross-document spread
2. **Entities** — named entities by document spread
3. **Keywords** — global keyword frequency
4. **Language metrics** — vocabulary richness, sentence complexity, lexical density, Flesch-Kincaid
5. **Document signatures** — per-document top keywords + entities
6. **Heading vocabulary** — most frequent section heading terms
7. **Cohesion score** — fraction of themes spanning ≥3 documents
8. **Insight generation** — quality observations

Output: Markdown report + JSON at `~/.claude/dockg_semantic_latest.json`

---

## 4. Choosing a Pipeline

| Need | Pipeline | Command |
|------|----------|---------|
| Build searchable graph for MCP/CLI queries | Core Build | `dockg build docs --wipe` |
| Deep NLP analysis with diversity sampling | Multipass | `dockg pipeline run --repo docs` |
| Corpus embedding for manifold analysis | Multipass | `dockg pipeline embed --repo docs` |
| Intrinsic dimensionality / MRL quality | Multipass | `dockg pipeline manifold` |
| Structural health check | Analysis | `dockg analyze docs` |
| Semantic theme/entity/language analysis | Analysis | `dockg semantic-analyze docs` |
| Quick topic classification exploration | Multipass | `dockg pipeline run --batch 10 --sampling random` |

The core build pipeline is always needed for MCP server, `query`, and `pack`. The multipass pipeline is complementary — use it for deeper corpus understanding, embedding quality evaluation, and diary_kg-style provenance tracking.

---

## 5. Storage Layout

```
.dockg/
├── graph.sqlite           # Core build: SQLite knowledge graph
├── lancedb/               # Core build: LanceDB vector index
├── snapshots/             # Temporal snapshots (JSON)
│   ├── manifest.json
│   └── <version>.json
├── cache/                 # Multipass: per-file feature caches (pickle)
│   └── <hash>_<hash>.pkl
├── pipeline/              # Multipass: pipeline run outputs
│   ├── PipelineRun_<id>_<ts>.psv
│   └── embeddings.json    # Corpus embedding cache
└── models/                # Cached embedding models
    └── all-mpnet-base-v2/
```

All artifacts under `.dockg/` are local and reproducible. Add `.dockg/` to `.gitignore`.

---

## 6. Model Reference

| Context | Model | Dims | Why |
|---------|-------|------|-----|
| Core build (`dockg build`) | `all-mpnet-base-v2` | 768 | Strong general-text sentence model |
| Pipeline embedding (`dockg pipeline embed`) | `nomic-ai/nomic-embed-text-v1` | 768 | Asymmetric retrieval with task prefix; matches diary_kg |
| Code knowledge graphs (CodeKG) | `BAAI/bge-small-en-v1.5` | 384 | Benchmark winner for code+metadata |

The core build and pipeline use different models by design:
- **Core build** embeds short node descriptions (title + name + text[:1024]) for SIMILAR_TO discovery
- **Pipeline embed** embeds full document chunks for manifold analysis and MRL evaluation
- Both produce 768-d vectors but serve different retrieval contexts
