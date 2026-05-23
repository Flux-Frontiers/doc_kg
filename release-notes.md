# Release Notes — v0.15.3

> Released: 2026-05-20

### Added
- `src/doc_kg/dockg.py`: `_classify_section_content_type()` — classifies a document section as `'front_matter'`, `'reference'`, or `None`. Rules applied in order: (1) `reference.md` files → `'reference'`; (2) H1 headings → `None` (book title); (3) headings matching main-content keywords (`chapter`, `book`, `part`, `volume`, etc.) → `None`; (4) sections starting after 40% of the file → `None` (late contextual intros); (5) headings matching `_FM_HEADING` regex → `'front_matter'`. `_FM_HEADING` regex covers prefaces, introductions, forewords, translator/editor/transcriber notes, biographical sketches, tables of contents, select bibliographies, and copyright sections. `_FM_MAIN_CONTENT` regex anchors on chapter/book/part/volume headings to ensure they always win over FM heuristics.
- `tests/test_front_matter.py`: 19 new tests across three classes — `TestClassifySectionContentType` (8 unit tests covering all decision branches: H1 bypass, `reference.md` override, main-content keyword wins, FM headings in early vs. late position, boundary conditions, normal prose, `None` preamble, zero-length file guard), `TestParseCorpusFrontMatterTagging` (7 integration tests: `reference.md` chunks tagged, preface/chapter distribution, introduction tagging, `Book I. Introduction.` not tagged, late contextual intro not tagged, prose-only file clean, mixed corpus), `TestQuerySeedFiltering` (4 integration tests with mocked LanceDB index and real SQLite store verifying `reference.md` and `front_matter` nodes are excluded from seeds and returned results while prose chunks pass through).
- `src/doc_kg/index.py`: `_discover_similar_edges()` gains `max_degree` parameter — when > 0, uses a per-node min-heap to collect top-k candidate edges during the ANN scan, then enforces a hard per-node cap with a greedy high-similarity selection pass before writing to SQLite. Prevents hub nodes from accumulating unbounded SIMILAR_TO degree in dense corpora. `build()`, `build_from_cache()`, and `_build_index_from_cache_chunks()` all gain a `similar_max_degree: int = 0` parameter (default 0 = unlimited, preserving existing behaviour).
- `src/doc_kg/kg.py`: `DocKG.build()`, `build_from_cache()`, and `build_index_from_cache()` gain `similar_max_degree: int = 0` parameter, threaded through to `SemanticIndex`.
- `tests/test_similar_edges.py`: 12 new tests for `_discover_similar_edges()` covering empty input, self-hit skipping, threshold filtering, canonical edge direction, similarity evidence, and all `max_degree` pruning cases (unlimited, cap=1, cap=2, dense graph, prefers highest similarity, threshold+cap interaction).

### Changed
- `src/doc_kg/dockg.py`: `parse_corpus()` now calls `_classify_section_content_type()` for every chunk whose `content_type` is `None` after chunking. Captures `total_chars = len(raw_text)` per file for position-cutoff calculation. Front-matter and reference sections are tagged during corpus ingestion so the content type is persisted in SQLite.
- `src/doc_kg/kg.py`: `DocKG.query()` now filters front-matter and reference content from both seed selection and returned results. Seeds are oversampled 3× to compensate for filtering; `reference.md` hits are dropped by file path immediately; remaining candidates are checked against the SQLite store for `content_type == 'front_matter'` and dropped. In the ranked result walk, nodes with `content_type` in `{'front_matter', 'reference'}` are skipped in the returned list but remain in the graph for traversal (they can still contribute neighbour edges).
- `src/doc_kg/index.py`: `_discover_similar_edges()` rewritten from per-chunk LanceDB ANN queries to a **blocked NumPy matmul** (BLAS SGEMM). Because sentence-transformers emits L2-normalised vectors (`normalize_embeddings=True`), cosine similarity equals the dot product, so `X[block] @ X.T` gives exact pairwise similarities with a single BLAS call per block — no per-chunk Python↔LanceDB round-trip. Block size is adaptively clamped so the `(B × N)` similarity matrix stays under ~256 MB regardless of corpus size. Top-k filtering now uses `np.argpartition` (O(N)) instead of a full sort. The `tbl` parameter is retained for call-site compatibility but is no longer used. Added `block_size: int = 512` parameter.
- `tests/test_similar_edges.py`: All tests rewritten to use real L2-normalised NumPy vectors instead of mocked LanceDB ANN results. `_make_tbl()` helper removed; `_run_discovery()` now takes `chunk_vecs` directly. Star scenario uses geometrically correct vectors (hub-spoke sim=0.6, spoke-spoke sim=0.36 < threshold). `test_max_degree_prefers_higher_similarity` uses exact dot-product construction for 0.99 and 0.85 similarities.
- `analysis/architecture.md`: Moved from project root into `analysis/` directory (renamed from `architecture.md`).
- `.vscode/settings.json`: Added `python.defaultInterpreterPath` and `python.testing.pytestPath` pointing to `.venv/bin/` so the VS Code Test Explorer uses the project virtual environment. Installed `pytest` and `pytest-cov` into `.venv` (were missing despite being declared in `[project.optional-dependencies] dev`).
- `.dockg/snapshots/manifest.json`: Snapshot updated for v0.15.3.

### Fixed
- `src/doc_kg/index.py`: `build_from_cache()` was not forwarding `similar_max_degree` to `_build_from_jsonl_cache()` — the JSONL cache path silently ignored the degree cap. Argument now threaded through correctly (mypy `call-arg` error).

### Removed
- `generate_wiki.py`: Deleted — superseded by dedicated documentation tooling.
- `CHANGES_exclude_dir.md`: Deleted — temporary scratch file.
- `release-notes.md`: Deleted — content lives in `CHANGELOG.md`.

---

_Full changelog: [CHANGELOG.md](CHANGELOG.md)_
