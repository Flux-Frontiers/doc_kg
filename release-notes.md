# Release Notes — v0.15.4

> Released: 2026-06-01

## What's New

### Type checker migrated from mypy to ty

The project has switched from `mypy` to Astral's `ty` for static type checking. `ty` is a Rust-based type checker that is significantly faster than `mypy` for large codebases. The migration covers CI (`.github/workflows/ci.yml`), pre-commit (`.pre-commit-config.yaml`), dev dependencies, and `pyproject.toml` configuration. The `[tool.mypy]` section has been replaced with `[tool.ty.environment]` and `[tool.ty.rules]`. All type-suppression comments have been updated to the `# ty: ignore[...]` format, and two `# type: ignore[return-value]` workarounds in `graph.py` have been replaced with explicit `assert` narrowing.

The `ruff-pre-commit` hook has also been updated to `v0.15.13` and the hook id renamed from `ruff` to `ruff-check`.

### Removed dead API surface

The `similar_max_degree` parameter has been removed from `DocKG.build()`, `build_from_cache()`, and `build_index_from_cache()`. The parameter was accepted but never forwarded to the underlying `SemanticIndex`, so callers were silently getting unlimited degree regardless of what they passed. Use `similar_k` for per-node edge caps.

### Housekeeping

13 stale `.claude/agents/` definition files have been removed (`cco`, `cw`, `do`, `doc`, `kc`, `me`, `qa`, `sd`, `sec`, `ta`, `uid`, `uids`, `uxd`).

---

_Full changelog: [CHANGELOG.md](CHANGELOG.md)_
