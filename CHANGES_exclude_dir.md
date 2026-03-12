# Change: `--exclude-dir` support and pyproject.toml config wiring

## Summary

Added Option B exclude parity with CodeKG: `--exclude-dir` CLI flag on `build` and `build-graph`,
plus wiring of the previously-dead `[tool.dockg].exclude` pyproject.toml config.

## Problem

`[tool.dockg].exclude` existed in pyproject.toml but was never read — no code loaded it.
`iter_text_files` supported an `exclude` parameter but neither `DocKG.__init__` nor any CLI
command passed anything to it. The exclusion config was silently ignored on every build.

## Files Changed

### `src/doc_kg/config.py` (new)

Mirrors `src/code_kg/config.py` in CodeKG. Reads `[tool.dockg].exclude` from pyproject.toml.

```python
from doc_kg.config import load_exclude_dirs

exclude = load_exclude_dirs("/path/to/corpus")  # → set of dir names
```

Single public function: `load_exclude_dirs(corpus_root)` → `set[str]`.
Returns an empty set if pyproject.toml is absent, unreadable, or has no `[tool.dockg].exclude`.

### `src/doc_kg/kg.py`

Added `exclude: set[str] | None = None` parameter to `DocKG.__init__`.
Stored as `self.exclude` and forwarded to `DocGraph` in the lazy `graph` property.

### `src/doc_kg/cli/cmd_build.py`

- Added `from doc_kg.config import load_exclude_dirs` import.
- Added `--exclude-dir DIR` repeatable option to both `build` and `build-graph` commands.
- Both commands now merge CLI flags with pyproject.toml values:
  ```python
  exclude = load_exclude_dirs(corpus_root) | set(exclude_dir)
  ```
- `exclude` is passed to `DocKG(... exclude=exclude or None)`.
- Build output now prints `exclude :` line showing active exclusions.

`build-index` was intentionally left unchanged — it operates on an existing SQLite graph,
no file walking occurs.

## Behaviour

Priority/merge order (same as CodeKG):
1. Built-in `SKIP_DIRS` in `dockg.py` (always applied, hardcoded)
2. `[tool.dockg].exclude` from pyproject.toml (auto-loaded from corpus root)
3. `--exclude-dir` CLI flags (merged at call time)

All three are unioned — there is no override, only additive exclusion.

## Example

```toml
# pyproject.toml
[tool.dockg]
exclude = [".dockg", ".codekg", "src", ".git", ".venv", "venv", "__pycache__"]
```

```bash
# CLI flags merged on top of pyproject.toml config
dockg build . --exclude-dir node_modules --exclude-dir dist
```

## Design Notes

- `include` (top-level directory whitelist, as in CodeKG) was deliberately not added.
  The `include` concept is motivated by "all source lives in `src/`" — a code pattern.
  Document corpora are generally indexed from root minus exclusions; an include whitelist
  adds complexity without a clear prose-corpus use case.
- The `[tool.dockg]` section was already present and documented in the CodeKG
  `pyproject.toml`; this change makes it functional.
