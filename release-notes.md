# Release Notes — v0.15.7

> Released: 2026-06-09

### Added
- **Query-time scope pushdown** (`src/doc_kg/kg.py`, `src/doc_kg/store.py`, `src/doc_kg/index.py`): `DocKG.query()` and `DocKG.pack()` accept optional `source_path_prefixes` and `node_kinds` constraints that restrict retrieval to a subtree (e.g. a single genre of a consolidated corpus) and/or node kinds. The filter is pushed *into* both seed channels — LanceDB vector search via a prefilter `where` clause (`SemanticIndex.search(..., where=)`) and FTS5 lexical search via parameterised SQL (`GraphStore.search_lexical(..., file_prefixes=, node_kinds=)`) — so the seed budget is spent entirely on in-scope nodes rather than post-filtered, eliminating cross-subtree starvation. A final `_node_in_scope()` guard drops any node that graph expansion pulled out of scope via edges. New helpers: `_lance_where()`/`_node_in_scope()` (`kg.py`) and `_node_filter_sql()` (`store.py`, injection-safe with `LIKE ... ESCAPE`).
- `tests/test_query_scope.py`: covers the SQL/Lance filter builders, the scope guard, and FTS5 lexical pushdown (prefix-only, kind-only, and combined) restricting results to a genre subtree.
- `src/doc_kg/store.py`: Hybrid lexical retrieval via SQLite FTS5. `GraphStore.rebuild_fts()` builds a *contentless* FTS5 table `nodes_fts` (inverted index only, ≈1× chunk-text size) over all `kind='chunk'` rows; safe to call repeatedly (drops + rebuilds) and no-ops cleanly when SQLite lacks FTS5. `has_fts()` reports index presence. `search_lexical()` runs BM25 ranking, trying an exact-phrase query first and falling back to OR-of-terms for recall; returns chunk IDs best-first, or `[]` on older corpora so callers degrade to dense-only. Added `_fts_terms()` helper to tokenise queries into bare alphanumerics, stripping apostrophes/punctuation that FTS5 would otherwise treat as query syntax (e.g. `Lot's` → `lot`, `s`).
- `src/doc_kg/kg.py`: `DocKG._fused_seeds()` blends the dense (vector) and lexical (BM25) seed channels with reciprocal rank fusion (RRF, `_RRF_K=60`) so exact-phrase matches that dense embeddings bury can seed graph expansion without sacrificing dense recall. Lexical-only seeds receive a synthetic cosine distance (`_LEXICAL_SEED_BASE_DIST` + per-rank step) so distance-based ranking can place them. `query()` and `pack()` now seed via `_fused_seeds()`. `DocKG.build()` calls `store.rebuild_fts()` so new builds get the lexical index automatically.
- `src/doc_kg/cli/cmd_build.py`: `dockg reindex-fts` command backfills the FTS5 lexical index on an existing graph from chunk text already in SQLite — no re-embedding, no LanceDB changes. Lets corpora built before the lexical index existed gain hybrid retrieval.
- `tests/test_store.py`: `test_fts_lexical_search` and `test_fts_rebuild_is_idempotent` cover graceful empty results before indexing, chunk-count after `rebuild_fts()`, exact-phrase isolation, apostrophe/punctuation handling via OR-fallback, term-less query degradation, and idempotent rebuilds.

### Changed
- `pyproject.toml`, `src/doc_kg/__init__.py`: Version bumped to 0.15.7.

### Removed

### Fixed

---

_Full changelog: [CHANGELOG.md](CHANGELOG.md)_
