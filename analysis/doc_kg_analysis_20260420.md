> **Analysis Report Metadata**
> - **Generated:** 2026-04-20T17:42:20Z
> - **Version:** pycode-kg 0.14.0
> - **Commit:** 13d64d9 (main)
> - **Platform:** macOS 26.4.1 | arm64 (arm) | Turing | Python 3.12.13
> - **Graph:** 4296 nodes · 4099 edges (324 meaningful)
> - **Included directories:** src
> - **Excluded directories:** tests
> - **Elapsed time:** 4s

# doc_kg Analysis

**Generated:** 2026-04-20 17:42:20 UTC

---

## Executive Summary

This report provides a comprehensive architectural analysis of the **doc_kg** repository using PyCodeKG's knowledge graph. The analysis covers complexity hotspots, module coupling, key call chains, and code quality signals to guide refactoring and architecture decisions.

| Overall Quality | Grade | Score |
|----------------|-------|-------|
| [C] **Fair** | **C** | 70 / 100 |

---

## Baseline Metrics

| Metric | Value |
|--------|-------|
| **Total Nodes** | 4296 |
| **Total Edges** | 4099 |
| **Modules** | 36 (of 36 total) |
| **Functions** | 88 |
| **Classes** | 39 |
| **Methods** | 161 |

### Edge Distribution

| Relationship Type | Count |
|-------------------|-------|
| CALLS | 1488 |
| CONTAINS | 288 |
| IMPORTS | 274 |
| ATTR_ACCESS | 1278 |
| INHERITS | 3 |

---

## Fan-In Ranking

Most-called functions are potential bottlenecks or core functionality. These functions are heavily depended upon across the codebase.

| # | Function | Module | Callers |
|---|----------|--------|---------|
| 1 | `close()` | src/doc_kg/kg.py | **11** |
| 2 | `close()` | src/doc_kg/store.py | **11** |
| 3 | `con()` | src/doc_kg/store.py | **10** |
| 4 | `store()` | src/doc_kg/kg.py | **8** |
| 5 | `_rewrap()` | src/doc_kg/snapshots.py | **5** |
| 6 | `index()` | src/doc_kg/kg.py | **5** |
| 7 | `_extract_links()` | src/doc_kg/chunker.py | **4** |
| 8 | `_get_kg()` | src/doc_kg/mcp_server.py | **4** |
| 9 | `embed_texts()` | src/doc_kg/index.py | **4** |
| 10 | `to_json()` | src/doc_kg/kg.py | **4** |
| 11 | `to_markdown()` | src/doc_kg/kg.py | **4** |
| 12 | `suppress_ingestion_logging()` | src/doc_kg/index.py | **4** |
| 13 | `extract()` | src/doc_kg/graph.py | **3** |
| 14 | `_slug()` | src/doc_kg/relations.py | **3** |
| 15 | `to_dict()` | src/doc_kg/kg.py | **3** |


**Insight:** Functions with high fan-in are either core APIs or bottlenecks. Review these for:
- Thread safety and performance
- Clear documentation and contracts
- Potential for breaking changes

---

## High Fan-Out Functions (Orchestrators)

Functions that call many others may indicate complex orchestration logic or poor separation of concerns.

No extreme high fan-out functions detected. Well-balanced architecture.

---

## Module Architecture

Top modules by dependency coupling and cohesion (showing up to 10 with activity).
Cohesion = incoming / (incoming + outgoing + 1); higher = more internally focused.

| Module | Functions | Classes | Incoming | Outgoing | Cohesion |
|--------|-----------|---------|----------|----------|----------|
| `src/doc_kg/kg.py` | 2 | 4 | 9 | 3 | 0.23 |
| `src/doc_kg/index.py` | 6 | 4 | 3 | 0 | 0.00 |
| `src/doc_kg/snapshots.py` | 5 | 4 | 1 | 0 | 0.00 |
| `src/doc_kg/store.py` | 1 | 2 | 6 | 1 | 0.12 |
| `src/doc_kg/dockg_semantic_analysis.py` | 5 | 4 | 1 | 2 | 0.50 |
| `src/doc_kg/chunker.py` | 5 | 2 | 1 | 0 | 0.00 |
| `src/doc_kg/dockg_thorough_analysis.py` | 5 | 2 | 2 | 2 | 0.40 |
| `src/doc_kg/sampler.py` | 0 | 3 | 1 | 0 | 0.00 |
| `src/doc_kg/embedder_worker.py` | 2 | 2 | 0 | 0 | 0.00 |
| `src/doc_kg/dockg.py` | 9 | 2 | 4 | 2 | 0.29 |

---

## Key Call Chains

Deepest call chains in the codebase.

**Chain 1** (depth: 3)

```
__exit__ → close → close
```

**Chain 2** (depth: 3)

```
build_graph → store → GraphStore
```

---

## Public API Surface

Identified public APIs (module-level functions with high usage).

| Function | Module | Fan-In | Type |
|----------|--------|--------|------|
| `DocKG()` | src/doc_kg/kg.py | 10 | class |
| `SnapshotManager()` | src/doc_kg/snapshots.py | 5 | class |
| `suppress_ingestion_logging()` | src/doc_kg/index.py | 4 | function |
| `query()` | src/doc_kg/cli/cmd_query.py | 3 | function |
| `build()` | src/doc_kg/cli/cmd_build.py | 3 | function |
| `pack()` | src/doc_kg/cli/cmd_query.py | 3 | function |
| `BuildStats()` | src/doc_kg/kg.py | 3 | class |
| `GraphStore()` | src/doc_kg/store.py | 3 | class |
| `SentenceTransformerEmbedder()` | src/doc_kg/index.py | 3 | class |
| `extract_entities()` | src/doc_kg/relations.py | 2 | function |
---

## Docstring Coverage

Docstring coverage directly determines semantic retrieval quality. Nodes without
docstrings embed only structured identifiers (`KIND/NAME/QUALNAME/MODULE`), where
keyword search is as effective as vector embeddings. The semantic model earns its
value only when a docstring is present.

| Kind | Documented | Total | Coverage |
|------|-----------|-------|----------|
| `function` | 69 | 88 | [WARN] 78.4% |
| `method` | 111 | 161 | [WARN] 68.9% |
| `class` | 39 | 39 | [OK] 100.0% |
| `module` | 35 | 36 | [OK] 97.2% |
| **total** | **254** | **324** | **[WARN] 78.4%** |

> **Recommendation:** 70 nodes lack docstrings. Prioritize documenting high-fan-in functions and public API surface first — these have the highest impact on query accuracy.

---

## Structural Importance Ranking (SIR)

Weighted PageRank aggregated by module — reveals architectural spine. Cross-module edges boosted 1.5×; private symbols penalized 0.85×. Node-level detail: `pycodekg centrality --top 25`

| Rank | Score | Members | Module |
|------|-------|---------|--------|
| 1 | 0.174417 | 2 | `src/doc_kg/cli/group.py` |
| 2 | 0.122605 | 34 | `src/doc_kg/kg.py` |
| 3 | 0.121233 | 23 | `src/doc_kg/store.py` |
| 4 | 0.071765 | 24 | `src/doc_kg/snapshots.py` |
| 5 | 0.070643 | 27 | `src/doc_kg/index.py` |
| 6 | 0.054959 | 20 | `src/doc_kg/chunker.py` |
| 7 | 0.043102 | 16 | `src/doc_kg/sampler.py` |
| 8 | 0.039565 | 22 | `src/doc_kg/dockg_semantic_analysis.py` |
| 9 | 0.036091 | 13 | `src/doc_kg/embedder_worker.py` |
| 10 | 0.034432 | 9 | `src/doc_kg/graph.py` |
| 11 | 0.032225 | 12 | `src/doc_kg/dockg.py` |
| 12 | 0.031806 | 18 | `src/doc_kg/dockg_thorough_analysis.py` |
| 13 | 0.031106 | 11 | `src/doc_kg/topics.py` |
| 14 | 0.022528 | 12 | `src/doc_kg/pipeline.py` |
| 15 | 0.017991 | 7 | `src/doc_kg/relations.py` |



---

## Code Quality Issues

- [WARN] Moderate docstring coverage (78.4%) — semantic retrieval quality is degraded for undocumented nodes; BM25 is as effective as embeddings without docstrings
- [WARN] 1 orphaned functions found (`main`) -- consider archiving or documenting

---

## Architectural Strengths

- Well-structured with 15 core functions identified
- No god objects or god functions detected

---

## Recommendations

### Immediate Actions
1. **Improve docstring coverage** — 70 nodes lack docstrings; prioritize high-fan-in functions and public APIs first for maximum semantic retrieval gain
2. **Remove or archive orphaned functions** — `main` have zero callers and add maintenance burden

### Medium-term Refactoring
1. **Harden high fan-in functions** — `close`, `close`, `con` are widely depended upon; review for thread safety, clear contracts, and stable interfaces
2. **Reduce module coupling** — consider splitting tightly coupled modules or introducing interface boundaries
3. **Add tests for key call chains** — the identified call chains represent well-traveled execution paths that benefit most from regression coverage

### Long-term Architecture
1. **Version and stabilize the public API** — document breaking-change policies for `DocKG`, `SnapshotManager`, `suppress_ingestion_logging`
2. **Enforce layer boundaries** — add linting or CI checks to prevent unexpected cross-module dependencies as the codebase grows
3. **Monitor hot paths** — instrument the high fan-in functions identified here to catch performance regressions early

---

## Inheritance Hierarchy

**3** INHERITS edges across **4** classes. Max depth: **1**.

| Class | Module | Depth | Parents | Children |
|-------|--------|-------|---------|----------|
| `SentenceTransformerEmbedder` | src/doc_kg/index.py | 1 | 1 | 0 |
| `Embedder` | src/doc_kg/index.py | 0 | 0 | 1 |
| `Snapshot` | src/doc_kg/snapshots.py | 0 | 1 | 0 |
| `SnapshotManager` | src/doc_kg/snapshots.py | 0 | 1 | 0 |


---

## Snapshot History

No snapshots found. Run `pycodekg snapshot save <version>` to capture one.


---

## Appendix: Orphaned Code

Functions with zero callers (potential dead code):

| Function | Module | Lines |
|----------|--------|-------|
| `main()` | src/doc_kg/app.py | 110 |
---

## CodeRank -- Global Structural Importance

Weighted PageRank over CALLS + IMPORTS + INHERITS edges (test paths excluded). Scores are normalized to sum to 1.0. This ranking seeds Phase 2 fan-in discovery and Phase 15 concern queries.

| Rank | Score | Kind | Name | Module |
|------|-------|------|------|--------|
| 1 | 0.000831 | method | `DocGraph.extract` | src/doc_kg/graph.py |
| 2 | 0.000776 | method | `GraphStore.con` | src/doc_kg/store.py |
| 3 | 0.000682 | method | `DocKG.store` | src/doc_kg/kg.py |
| 4 | 0.000666 | function | `_rewrap` | src/doc_kg/snapshots.py |
| 5 | 0.000655 | function | `_slug` | src/doc_kg/relations.py |
| 6 | 0.000531 | function | `_extract_links` | src/doc_kg/chunker.py |
| 7 | 0.000504 | method | `TextPack.to_dict` | src/doc_kg/kg.py |
| 8 | 0.000476 | method | `DocKG.embedder` | src/doc_kg/kg.py |
| 9 | 0.000462 | function | `_get_kg` | src/doc_kg/mcp_server.py |
| 10 | 0.000445 | function | `_embed_shard` | src/doc_kg/embedder_worker.py |
| 11 | 0.000441 | function | `_groups_to_chunks` | src/doc_kg/chunker.py |
| 12 | 0.000426 | function | `_load_store` | src/doc_kg/app.py |
| 13 | 0.000416 | function | `_split_sentences` | src/doc_kg/chunker.py |
| 14 | 0.000410 | method | `SentenceGroupChunker._sentence_group_chunks` | src/doc_kg/chunker.py |
| 15 | 0.000406 | method | `GraphStore.close` | src/doc_kg/store.py |
| 16 | 0.000406 | method | `SentenceTransformerEmbedder.embed_texts` | src/doc_kg/index.py |
| 17 | 0.000406 | method | `TopicExtractor._load_topic_map` | src/doc_kg/topics.py |
| 18 | 0.000406 | method | `DocKG.close` | src/doc_kg/kg.py |
| 19 | 0.000392 | class | `ThemeSummary` | src/doc_kg/dockg_semantic_analysis.py |
| 20 | 0.000384 | method | `DocKG.index` | src/doc_kg/kg.py |

---

## Concern-Based Hybrid Ranking

Top structurally-dominant nodes per architectural concern (0.60 × semantic + 0.25 × CodeRank + 0.15 × graph proximity).

### Configuration Loading Initialization Setup

| Rank | Score | Kind | Name | Module |
|------|-------|------|------|--------|
| 1 | 0.7749 | function | `_load_store` | src/doc_kg/app.py |
| 2 | 0.75 | method | `ProvMeta.__init__` | src/doc_kg/store.py |
| 3 | 0.7457 | method | `DocKG.__init__` | src/doc_kg/kg.py |
| 4 | 0.7429 | function | `_init_state` | src/doc_kg/app.py |
| 5 | 0.7423 | method | `SentenceGroupChunker.__init__` | src/doc_kg/chunker.py |

### Data Persistence Storage Database

| Rank | Score | Kind | Name | Module |
|------|-------|------|------|--------|
| 1 | 0.8179 | method | `DocKG.store` | src/doc_kg/kg.py |
| 2 | 0.7138 | method | `GraphStore.write` | src/doc_kg/store.py |
| 3 | 0.7123 | method | `SemanticIndex.build_from_cache` | src/doc_kg/index.py |
| 4 | 0.7065 | method | `SemanticIndex.precompute_embeddings` | src/doc_kg/index.py |
| 5 | 0.7056 | method | `SnapshotManager.save_snapshot` | src/doc_kg/snapshots.py |

### Query Search Retrieval Semantic

| Rank | Score | Kind | Name | Module |
|------|-------|------|------|--------|
| 1 | 0.75 | method | `SemanticIndex.search` | src/doc_kg/index.py |
| 2 | 0.7102 | function | `query` | src/doc_kg/cli/cmd_query.py |
| 3 | 0.7007 | method | `DocKG.query` | src/doc_kg/kg.py |
| 4 | 0.6487 | class | `QueryResult` | src/doc_kg/kg.py |
| 5 | 0.6464 | class | `SemanticIndex` | src/doc_kg/index.py |

### Graph Traversal Node Edge

| Rank | Score | Kind | Name | Module |
|------|-------|------|------|--------|
| 1 | 0.7525 | method | `DocGraph.edges` | src/doc_kg/graph.py |
| 2 | 0.7503 | method | `SemanticIndex._discover_similar_edges` | src/doc_kg/index.py |
| 3 | 0.75 | method | `GraphStore.edges_from` | src/doc_kg/store.py |
| 4 | 0.7446 | method | `GraphStore.edges_within` | src/doc_kg/store.py |
| 5 | 0.7389 | method | `DocGraph.result` | src/doc_kg/graph.py |



---

*Report generated by PyCodeKG Thorough Analysis Tool — analysis completed in 4.2s*
