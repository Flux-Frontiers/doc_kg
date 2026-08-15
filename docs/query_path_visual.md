# DocKG Query Path — Visual Description for Image Generation

## One-sentence summary

**A DocKG query fans out into two parallel seed channels — dense vector search (sqlite-vec) and lexical BM25 search (SQLite FTS5) — fuses them with reciprocal rank fusion, expands the fused seeds through the structural graph, then ranks, guards, and trims the result set into a scored context pack.**

> Pipeline version: v0.15.7+ (hybrid seeding, scope pushdown, dual-distance lexical seeds)

---

## Image Generation Prompt (text-to-image / illustration brief)

> A clean, high-contrast technical flow diagram on a dark navy background, oriented top to bottom. At the top center, a rounded input box containing a quoted natural-language query string ("what did Pepys say about the great fire?") with a small magnifying-glass icon. The query splits into two parallel vertical channel columns connected by downward arrows. The left column, labeled "Dense Channel," shows three stacked boxes: "Embed query — bge-small-en-v1.5 (384-d)," "sqlite-vec ANN search — cosine, oversample k×3," and a small gate icon labeled "scope prefilter: starts_with(file_path)." The right column, labeled "Lexical Channel," shows three stacked boxes: "Tokenize — _fts_terms (bare alphanumerics)," "SQLite FTS5 BM25 — exact phrase first, OR-of-terms fallback," and a matching gate icon labeled "scope pushdown: parameterised SQL." Both gate icons are rendered as identical funnel-shaped valves to emphasize symmetric filtering. Between the two columns, a shared horizontal strip labeled "content-type filter" with crossed-out file icons marked "front_matter" and "reference.md." The two channels converge into a central mixing funnel labeled "Reciprocal Rank Fusion — score += 1/(60 + rank)," emitting a row of eight seed circles. Two of the seed circles are visually distinct (teal ring) and carry a split badge showing two numbers: "self_dist ≈ best dense + ε" on the upper half and "neighbour dist = 0.45" on the lower half, with a tiny caption "lexical-only seeds carry two distances." The seed row flows downward into a force-directed graph web labeled "Graph Expansion — hop 1, batched SQL," with nodes connected by thin labeled edges (CONTAINS, NEXT, SIMILAR_TO, HAS_TOPIC, MENTIONS_ENTITY) and provenance arrows showing each expanded node inheriting the distance of the seed that reached it. Below the web, a vertical ranking ladder labeled "Rank — base_dist → hop → boosts → kind," with chunk nodes sorted top to bottom and small "+boost" chips on short chunks. Beneath the ladder, two final gate icons in sequence: "scope guard — _node_in_scope()" and "content filter — drop front_matter/reference," followed by a cutoff bar labeled "max_nodes = 15." At the bottom, an output panel split in two: left half a JSON card labeled "QueryResult — nodes + edges + relevance{score, dist, hop}," right half a document stack labeled "TextPack — ranked excerpts for LLM context." In the lower-right corner, a small inset benchmark panel with two bars: "exact-phrase recall@15: 0.37 → 0.67 (hybrid)" in green and "labeled gold set: −1 pp" in muted gray. Color coding: dense channel and embeddings in amber, lexical channel and FTS5 in teal, fusion and ranking in violet, guards and filters in red-orange, output layer in green. Style: flat design, sans-serif labels, IBM Plex Mono for code names, minimal drop shadows, thin white connector arrows.

---

## Structured Stage Description

### Stage 0 — Input

| Input | Description |
|-------|-------------|
| `q` | Natural-language query string |
| `k` | Seed count (default 8) |
| `hop` | Graph expansion depth (default 1) |
| `max_nodes` | Result cutoff and metric horizon (default 15–25) |
| `source_path_prefixes` | Optional scope: restrict to a corpus subtree (e.g. one genre) |
| `node_kinds` | Optional scope: restrict to node kinds (e.g. `chunk`, `section`) |

Entry points: `DocKG.query()` (nodes + edges) and `DocKG.pack()` (text excerpts). Both seed
via the same `_fused_seeds()` path.

---

### Stage 1 — Two parallel seed channels

#### Dense channel (`SemanticIndex.search`)

1. Embed the query with `BAAI/bge-small-en-v1.5` (384-d, L2-normalised)
2. sqlite-vec ANN search, cosine metric, oversampled to `k × 3` to survive downstream filtering
3. **Scope pushdown:** optional `starts_with(file_path, …)` / `kind IN (…)` prefilter
   (`_lance_where()` — a historical name, now shared by both backends) applied *inside*
   the vector search, so the seed budget is spent entirely on in-scope nodes —
   wildcard-free, literal-prefix semantics

#### Lexical channel (`GraphStore.search_lexical`)

1. Tokenize the query to bare alphanumerics (`_fts_terms`: `Lot's` → `lot`, `s`) so FTS5
   never sees stray query syntax
2. BM25 search over the contentless FTS5 table `nodes_fts` (chunk text only, ≈1× text size)
3. **Exact-phrase query first** (adjacent terms, in order); falls back to OR-of-terms for recall
4. **Scope pushdown:** the same prefix/kind constraints as parameterised SQL
   (`_node_filter_sql()`, `LIKE … ESCAPE`, injection-safe)
5. Degrades to `[]` (dense-only seeding) when the corpus has no FTS index

#### Shared hygiene filter

Both channels drop `reference.md` hits and `content_type ∈ {front_matter, reference}` chunks
via a single batched node fetch before fusion.

---

### Stage 2 — Reciprocal rank fusion (`_fused_seeds`)

- Each channel contributes `1 / (60 + rank)` per node (`_RRF_K = 60`); scores sum for nodes
  found by both
- Top-`k` fused nodes become the seeds
- **Dual-distance lexical seeds:** a seed found only by the lexical channel carries two
  distances —
  - `self_dist` = best dense distance + small per-rank step → the matching chunk itself ranks
    *just behind the best dense hit*
  - `dist` = conservative `_LEXICAL_SEED_BASE_DIST` (0.45) + per-rank step → inherited by the
    seed's expansion neighbourhood
  - Rationale: *an exact lexical match is strong evidence for the matching chunk, weak
    evidence for its structural neighbours.* One BM25 hit can surface itself but cannot flood
    the top-k with its neighbourhood.
- Dense seeds use their real cosine distance for both roles

---

### Stage 3 — Graph expansion (`GraphStore.expand`)

- Batched SQL per hop (temp table + UNION), frontier capped at 5 000 nodes
- Default edge types: `CONTAINS`, `NEXT`, `SIMILAR_TO`, `HAS_TOPIC`, `MENTIONS_ENTITY`,
  `HAS_KEYWORD`, `REFERENCES`
- Provenance per node: which seed reached it (`via_seed`) and at what hop (`best_hop`)

---

### Stage 4 — Ranking

Rank key, in order (`_seed_base_dist()` supplies the first component):

1. **`base_dist`** — a seed's own `self_dist`; an expanded node inherits its `via_seed`'s `dist`
2. **`best_hop`** — fewer hops from a seed wins ties
3. **Boosts** — `semantic_boost` (edge-type weights within the result set) +
   `short_chunk_boost` (surfaces factual asides 50–200 chars; micro-fragments < 50 chars get 0)
4. **Kind priority** — chunks before sections before documents
5. Node id (stable tiebreak)

---

### Stage 5 — Guards and cutoff

Applied in ranked order until `max_nodes` results are kept:

| Guard | Effect |
|-------|--------|
| Content filter | `front_matter` / `reference` nodes excluded from results (still traversable in the graph) |
| Scope guard (`_node_in_scope`) | Drops any node that graph expansion pulled out of the requested subtree/kinds via edges — literal `startswith`, mirroring both pushdown channels |
| Pack dedup (`pack()` only) | Document/section nodes suppressed when their file's chunks are already present |

---

### Stage 6 — Output

| Artifact | Contents |
|----------|----------|
| `QueryResult` | Ranked node dicts (each with `relevance = {score, dist, hop, semantic_boost}`) + edges within the returned set |
| `TextPack` | Same ranking, with per-node text excerpts (`max_chars` cap) rendered as a Markdown context pack for LLM ingestion |

---

## Benchmark validation (`benchmarks/recall_bench.py`)

| Query set | dense-only | hybrid | reading |
|-----------|-----------:|-------:|---------|
| Exact-phrase (60 auto-generated) | 0.367 | **0.667** | +30 pp recall@15 — the lexical channel's purpose |
| Labeled gold (34 human-labeled) | 0.254 | 0.244 | −1 pp — single RRF membership displacement; gold set is dense-biased |

The dual-distance design is what reconciles the two: a single synthetic distance either floods
the top-k with lexical neighbourhoods (0.12: −14 pp gold recall) or buries the exact-phrase hit
itself (flat 0.45: hybrid *lost* to dense on phrases, 0.32 vs 0.37).

---

## ASCII overview

```
                       ┌────────────────────────────┐
                       │   natural-language query    │
                       └──────────────┬──────────────┘
              ┌───────────────────────┴───────────────────────┐
              ▼                                               ▼
   DENSE CHANNEL (sqlite-vec)                     LEXICAL CHANNEL (FTS5)
   embed: bge-small (384-d)                       tokenize: _fts_terms
   ANN cosine, oversample k×3                     BM25: phrase → OR fallback
   scope: starts_with prefilter                   scope: parameterised SQL
              │                                               │
              └──────── drop front_matter / reference ────────┘
                                      │
                                      ▼
                     RRF FUSION  score += 1/(60+rank)
                     lexical-only seeds: self_dist ≈ best-dense+ε
                                         neighbour dist = 0.45
                                      │
                                      ▼
                     GRAPH EXPANSION  (hop 1, batched SQL)
                     CONTAINS · NEXT · SIMILAR_TO · HAS_TOPIC ·
                     MENTIONS_ENTITY  — provenance: via_seed, best_hop
                                      │
                                      ▼
                     RANK  base_dist → hop → boosts → kind
                                      │
                                      ▼
                     GUARDS  content filter → _node_in_scope → max_nodes
                                      │
                       ┌──────────────┴──────────────┐
                       ▼                             ▼
                 QueryResult                     TextPack
            nodes + edges + relevance      ranked excerpts for LLM
```
