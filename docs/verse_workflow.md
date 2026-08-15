# DocKG — Verse Corpus Ingestion Workflow

A step-by-step guide for ingesting verse-structured sacred texts (KJV Bible, Quran, Vedas, etc.)
into DocKG with near-100% topic coverage via corpus-derived K-means clustering.

---

## Image Generation Prompt (text-to-image / illustration brief)

> A clean, high-contrast technical architecture diagram on a dark navy background. At the top, a stack of labeled text files (`.md`) with visible `chapter:verse` line fragments flowing downward into a horizontal five-phase pipeline. The phases are five evenly-spaced rectangular boxes connected left-to-right by thick arrows, labeled: "Phase 1 — Corpus Preparation," "Phase 2 — Topic Discovery," "Phase 3 — Review YAML," "Phase 4 — Build Graph," "Phase 5 — Query." Below each phase box, a smaller annotation box describes the key operation: Phase 1 shows a magnifying glass over a text file with the label "VerseChunker auto-detect (>10% chapter:verse lines)"; Phase 2 shows a cluster scatter plot icon with the label "K-means (k=16) + TF-IDF → cluster keywords"; Phase 3 shows a YAML document icon with optional edit annotation; Phase 4 shows a database cylinder stack labeled "SQLite + sqlite-vec" with an arrow from a `.kmeans.joblib` model file; Phase 5 shows two output branches — "dockg query" (CLI terminal icon) and "pack_docs / query_docs" (MCP server icon). Below Phase 2, a branching callout shows two output artifacts side-by-side: a file icon labeled `discovered_topics.yaml` and a model icon labeled `discovered_topics.kmeans.joblib`, connected to Phase 4 by a dashed feedback arrow. Below the pipeline, a small comparison table rendered as an inset panel shows three rows: "Keyword catalog → ~7% coverage," "User YAML → ~40% coverage," "K-means model → 100% coverage." Color coding: verse detection and chunking in blue, K-means / embedding operations in amber, YAML / topic artifacts in teal, graph build and storage in violet, query layer in green. Style: flat design, sans-serif labels, IBM Plex Mono for code names and file extensions, minimal drop shadows, subtle grid lines on the cluster scatter plot icon.

---

## What Is a "Verse Corpus"?

A verse corpus is any document where content is organized as numbered `chapter:verse` anchors rather
than prose paragraphs. The King James Bible is the canonical example:

```
## Genesis
1:1 In the beginning God created the heaven and the earth.
1:2 And the earth was without form, and void; and darkness was
upon the face of the deep...
```

DocKG auto-detects verse documents (>10% of lines match `chapter:verse` pattern) and switches to
`VerseChunker` automatically when `--chunk-strategy semantic` is used.

---

## Why a Specialized Workflow?

Standard prose chunking (sentence groups, semantic splits) breaks verse structure:
- Verse boundaries are not sentence boundaries
- Chapter context must be preserved per chunk
- KJV vocabulary defeats keyword topic catalogs (high frequency of "lord", "unto", "saith")
- Manual topic catalogs cover ~7% of chunks; K-means embedding covers 100%

The verse workflow solves all three problems.

---

## The Five-Phase Workflow

```
Phase 1          Phase 2           Phase 3          Phase 4           Phase 5
DETECT     →   DISCOVER       →   REVIEW      →    BUILD        →    QUERY
verses         topics              YAML            graph             corpus
```

---

## Phase 1 — Corpus Preparation

Ensure your corpus is in a single directory. DocKG walks all `.md`, `.txt`, `.rst`, and `.pdf` files under `--repo`.

```bash
# Example structure
corpus/
  sacred-texts/
    the_bible.md       # 99k lines, KJV
    reference.md       # optional metadata
```

**Auto-detection check** — DocKG identifies verse documents by scanning the first 500 lines.
If >10% of non-blank lines match `chapter:verse text`, the file is classified as a verse document
and `VerseChunker` is activated automatically.

| Signal | Threshold |
|---|---|
| Lines matching `^\d+:\d+\s` | >10% of non-blank lines |
| Verses per chunk (default) | 5 verses |
| TOC preamble skipped | Yes (last `##` heading before first verse ref) |

---

## Phase 2 — Topic Discovery (K-means + TF-IDF)

Run `discover-topics` to let the corpus define its own thematic clusters. This is the
corpus-derived alternative to hand-writing a topic catalog.

```bash
dockg pipeline discover-topics \
  --repo /path/to/corpus \
  --output /path/to/corpus/discovered_topics.yaml \
  --n-clusters 16 \
  --n-keywords 15 \
  --chunk-strategy verse \
  --sentences 5
```

**What happens internally:**

| Step | Operation | Output |
|---|---|---|
| 1 | `VerseChunker` splits all files by `chapter:verse` anchors | ~5,400 chunks (KJV) |
| 2 | `BAAI/bge-small-en-v1.5` embeds every chunk (384-d vectors) | (5400, 384) matrix |
| 3 | K-means fits `k=16` clusters on the embedding matrix | 16 centroids |
| 4 | Per-cluster TF-IDF identifies top-15 discriminative terms | Keywords per cluster |
| 5 | YAML catalog written: `{cluster_NN: [kw, ...]}` | Human-readable labels |
| 6 | Fitted K-means saved: `*.kmeans.joblib` | Build-time model |

**Actual output — KJV Bible, k=16:**

| Cluster | Chunks | Top Keywords |
|---|---|---|
| cluster_04 | 578 | kadeshbarnea, achan, rephidim (Exodus/wilderness) |
| cluster_13 | 527 | lazarus, magdalene, cornelius (NT narrative) |
| cluster_01 | 497 | untempered, furbished, haughtiness (Major Prophets) |
| cluster_14 | 443 | apostle, uncircumcision, obedience (Epistles) |
| cluster_07 | 365 | fool, vanity, folly (Wisdom literature) |
| cluster_11 | 349 | testimonies, precepts, lovingkindness (Psalms) |
| cluster_05 | 320 | rachel, laban, leah, rebekah (Patriarchs) |
| cluster_10 | 281 | offering, bullock, atonement (Levitical law) |
| cluster_03 | 221 | cubits, breadth, pillars (Temple architecture) |
| cluster_00 | 268 | reigned, jeroboam, rehoboam (Kings/Chronicles) |

**Choosing k:**

| k | Effect |
|---|---|
| Too low (<8) | Blends distinct themes (Prophets + Epistles in one cluster) |
| 16 (default) | Good balance for a 66-book corpus |
| Too high (>30) | Fragments coherent books into sub-clusters |

Rule of thumb: start at `k ≈ sqrt(files × 10)`, then inspect the YAML. Merge clusters
whose top keywords overlap; split clusters whose keywords look unrelated.

**Two outputs are always written:**

```
discovered_topics.yaml          ← human-readable; rename cluster_NN labels
discovered_topics.kmeans.joblib ← fitted model; used by build-graph for 100% coverage
```

---

## Phase 3 — Review and Label the YAML (Optional)

Open `discovered_topics.yaml` and rename `cluster_NN` keys to human-readable labels.
This step is optional — you can build directly with `--kmeans-model` using the numeric labels.

```yaml
# Before
cluster_11:
  - testimonies
  - precepts
  - lovingkindness
  - quicken
  - meditate

# After renaming (optional)
psalms_devotional:
  - testimonies
  - precepts
  - lovingkindness
  - quicken
  - meditate
```

If you rename labels:
- Use the renamed YAML with `--topics-file` (keyword matching, ~7% coverage)
- **Or** rebuild the K-means model using `discover-topics` after renaming (embedding-based, 100%)

For most use cases, the numeric `cluster_NN` labels are sufficient for querying.

---

## Phase 4 — Build the Graph

Use `--kmeans-model` to enable embedding-based topic assignment. Every chunk is embedded
at build time and assigned to its nearest centroid — no keywords required.

```bash
dockg build-graph \
  --repo /path/to/corpus \
  --chunk-strategy verse \
  --kmeans-model /path/to/corpus/discovered_topics.kmeans.joblib
```

**Or build + index in one step:**

```bash
dockg build \
  --repo /path/to/corpus \
  --chunk-strategy verse \
  --kmeans-model /path/to/corpus/discovered_topics.kmeans.joblib
```

**Actual results — KJV Bible:**

| Metric | Value |
|---|---|
| Files processed | 2 |
| Chunks produced | 6,630 |
| Topic nodes | 16 |
| Chunks with topic | **6,630 (100%)** |
| Total nodes | 12,936 |
| Total edges | 201,755 |
| Build time | ~14 seconds (graph only) |

**Comparison — keyword matching vs K-means:**

| Method | Coverage | Speed | Requires |
|---|---|---|---|
| Keyword catalog (default) | ~7% | Fast | Hand-written YAML |
| `--topics-file` (user YAML) | ~15–40% | Fast | Reviewed YAML |
| `--kmeans-model` | **~100%** | Moderate (embedding) | `discover-topics` first |

---

## Phase 5 — Query the Verse Graph

After building, use the standard DocKG MCP tools or CLI to explore the graph.

### Find chunks about a specific theme

```bash
dockg query "covenant with Abraham"
```

### Get the text of relevant passages

```bash
dockg pack "law and commandments" --top 10
```

### Explore topic clusters

```python
# MCP — find all chunks in the Psalms cluster
query_docs("devotional meditation praise", rels="HAS_TOPIC")
```

### Navigate by verse metadata

Verse chunks carry structured metadata: `book`, `chapter`, `verse_start`, `verse_end`.
These are stored as SQLite columns and can be queried directly:

```python
# All chunks from Genesis chapter 1
query_docs("creation genesis beginning", hop=0, k=12)
```

---

## Per-Path Topic Overrides (Multi-Corpus)

When your corpus mixes verse and prose files, route different topic catalogs to different paths:

```bash
dockg build-graph \
  --repo /path/to/corpus \
  --chunk-strategy semantic \
  --topics-prefix "sacred-texts/=sacred_texts_topics.yaml" \
  --topics-prefix "docs/=software_topics.yaml"
```

First matching prefix wins. Files that match no prefix fall back to `--topics-file`
or the built-in default catalog.

---

## Complete Command Reference

```bash
# Step 1: Discover topics (one-time per corpus)
dockg pipeline discover-topics \
  --repo /path/to/corpus \
  --output discovered_topics.yaml \
  --n-clusters 16 \
  --chunk-strategy verse \
  --sentences 5

# Step 2: (Optional) Review discovered_topics.yaml, rename cluster labels

# Step 3: Build the graph with K-means topic assignment
dockg build-graph \
  --repo /path/to/corpus \
  --chunk-strategy verse \
  --kmeans-model discovered_topics.kmeans.joblib

# Step 4: Build the vector index (for semantic search)
dockg build-index --repo /path/to/corpus

# Step 5: Query
dockg query "covenant law commandment"
dockg pack "psalms praise worship"

# OR: Build graph + index in one step (Steps 3+4)
dockg build \
  --repo /path/to/corpus \
  --chunk-strategy verse \
  --kmeans-model discovered_topics.kmeans.joblib
```

---

## Verse Chunk Schema

Each verse chunk node carries the following metadata fields:

| Field | Type | Example |
|---|---|---|
| `id` | str | `chunk:sacred-texts/the_bible.md:0042` |
| `kind` | str | `chunk` |
| `content_type` | str | `verse` |
| `book` | str | `Genesis` |
| `chapter` | int | `1` |
| `verse_start` | int | `1` |
| `verse_end` | int | `5` |
| `text` | str | `1:1 In the beginning... 1:5 And God called...` |

---

## Tips and Troubleshooting

**"My corpus produces very few chunks"**
- Confirm `VerseChunker.is_verse_document()` triggers: >10% of non-blank lines must match `^\d+:\d+\s`
- Force verse mode: `--chunk-strategy verse`

**"My cluster keywords look like noise"**
- Increase `--n-keywords` (default 15) to see more terms per cluster
- Add domain stop-words to the `_TFIDF_STOPWORDS` set in `discover_topics.py`

**"I want finer-grained topics"**
- Increase `--n-clusters` (try 24 or 32 for a 66-book corpus)
- Watch for sparse clusters (flagged ⚠ in the discover-topics table)

**"Build takes too long"**
- Use `build-graph` (graph only, no vectors) then `build-index` separately
- Reduce `--n-clusters` to speed up K-means

**"My topics look wrong after renaming"**
- Renaming YAML labels does not move centroids; only the display name changes
- Rebuild with the renamed YAML as `--topics-file` to use keyword matching on renamed labels
- For embedding-based 100% coverage, re-run `discover-topics` after any YAML edits
