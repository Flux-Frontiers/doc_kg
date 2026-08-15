# DocKG Benchmark — LongMemEval

**Evaluates DocKG retrieval against LongMemEval.**
Goal: maximum session-level recall using pure graph retrieval — no LLM, no inference, no rerank.

---

## Architecture

Every unique haystack session across all 500 questions is written once as
`<session_id>.md` under `benchmarks/data/longmemeval_corpus/`. A single DocKG
is built from that corpus (SQLite graph + sqlite-vec vector index), then all 500
queries run against it — ingest once, query many.

Retrieval path: `DocKG.query(q, k, hop, rels, max_nodes)` — the same
semantic-seed + graph-expansion path that `pack_docs` uses:

1. sqlite-vec ANN search → top-k semantic seed nodes
2. Graph expansion across edge types (CONTAINS, NEXT, SIMILAR_TO, HAS_TOPIC,
   MENTIONS_ENTITY, HAS_KEYWORD, CO_OCCURS_WITH, REFERENCES)
3. Ranked nodes collapsed to session IDs via `file_path`
4. Post-filtered to the question's `haystack_session_ids`

No keyword rerank. No LLM rerank. The graph is the retrieval engine.

---

## Setup

```bash
# Install DocKG
cd /Users/egs/repos/doc_kg
poetry install
```

---

## Step 0 — Download the Dataset (one time, ~50 MB)

```bash
python benchmarks/longmemeval_dockg.py prepare \
  /tmp/longmemeval-data/longmemeval_s_cleaned.json \
  --download
```

Or manually:

```bash
mkdir -p /tmp/longmemeval-data
curl -fsSL -o /tmp/longmemeval-data/longmemeval_s_cleaned.json \
  https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_s_cleaned.json
```

---

## Step 1 — Prepare Corpus + Build the KG (one time)

```bash
python benchmarks/longmemeval_dockg.py prepare \
  /tmp/longmemeval-data/longmemeval_s_cleaned.json
```

Writes every unique haystack session as a Markdown file, then builds the
persistent DocKG. Takes several minutes on first run.

**Rebuild from scratch** (after code or corpus changes):

```bash
python benchmarks/longmemeval_dockg.py prepare \
  /tmp/longmemeval-data/longmemeval_s_cleaned.json \
  --wipe
```

---

## Step 2 — Run the Benchmark (repeatable — KG is reused)

```bash
# Default parameters (k=50, hop=2, max_nodes=1000)
python benchmarks/longmemeval_dockg.py run \
  /tmp/longmemeval-data/longmemeval_s_cleaned.json

# Quick smoke test — first 20 questions
python benchmarks/longmemeval_dockg.py run \
  /tmp/longmemeval-data/longmemeval_s_cleaned.json --limit 20

# Tune graph-expansion parameters
python benchmarks/longmemeval_dockg.py run \
  /tmp/longmemeval-data/longmemeval_s_cleaned.json \
  --k 50 --hop 2 --max-nodes 1000

# Restrict edge types
python benchmarks/longmemeval_dockg.py run \
  /tmp/longmemeval-data/longmemeval_s_cleaned.json \
  --rels CONTAINS,NEXT,SIMILAR_TO,HAS_TOPIC,MENTIONS_ENTITY,HAS_KEYWORD,CO_OCCURS_WITH

# Save per-question results to JSONL
python benchmarks/longmemeval_dockg.py run \
  /tmp/longmemeval-data/longmemeval_s_cleaned.json \
  --out benchmarks/results_dockg.jsonl
```

---

## All-in-One (prepare + run)

```bash
python benchmarks/longmemeval_dockg.py all \
  /tmp/longmemeval-data/longmemeval_s_cleaned.json \
  --download
```

---

## Parameters

| Flag | Default | Description |
|---|---|---|
| `--download` | off | Download dataset from HuggingFace if not present |
| `--wipe` | off | Rewrite corpus files and rebuild KG from scratch |
| `--k` | 50 | Semantic seed count (vector top-K before graph expansion) |
| `--hop` | 2 | Graph expansion hops from each seed |
| `--max-nodes` | 1000 | Cap on ranked nodes returned by `DocKG.query` |
| `--rels` | all | Comma-separated edge types to traverse |
| `--limit` | 0 (all) | Limit to first N questions |
| `--skip` | 0 | Skip first N questions |
| `--model` | default | Override sentence-transformer model (prepare only) |
| `--out` | none | Save per-question results to JSONL |

---

## Metrics Reported

- **Recall@K** — fraction of questions where the correct session appears in top-K results
- **NDCG@K** — normalized discounted cumulative gain at K
- Reported at K = 1, 3, 5, 10, 30, 50
- Per-type breakdown by LongMemEval question category

---

## Comparison vs MemPal Baseline

| System | R@5 | LLM Required | Notes |
|---|---|---|---|
| MemPal raw (ChromaDB) | 96.6% | None | Reference baseline |
| MemPal hybrid v4 + Haiku rerank | 100% | Haiku | Best published score |
| **DocKG (graph retrieval)** | TBD | **None** | This benchmark |

DocKG's retrieval is structurally richer than raw ChromaDB: beyond cosine
similarity it traverses topic, entity, keyword, and similarity edges, and uses
the document hierarchy (document → section → chunk). The hypothesis is that
graph expansion recovers sessions that pure embedding search misses.

---

## Data Location

| Artifact | Path |
|---|---|
| Dataset | `/tmp/longmemeval-data/longmemeval_s_cleaned.json` |
| Corpus (Markdown sessions) | `benchmarks/data/longmemeval_corpus/` |
| DocKG SQLite graph | `benchmarks/data/.dockg/graph.sqlite` |
| DocKG vector index | `benchmarks/data/.dockg/vectors.sqlite` |
| Results JSONL | `benchmarks/results_dockg.jsonl` (if `--out` used) |
