# Release Notes — v0.15.5

> Released: 2026-06-05

## [0.15.5] - 2026-06-05

### Changed
- `.pre-commit-config.yaml`, `pyproject.toml`: Removed `pylint` entirely; linting is now handled exclusively by `ruff`, consistent with the `kgrag` project. Dropped `pylint>=4.0.5` from `dev` and `all` optional-dependency groups and deleted `[tool.pylint.messages_control]` configuration.

### Fixed
- `src/doc_kg/kg.py`: Restored `similar_max_degree: int = 0` parameter to `DocKG.build()`, `build_from_cache()`, and `build_index_from_cache()`. The parameter was introduced in v0.15.3 but removed in v0.15.4 because it was accepted without being forwarded to `SemanticIndex`. It is now threaded through correctly to `_discover_similar_edges()` via all three public build paths.
- `tests/test_front_matter.py`: `TestQuerySeedFiltering` tests were failing in CI with a HuggingFace connectivity error. The root cause was that `patch.object(kg.index, "search", ...)` triggered the lazy `index` property before the patch applied, initialising `SemanticIndex` and loading the sentence-transformer model. Fixed by injecting `kg._index = MagicMock()` directly so the lazy property is bypassed entirely. Tests now run in ~0.05 s with no network access.

---

_Full changelog: [CHANGELOG.md](CHANGELOG.md)_
