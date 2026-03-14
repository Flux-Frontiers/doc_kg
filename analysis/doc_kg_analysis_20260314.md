> **Analysis Report Metadata**
> - **Generated:** 2026-03-14T23:18:50Z
> - **Version:** code-kg 0.9.0
> - **Commit:** 2426c1d (main)
> - **Platform:** Darwin arm64 | Python 3.12.13
> - **Graph:** 2543 nodes · 2520 edges (215 meaningful)
> - **Included directories:** src
> - **Excluded directories:** tests
> - **Elapsed time:** 5s

# doc_kg Analysis

**Generated:** 2026-03-14 23:18:50 UTC

---

## Executive Summary

This report provides a comprehensive architectural analysis of the **doc_kg** repository using CodeKG's knowledge graph. The analysis covers complexity hotspots, module coupling, key call chains, and code quality signals to guide refactoring and architecture decisions.

| Overall Quality | Grade | Score |
|----------------|-------|-------|
| [C] **Fair** | **C** | 70 / 100 |

---

## Baseline Metrics

| Metric | Value |
|--------|-------|
| **Total Nodes** | 2543 |
| **Total Edges** | 2520 |
| **Modules** | 25 (of 25 total) |
| **Functions** | 65 |
| **Classes** | 23 |
| **Methods** | 102 |

### Edge Distribution

| Relationship Type | Count |
|-------------------|-------|
| CALLS | 858 |
| CONTAINS | 190 |
| IMPORTS | 177 |
| ATTR_ACCESS | 761 |
| INHERITS | 1 |

---

## Fan-In Ranking

Most-called functions are potential bottlenecks or core functionality. These functions are heavily depended upon across the codebase.

| # | Function | Module | Callers |
|---|----------|--------|---------|
| 1 | `close()` | src/doc_kg/kg.py | **10** |
| 2 | `close()` | src/doc_kg/store.py | **10** |
| 3 | `con()` | src/doc_kg/store.py | **9** |
| 4 | `store()` | src/doc_kg/kg.py | **6** |
| 5 | `to_dict()` | src/doc_kg/kg.py | **5** |
| 6 | `load_manifest()` | src/doc_kg/snapshots.py | **4** |
| 7 | `_get_kg()` | src/doc_kg/mcp_server.py | **4** |
| 8 | `load_snapshot()` | src/doc_kg/snapshots.py | **4** |
| 9 | `index()` | src/doc_kg/kg.py | **4** |
| 10 | `to_json()` | src/doc_kg/kg.py | **4** |
| 11 | `to_markdown()` | src/doc_kg/kg.py | **4** |
| 12 | `extract()` | src/doc_kg/graph.py | **3** |
| 13 | `_slug()` | src/doc_kg/relations.py | **3** |
| 14 | `embed_texts()` | src/doc_kg/index.py | **3** |
| 15 | `build_graph()` | src/doc_kg/kg.py | **3** |


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
| `src/doc_kg/kg.py` | 1 | 4 | 7 | 3 | 0.27 |
| `src/doc_kg/index.py` | 6 | 4 | 2 | 0 | 0.00 |
| `src/doc_kg/snapshots.py` | 0 | 5 | 1 | 0 | 0.00 |
| `src/doc_kg/store.py` | 1 | 2 | 5 | 1 | 0.14 |
| `src/doc_kg/dockg_thorough_analysis.py` | 5 | 2 | 2 | 2 | 0.40 |
| `src/doc_kg/chunker.py` | 4 | 1 | 0 | 0 | 0.00 |
| `src/doc_kg/dockg.py` | 9 | 2 | 3 | 2 | 0.33 |
| `src/doc_kg/app.py` | 9 | 0 | 0 | 2 | 0.67 |
| `src/doc_kg/graph.py` | 0 | 1 | 2 | 1 | 0.25 |
| `src/doc_kg/mcp_server.py` | 7 | 0 | 0 | 1 | 0.50 |

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
| `DocKG()` | src/doc_kg/kg.py | 9 | class |
| `SnapshotManager()` | src/doc_kg/snapshots.py | 4 | class |
| `GraphStore()` | src/doc_kg/store.py | 3 | class |
| `build()` | src/doc_kg/cli/cmd_build.py | 3 | function |
| `pack()` | src/doc_kg/cli/cmd_query.py | 3 | function |
| `Snapshot()` | src/doc_kg/snapshots.py | 2 | class |
| `BuildStats()` | src/doc_kg/kg.py | 2 | class |
| `SnapshotDelta()` | src/doc_kg/snapshots.py | 2 | class |
| `SnapshotMetrics()` | src/doc_kg/snapshots.py | 2 | class |
| `SentenceTransformerEmbedder()` | src/doc_kg/index.py | 2 | class |
---

## Docstring Coverage

Docstring coverage directly determines semantic retrieval quality. Nodes without
docstrings embed only structured identifiers (`KIND/NAME/QUALNAME/MODULE`), where
keyword search is as effective as vector embeddings. The semantic model earns its
value only when a docstring is present.

| Kind | Documented | Total | Coverage |
|------|-----------|-------|----------|
| `function` | 49 | 65 | [WARN] 75.4% |
| `method` | 57 | 102 | [WARN] 55.9% |
| `class` | 23 | 23 | [OK] 100.0% |
| `module` | 24 | 25 | [OK] 96.0% |
| **total** | **153** | **215** | **[WARN] 71.2%** |

> **Recommendation:** 62 nodes lack docstrings. Prioritize documenting high-fan-in functions and public API surface first — these have the highest impact on query accuracy.

---

## Structural Importance Ranking (SIR)

Weighted PageRank aggregated by module — reveals architectural spine. Cross-module edges boosted 1.5×; private symbols penalized 0.85×. Node-level detail: `codekg centrality --top 25`

| Rank | Score | Members | Module |
|------|-------|---------|--------|
| 1 | 0.190912 | 31 | `src/doc_kg/kg.py` |
| 2 | 0.183597 | 22 | `src/doc_kg/store.py` |
| 3 | 0.142840 | 23 | `src/doc_kg/snapshots.py` |
| 4 | 0.105508 | 25 | `src/doc_kg/index.py` |
| 5 | 0.056580 | 9 | `src/doc_kg/graph.py` |
| 6 | 0.052304 | 18 | `src/doc_kg/dockg_thorough_analysis.py` |
| 7 | 0.051530 | 12 | `src/doc_kg/dockg.py` |
| 8 | 0.048847 | 13 | `src/doc_kg/chunker.py` |
| 9 | 0.035004 | 8 | `src/doc_kg/topics.py` |
| 10 | 0.029959 | 7 | `src/doc_kg/relations.py` |
| 11 | 0.024376 | 10 | `src/doc_kg/app.py` |
| 12 | 0.022737 | 8 | `src/doc_kg/mcp_server.py` |
| 13 | 0.015112 | 6 | `src/doc_kg/cli/cmd_snapshot.py` |
| 14 | 0.014107 | 2 | `src/doc_kg/cli/main.py` |
| 15 | 0.010891 | 4 | `src/doc_kg/cli/cmd_build.py` |



---

## Code Quality Issues

- [WARN] Moderate docstring coverage (71.2%) — semantic retrieval quality is degraded for undocumented nodes; BM25 is as effective as embeddings without docstrings
- [WARN] 2 orphaned functions found (`main`, `_silent_init`) -- consider archiving or documenting

---

## Architectural Strengths

- Well-structured with 15 core functions identified
- No god objects or god functions detected

---

## Recommendations

### Immediate Actions
1. **Improve docstring coverage** — 62 nodes lack docstrings; prioritize high-fan-in functions and public APIs first for maximum semantic retrieval gain
2. **Remove or archive orphaned functions** — `main`, `_silent_init` have zero callers and add maintenance burden

### Medium-term Refactoring
1. **Harden high fan-in functions** — `close`, `close`, `con` are widely depended upon; review for thread safety, clear contracts, and stable interfaces
2. **Reduce module coupling** — consider splitting tightly coupled modules or introducing interface boundaries
3. **Add tests for key call chains** — the identified call chains represent well-traveled execution paths that benefit most from regression coverage

### Long-term Architecture
1. **Version and stabilize the public API** — document breaking-change policies for `DocKG`, `SnapshotManager`, `GraphStore`
2. **Enforce layer boundaries** — add linting or CI checks to prevent unexpected cross-module dependencies as the codebase grows
3. **Monitor hot paths** — instrument the high fan-in functions identified here to catch performance regressions early

---

## Inheritance Hierarchy

**1** INHERITS edges across **2** classes. Max depth: **1**.

| Class | Module | Depth | Parents | Children |
|-------|--------|-------|---------|----------|
| `SentenceTransformerEmbedder` | src/doc_kg/index.py | 1 | 1 | 0 |
| `Embedder` | src/doc_kg/index.py | 0 | 0 | 1 |


---

## Snapshot History

No snapshots found. Run `codekg snapshot save <version>` to capture one.


---

## Appendix: Orphaned Code

Functions with zero callers (potential dead code):

| Function | Module | Lines |
|----------|--------|-------|
| `main()` | src/doc_kg/app.py | 108 |
| `_silent_init()` | src/doc_kg/index.py | 2 |
---

## CodeRank -- Global Structural Importance

Weighted PageRank over CALLS + IMPORTS + INHERITS edges (test paths excluded). Scores are normalized to sum to 1.0. This ranking seeds Phase 2 fan-in discovery and Phase 15 concern queries.

| Rank | Score | Kind | Name | Module |
|------|-------|------|------|--------|
| 1 | 0.001509 | method | `GraphStore.con` | src/doc_kg/store.py |
| 2 | 0.001392 | method | `DocGraph.extract` | src/doc_kg/graph.py |
| 3 | 0.001098 | function | `_slug` | src/doc_kg/relations.py |
| 4 | 0.001008 | method | `DocKG.store` | src/doc_kg/kg.py |
| 5 | 0.000962 | class | `SnapshotDelta` | src/doc_kg/snapshots.py |
| 6 | 0.000890 | class | `SnapshotManifest` | src/doc_kg/snapshots.py |
| 7 | 0.000873 | method | `SnapshotManager.load_manifest` | src/doc_kg/snapshots.py |
| 8 | 0.000844 | method | `TextPack.to_dict` | src/doc_kg/kg.py |
| 9 | 0.000775 | function | `_get_kg` | src/doc_kg/mcp_server.py |
| 10 | 0.000741 | method | `SnapshotManager.load_snapshot` | src/doc_kg/snapshots.py |
| 11 | 0.000714 | function | `_load_store` | src/doc_kg/app.py |
| 12 | 0.000681 | method | `GraphStore.close` | src/doc_kg/store.py |
| 13 | 0.000681 | method | `SentenceTransformerEmbedder.embed_texts` | src/doc_kg/index.py |
| 14 | 0.000681 | method | `TopicExtractor._load_topic_map` | src/doc_kg/topics.py |
| 15 | 0.000681 | method | `DocKG.close` | src/doc_kg/kg.py |
| 16 | 0.000656 | method | `DocKG.embedder` | src/doc_kg/kg.py |
| 17 | 0.000629 | method | `TextChunker._semantic_chunks` | src/doc_kg/chunker.py |
| 18 | 0.000629 | function | `_extract_links` | src/doc_kg/chunker.py |
| 19 | 0.000620 | method | `Snapshot.from_dict` | src/doc_kg/snapshots.py |
| 20 | 0.000608 | method | `TextChunker._fixed_size_chunks` | src/doc_kg/chunker.py |

---

## Concern-Based Hybrid Ranking

Top structurally-dominant nodes per architectural concern (0.60 × semantic + 0.25 × CodeRank + 0.15 × graph proximity).

### Configuration Loading Initialization Setup

| Rank | Score | Kind | Name | Module |
|------|-------|------|------|--------|
| 1 | 0.7831 | function | `_load_store` | src/doc_kg/app.py |
| 2 | 0.75 | method | `ProvMeta.__init__` | src/doc_kg/store.py |
| 3 | 0.7487 | method | `DocKG.__init__` | src/doc_kg/kg.py |
| 4 | 0.745 | function | `_init_state` | src/doc_kg/app.py |
| 5 | 0.7415 | method | `GraphStore.__init__` | src/doc_kg/store.py |

### Data Persistence Storage Database

| Rank | Score | Kind | Name | Module |
|------|-------|------|------|--------|
| 1 | 0.8274 | method | `GraphStore.con` | src/doc_kg/store.py |
| 2 | 0.8185 | method | `DocKG.store` | src/doc_kg/kg.py |
| 3 | 0.6966 | method | `GraphStore.write` | src/doc_kg/store.py |
| 4 | 0.6921 | method | `SemanticIndex.build` | src/doc_kg/index.py |
| 5 | 0.6676 | class | `GraphStore` | src/doc_kg/store.py |

### Query Search Retrieval Semantic

| Rank | Score | Kind | Name | Module |
|------|-------|------|------|--------|
| 1 | 0.75 | method | `SemanticIndex.search` | src/doc_kg/index.py |
| 2 | 0.7108 | function | `query` | src/doc_kg/cli/cmd_query.py |
| 3 | 0.701 | method | `DocKG.query` | src/doc_kg/kg.py |
| 4 | 0.6952 | method | `Embedder.embed_query` | src/doc_kg/index.py |
| 5 | 0.6497 | class | `QueryResult` | src/doc_kg/kg.py |

### Graph Traversal Node Edge

| Rank | Score | Kind | Name | Module |
|------|-------|------|------|--------|
| 1 | 0.7733 | method | `DocGraph.edges` | src/doc_kg/graph.py |
| 2 | 0.7548 | method | `SemanticIndex._discover_similar_edges` | src/doc_kg/index.py |
| 3 | 0.7478 | method | `GraphStore.edges_from` | src/doc_kg/store.py |
| 4 | 0.7411 | method | `GraphStore.edges_within` | src/doc_kg/store.py |
| 5 | 0.7362 | method | `DocGraph.result` | src/doc_kg/graph.py |



---

*Report generated by CodeKG Thorough Analysis Tool — analysis completed in 5.4s*
