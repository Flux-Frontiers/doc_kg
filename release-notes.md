# Release Notes — v0.13.0

> Released: 2026-05-03

### Added
- `tests/test_pack_dedup.py`: New test module (8 tests) covering `DocKG.pack()` deduplication, `_short_chunk_boost` micro-fragment guard, `TextChunker` and `chunker_for()` `min_chunk_chars` defaults, and `CrossSnippetPack.render()` micro-fragment filtering.

### Changed
- `src/doc_kg/chunker.py`: `TextChunker.__init__` and `chunker_for()` — `min_chunk_chars` default raised from 1 → 50; the old default of 1 allowed micro-fragments (e.g. `"see"`, `"cf."`) to be stored and indexed, polluting pack results.
- `src/doc_kg/kg.py`: Added `_MIN_CHUNK_CHARS = 50` module constant; `_short_chunk_boost()` now returns `0.0` for chunks shorter than `_MIN_CHUNK_CHARS` so micro-fragments cannot float to the top of `pack()` results via the short-chunk boost; `pack()` deduplication pre-pass now builds `seen_files_with_chunks` before the ranking loop so document/section nodes are always suppressed when their file's chunks are present (fixes edge case where chunks and coarse nodes shared the same rank).
- `pyproject.toml`: `kgdeps` and `all` extras now include `kg-rag @ git+https://github.com/Flux-Frontiers/KGRAG.git`; removed stale `[[tool.poetry.source]]` TestPyPI block; version bumped to 0.13.0.
- `.github/workflows/publish.yml`: Added `poetry publish` step so tag pushes automatically publish to PyPI via `PYPI_TOKEN` secret.
- `tests/test_chunker.py`, `tests/test_dockg.py`: Test fixture strings lengthened to meet the new 50-char `min_chunk_chars` floor so fixture chunks are not silently dropped during corpus parsing.

### Fixed
- `src/doc_kg/snapshots.py`: Docstring references corrected from `kg_snapshot.snapshots` → `kg_utils.snapshots` (the canonical package since v0.12.2).

---

_Full changelog: [CHANGELOG.md](CHANGELOG.md)_
