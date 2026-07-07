> **Analysis Report Metadata**
> - **Generated:** 2026-06-24T17:57:42Z
> - **Version:** pycode-kg 0.19.3
> - **Commit:** 703270d (main)
> - **Platform:** macOS 27.0 | arm64 (arm) | turing | Python 3.12.13
> - **Graph:** 5286 nodes · 4930 edges (357 meaningful)
> - **Included directories:** src
> - **Excluded directories:** tests
> - **Elapsed time:** 5s

# doc_kg Analysis

**Generated:** 2026-06-24 17:57:42 UTC

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
| **Total Nodes** | 5286 |
| **Total Edges** | 4930 |
| **Modules** | 39 (of 39 total) |
| **Functions** | 109 |
| **Classes** | 38 |
| **Methods** | 171 |

### Edge Distribution

| Relationship Type | Count |
|-------------------|-------|
| CALLS | 1875 |
| CONTAINS | 318 |
| IMPORTS | 316 |
| ATTR_ACCESS | 1523 |
| INHERITS | 2 |

---

## Fan-In Ranking

Most-called functions are potential bottlenecks or core functionality. These functions are heavily depended upon across the codebase.

| # | Function | Module | Callers |
|---|----------|--------|---------|
| 1 | `close()` | src/doc_kg/kg.py | **17** |
| 2 | `close()` | src/doc_kg/store.py | **17** |
| 3 | `con()` | src/doc_kg/store.py | **16** |
| 4 | `store()` | src/doc_kg/kg.py | **9** |
| 5 | `suppress_ingestion_logging()` | src/doc_kg/index.py | **6** |
| 6 | `_rewrap()` | src/doc_kg/snapshots.py | **5** |
| 7 | `to_markdown()` | src/doc_kg/kg.py | **5** |
| 8 | `_extract_links()` | src/doc_kg/chunker.py | **4** |
| 9 | `_get_kg()` | src/doc_kg/mcp_server.py | **4** |
| 10 | `_row_to_node()` | src/doc_kg/store.py | **4** |
| 11 | `index()` | src/doc_kg/kg.py | **4** |
| 12 | `to_json()` | src/doc_kg/kg.py | **4** |
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
| `src/doc_kg/kg.py` | 6 | 4 | 9 | 3 | 0.69 |
| `src/doc_kg/store.py` | 4 | 2 | 7 | 1 | 0.78 |
| `src/doc_kg/chunker.py` | 6 | 3 | 1 | 0 | 0.50 |
| `src/doc_kg/snapshots.py` | 5 | 4 | 1 | 0 | 0.50 |
| `src/doc_kg/index.py` | 8 | 2 | 2 | 0 | 0.67 |
| `src/doc_kg/dockg_semantic_analysis.py` | 5 | 4 | 1 | 2 | 0.25 |
| `src/doc_kg/dockg_thorough_analysis.py` | 5 | 2 | 2 | 2 | 0.40 |
| `src/doc_kg/sampler.py` | 0 | 3 | 1 | 0 | 0.50 |
| `src/doc_kg/dockg.py` | 10 | 2 | 4 | 2 | 0.57 |
| `src/doc_kg/embedder_worker.py` | 2 | 2 | 0 | 0 | 0.00 |

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
| `DocKG()` | src/doc_kg/kg.py | 13 | class |
| `suppress_ingestion_logging()` | src/doc_kg/index.py | 6 | function |
| `SnapshotManager()` | src/doc_kg/snapshots.py | 5 | class |
| `GraphStore()` | src/doc_kg/store.py | 5 | class |
| `pack()` | src/doc_kg/cli/cmd_query.py | 3 | function |
| `BuildStats()` | src/doc_kg/kg.py | 3 | class |
| `build()` | src/doc_kg/cli/cmd_build.py | 2 | function |
| `DocEdge()` | src/doc_kg/dockg.py | 2 | class |
| `TopicExtractor()` | src/doc_kg/topics.py | 2 | class |
| `main()` | src/doc_kg/dockg_semantic_analysis.py | 1 | function |
---

## Docstring Coverage

Docstring coverage directly determines semantic retrieval quality. Nodes without
docstrings embed only structured identifiers (`KIND/NAME/QUALNAME/MODULE`), where
keyword search is as effective as vector embeddings. The semantic model earns its
value only when a docstring is present.

| Kind | Documented | Total | Coverage |
|------|-----------|-------|----------|
| `function` | 86 | 109 | [WARN] 78.9% |
| `method` | 122 | 171 | [WARN] 71.3% |
| `class` | 38 | 38 | [OK] 100.0% |
| `module` | 38 | 39 | [OK] 97.4% |
| **total** | **284** | **357** | **[WARN] 79.6%** |

> **Recommendation:** 73 nodes lack docstrings. Prioritize documenting high-fan-in functions and public API surface first — these have the highest impact on query accuracy.

---

## Structural Importance Ranking (SIR)

Weighted PageRank aggregated by module — reveals architectural spine. Cross-module edges boosted 1.5×; private symbols penalized 0.85×. Node-level detail: `pycodekg centrality --top 25`

| Rank | Score | Members | Module |
|------|-------|---------|--------|
| 1 | 0.179150 | 2 | `src/doc_kg/cli/group.py` |
| 2 | 0.144733 | 32 | `src/doc_kg/store.py` |
| 3 | 0.133259 | 39 | `src/doc_kg/kg.py` |
| 4 | 0.066662 | 28 | `src/doc_kg/chunker.py` |
| 5 | 0.064837 | 25 | `src/doc_kg/snapshots.py` |
| 6 | 0.046049 | 23 | `src/doc_kg/index.py` |
| 7 | 0.038589 | 16 | `src/doc_kg/sampler.py` |
| 8 | 0.035439 | 22 | `src/doc_kg/dockg_semantic_analysis.py` |
| 9 | 0.031727 | 13 | `src/doc_kg/embedder_worker.py` |
| 10 | 0.031657 | 9 | `src/doc_kg/graph.py` |
| 11 | 0.029921 | 13 | `src/doc_kg/dockg.py` |
| 12 | 0.028480 | 18 | `src/doc_kg/dockg_thorough_analysis.py` |
| 13 | 0.027727 | 11 | `src/doc_kg/topics.py` |
| 14 | 0.020156 | 12 | `src/doc_kg/pipeline.py` |
| 15 | 0.015772 | 10 | `src/doc_kg/manifold.py` |



---

## Code Quality Issues

- [WARN] Moderate docstring coverage (79.6%) — semantic retrieval quality is degraded for undocumented nodes; BM25 is as effective as embeddings without docstrings
- [WARN] 2 orphaned functions found (`main`, `_silent_init`) -- consider archiving or documenting
- [WARN] `kg.py` has 38 functions/methods/classes -- consider splitting into focused submodules
- [WARN] `store.py` has 31 functions/methods/classes -- consider splitting into focused submodules

---

## Architectural Strengths

- Well-structured with 15 core functions identified
- No god objects or god functions detected

---

## Recommendations

### Immediate Actions
1. **Improve docstring coverage** — 73 nodes lack docstrings; prioritize high-fan-in functions and public APIs first for maximum semantic retrieval gain
2. **Remove or archive orphaned functions** — `main`, `_silent_init` have zero callers and add maintenance burden

### Medium-term Refactoring
1. **Harden high fan-in functions** — `close`, `close`, `con` are widely depended upon; review for thread safety, clear contracts, and stable interfaces
2. **Reduce module coupling** — consider splitting tightly coupled modules or introducing interface boundaries
3. **Add tests for key call chains** — the identified call chains represent well-traveled execution paths that benefit most from regression coverage

### Long-term Architecture
1. **Version and stabilize the public API** — document breaking-change policies for `DocKG`, `suppress_ingestion_logging`, `SnapshotManager`
2. **Enforce layer boundaries** — add linting or CI checks to prevent unexpected cross-module dependencies as the codebase grows
3. **Monitor hot paths** — instrument the high fan-in functions identified here to catch performance regressions early

---

## Inheritance Hierarchy

**2** INHERITS edges across **2** classes. Max depth: **0**.

| Class | Module | Depth | Parents | Children |
|-------|--------|-------|---------|----------|
| `Snapshot` | src/doc_kg/snapshots.py | 0 | 1 | 0 |
| `SnapshotManager` | src/doc_kg/snapshots.py | 0 | 1 | 0 |


---

## Snapshot History

Recent snapshots in reverse chronological order. Δ columns show change vs. the immediately preceding snapshot.

| # | Timestamp | Branch | Version | Nodes | Edges | Coverage | Δ Nodes | Δ Edges | Δ Coverage |
|---|-----------|--------|---------|-------|-------|----------|---------|---------|------------|
| 1 | 2026-06-10 23:48:11 | main | 0.15.8 | 5286 | 4930 | 79.6% | +918 | +758 | +0.8% |
| 2 | 2026-05-04 14:08:03 | main | 0.14.0 | 4368 | 4172 | 78.8% | — | — | — |


---

## Appendix: Orphaned Code

Functions with zero callers (potential dead code):

| Function | Module | Lines |
|----------|--------|-------|
| `main()` | src/doc_kg/app.py | 110 |
| `_silent_init()` | src/doc_kg/index.py | 2 |
---

## CodeRank -- Global Structural Importance

Weighted PageRank over CALLS + IMPORTS + INHERITS edges (test paths excluded). Scores are normalized to sum to 1.0. This ranking seeds Phase 2 fan-in discovery and Phase 15 concern queries.

| Rank | Score | Kind | Name | Module |
|------|-------|------|------|--------|
| 1 | 0.000916 | method | `GraphStore.con` | src/doc_kg/store.py |
| 2 | 0.000679 | method | `DocGraph.extract` | src/doc_kg/graph.py |
| 3 | 0.000540 | function | `_rewrap` | src/doc_kg/snapshots.py |
| 4 | 0.000535 | function | `_slug` | src/doc_kg/relations.py |
| 5 | 0.000512 | method | `DocKG.store` | src/doc_kg/kg.py |
| 6 | 0.000434 | function | `_extract_links` | src/doc_kg/chunker.py |
| 7 | 0.000412 | method | `TextPack.to_dict` | src/doc_kg/kg.py |
| 8 | 0.000385 | method | `DocKG.embedder` | src/doc_kg/kg.py |
| 9 | 0.000378 | function | `_get_kg` | src/doc_kg/mcp_server.py |
| 10 | 0.000363 | function | `_embed_shard` | src/doc_kg/embedder_worker.py |
| 11 | 0.000360 | function | `_groups_to_chunks` | src/doc_kg/chunker.py |
| 12 | 0.000348 | function | `_load_store` | src/doc_kg/app.py |
| 13 | 0.000340 | function | `_split_sentences` | src/doc_kg/chunker.py |
| 14 | 0.000335 | function | `_row_to_node` | src/doc_kg/store.py |
| 15 | 0.000335 | method | `SentenceGroupChunker._sentence_group_chunks` | src/doc_kg/chunker.py |
| 16 | 0.000332 | method | `GraphStore.close` | src/doc_kg/store.py |
| 17 | 0.000332 | method | `TopicExtractor._load_topic_map` | src/doc_kg/topics.py |
| 18 | 0.000332 | method | `DocKG.close` | src/doc_kg/kg.py |
| 19 | 0.000320 | class | `ThemeSummary` | src/doc_kg/dockg_semantic_analysis.py |
| 20 | 0.000308 | method | `DocKG.index` | src/doc_kg/kg.py |

---

## Concern-Based Hybrid Ranking

Top structurally-dominant nodes per architectural concern (0.60 × semantic + 0.25 × CodeRank + 0.15 × graph proximity).

### Configuration Loading Initialization Setup

| Rank | Score | Kind | Name | Module |
|------|-------|------|------|--------|
| 1 | 0.7693 | function | `_load_store` | src/doc_kg/app.py |
| 2 | 0.75 | method | `ProvMeta.__init__` | src/doc_kg/store.py |
| 3 | 0.7492 | method | `DocKG.__init__` | src/doc_kg/kg.py |
| 4 | 0.7446 | function | `_init_state` | src/doc_kg/app.py |
| 5 | 0.7446 | method | `SentenceGroupChunker.__init__` | src/doc_kg/chunker.py |

### Data Persistence Storage Database

| Rank | Score | Kind | Name | Module |
|------|-------|------|------|--------|
| 1 | 0.7967 | method | `DocKG.store` | src/doc_kg/kg.py |
| 2 | 0.7143 | method | `GraphStore.write` | src/doc_kg/store.py |
| 3 | 0.712 | method | `SemanticIndex.build_from_cache` | src/doc_kg/index.py |
| 4 | 0.708 | method | `SemanticIndex.precompute_embeddings` | src/doc_kg/index.py |
| 5 | 0.7072 | method | `SnapshotManager.save_snapshot` | src/doc_kg/snapshots.py |

### Query Search Retrieval Semantic

| Rank | Score | Kind | Name | Module |
|------|-------|------|------|--------|
| 1 | 0.75 | method | `SemanticIndex.search` | src/doc_kg/index.py |
| 2 | 0.7363 | method | `GraphStore.search_lexical` | src/doc_kg/store.py |
| 3 | 0.7266 | function | `query` | src/doc_kg/cli/cmd_query.py |
| 4 | 0.6623 | class | `QueryResult` | src/doc_kg/kg.py |
| 5 | 0.6613 | class | `SemanticIndex` | src/doc_kg/index.py |

### Graph Traversal Node Edge

| Rank | Score | Kind | Name | Module |
|------|-------|------|------|--------|
| 1 | 0.75 | method | `GraphStore.expand` | src/doc_kg/store.py |
| 2 | 0.7146 | method | `DocGraph.edges` | src/doc_kg/graph.py |
| 3 | 0.7106 | method | `DocKG.query` | src/doc_kg/kg.py |
| 4 | 0.704 | method | `GraphStore._upsert_edges` | src/doc_kg/store.py |
| 5 | 0.696 | method | `SemanticIndex._discover_similar_edges` | src/doc_kg/index.py |



---

*Report generated by PyCodeKG Thorough Analysis Tool — analysis completed in 5.4s*
