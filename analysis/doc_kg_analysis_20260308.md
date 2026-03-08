> **Analysis Report Metadata**  
> - **Generated:** 2026-03-08T20:30:23Z  
> - **Version:** code-kg 0.5.2  
> - **Commit:** 45fe6b9 (main)  

# doc_kg Analysis

**Generated:** 2026-03-08 20:30:23 UTC

---

## 📊 Executive Summary

This report provides a comprehensive architectural analysis of the **doc_kg** repository using CodeKG's knowledge graph. The analysis covers complexity hotspots, module coupling, critical call chains, and code quality signals to guide refactoring and architecture decisions.

| Overall Quality | Grade | Score |
|----------------|-------|-------|
| 🟡 **Fair** | **C** | 70 / 100 |

---

## 📈 Baseline Metrics

| Metric | Value |
|--------|-------|
| **Total Nodes** | 1487 |
| **Total Edges** | 1486 |
| **Modules** | 5 |
| **Functions** | 53 |
| **Classes** | 14 |
| **Methods** | 71 |

### Edge Distribution

| Relationship Type | Count |
|-------------------|-------|
| CALLS | 458 |
| CONTAINS | 138 |
| IMPORTS | 99 |
| ATTR_ACCESS | 424 |
| INHERITS | 1 |

---

## 🔥 Complexity Hotspots (High Fan-In)

Most-called functions are potential bottlenecks or core functionality. These functions are heavily depended upon across the codebase.

| # | Function | Module | Callers | Risk Level |
|---|----------|--------|---------|-----------|
| 1 | `close()` | src/doc_kg/kg.py | **12** | 🟢 LOW |
| 2 | `close()` | src/doc_kg/store.py | **12** | 🟢 LOW |
| 3 | `stats()` | src/doc_kg/kg.py | **6** | 🟢 LOW |
| 4 | `chunk()` | src/doc_kg/chunker.py | **5** | 🟢 LOW |
| 5 | `search()` | src/doc_kg/index.py | **4** | 🟢 LOW |
| 6 | `node()` | src/doc_kg/kg.py | **4** | 🟢 LOW |
| 7 | `node()` | src/doc_kg/store.py | **4** | 🟢 LOW |
| 8 | `_extract_links()` | src/doc_kg/chunker.py | **3** | 🟢 LOW |
| 9 | `_split_sentences()` | src/doc_kg/chunker.py | **3** | 🟢 LOW |
| 10 | `extract()` | src/doc_kg/graph.py | **3** | 🟢 LOW |
| 11 | `build()` | src/doc_kg/cli/cmd_build.py | **2** | 🟢 LOW |
| 12 | `slugify()` | src/doc_kg/dockg.py | **2** | 🟢 LOW |
| 13 | `build()` | src/doc_kg/kg.py | **2** | 🟢 LOW |
| 14 | `build_graph()` | src/doc_kg/kg.py | **2** | 🟢 LOW |
| 15 | `ProvMeta()` | src/doc_kg/store.py | **1** | 🟢 LOW |


**Insight:** Functions with high fan-in are either core APIs or bottlenecks. Review these for:
- Thread safety and performance
- Clear documentation and contracts
- Potential for breaking changes

---

## 🔗 High Fan-Out Functions (Orchestrators)

Functions that call many others may indicate complex orchestration logic or poor separation of concerns.

✓ No extreme high fan-out functions detected. Well-balanced architecture.

---

## 📦 Module Architecture

Top modules by dependency coupling and cohesion.

| Module | Functions | Classes | Incoming | Outgoing | Cohesion |
|--------|-----------|---------|----------|----------|----------|
| `src/doc_kg/cli/cmd_build.py` | 0 | 0 | 1 | 5 | 0.82 |
| `src/doc_kg/cli/cmd_query.py` | 0 | 0 | 1 | 6 | 0.78 |
| `src/doc_kg/__main__.py` | 0 | 0 | 0 | 5 | 0.90 |
| `src/doc_kg/cli/options.py` | 0 | 0 | 0 | 6 | 0.90 |
| `src/doc_kg/graph.py` | 0 | 0 | 0 | 5 | 0.90 |

---

## 🔗 Critical Call Chains

Deepest call chains in the codebase. These represent critical execution paths.

**Chain 1** (depth: 4)

```
close → __exit__ → test_store_write_and_read → test_store_stats
```

**Chain 2** (depth: 4)

```
close → __exit__ → test_store_write_and_read → test_store_stats
```

**Chain 3** (depth: 4)

```
stats → test_store_stats → test_store_wipe → test_store_context_manager
```

**Chain 4** (depth: 4)

```
chunk → test_chunker_plain_no_embedder → test_chunker_markdown_sections → test_chunker_markdown_no_headings
```

**Chain 5** (depth: 4)

```
search → search → _discover_similar_edges → query
```

---

## 🔓 Public API Surface

Identified public APIs (module-level functions with high usage).

| Function | Module | Fan-In | Type |
|----------|--------|--------|------|
| `_extract_links()` | src/doc_kg/chunker.py | 3 | function |
| `_split_sentences()` | src/doc_kg/chunker.py | 3 | function |
---

## 📝 Docstring Coverage

Docstring coverage directly determines semantic retrieval quality. Nodes without
docstrings embed only structured identifiers (`KIND/NAME/QUALNAME/MODULE`), where
keyword search is as effective as vector embeddings. The semantic model earns its
value only when a docstring is present.

| Kind | Documented | Total | Coverage |
|------|-----------|-------|----------|
| `function` | 23 | 53 | 🔴 43.4% |
| `method` | 43 | 71 | 🟡 60.6% |
| `class` | 14 | 14 | 🟢 100.0% |
| `module` | 15 | 17 | 🟢 88.2% |
| **total** | **95** | **155** | **🟡 61.3%** |

> **Recommendation:** 60 nodes lack docstrings. Prioritize documenting high-fan-in functions and public API surface first — these have the highest impact on query accuracy.



---

## ⚠️  Code Quality Issues

- ⚠️  Moderate docstring coverage (61.3%) — semantic retrieval quality is degraded for undocumented nodes; BM25 is as effective as embeddings without docstrings
- ⚠️  2 orphaned functions found (`store`, `con`) — consider archiving or documenting

---

## ✅ Architectural Strengths

- ✓ Well-structured with 15 core functions identified
- ✓ No god objects or god functions detected

---

## 💡 Recommendations

### Immediate Actions
1. **Improve docstring coverage** — 60 nodes lack docstrings; prioritize high-fan-in functions and public APIs first for maximum semantic retrieval gain
2. **Remove or archive orphaned functions** — `store`, `con` have zero callers and add maintenance burden

### Medium-term Refactoring
1. **Harden high fan-in functions** — `close`, `close`, `stats` are widely depended upon; review for thread safety, clear contracts, and stable interfaces
2. **Reduce module coupling** — consider splitting tightly coupled modules or introducing interface boundaries
3. **Add tests for critical call chains** — the identified call chains represent high-risk execution paths that benefit most from regression coverage

### Long-term Architecture
1. **Version and stabilize the public API** — document breaking-change policies for `_extract_links`, `_split_sentences`
2. **Enforce layer boundaries** — add linting or CI checks to prevent unexpected cross-module dependencies as the codebase grows
3. **Monitor hot paths** — instrument the high fan-in functions identified here to catch performance regressions early

---

## 📋 Appendix: Orphaned Code

Functions with zero callers (potential dead code):

| Function | Module | Lines |
|----------|--------|-------|
| `con()` | src/doc_kg/store.py | 9 |
| `store()` | src/doc_kg/kg.py | 4 |


---

*Report generated by CodeKG Thorough Analysis Tool — analysis completed in 6.4s*
