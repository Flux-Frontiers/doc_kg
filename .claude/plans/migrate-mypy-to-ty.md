# Handoff: Migrate mypy → ty

**Status:** Ready to execute
**Reference:** pycode_kg completed this migration in commits `9ccf076`, `371a41e` (2026-06-01)
**Effort:** Low — no optional-dep GUI extras in doc_kg, so the simpler path applies

---

## Background

Astral's [`ty`](https://github.com/astral-sh/ty) replaces mypy as the project type checker. It uses different error codes (`invalid-assignment`, `unresolved-attribute`, etc.) so mypy `# type: ignore[code]` comments must be converted to `# ty: ignore[code]`. The key lesson from pycode_kg: **run `ty check src/` locally first before touching any files** — ty may surface real issues worth fixing properly rather than suppressing.

---

## Step 1: Install ty and run the check

```bash
poetry add --group dev ty@^0.0.41
poetry run ty check src/
```

Count and categorize the diagnostics. In pycode_kg there were 44; most were false positives from third-party stubs.

---

## Step 2: pyproject.toml changes

Replace the `[tool.mypy]` block and update the `dev`/`all` extras:

```toml
# REMOVE:
[tool.mypy]
python_version        = "3.12"
strict                = false
ignore_missing_imports = true
mypy_path             = "src"
explicit_package_bases = true

# ADD:
[tool.ty.environment]
python-version = "3.12"
root = ["src"]

[tool.ty.rules]
# Be lenient about third-party stubs (mirrors mypy's ignore_missing_imports).
unresolved-import = "ignore"
```

In `[project.optional-dependencies]`, replace `"mypy>=1.10.0"` with `"ty>=0.0.41"` in both the `dev` and `all` extras. Same for `[tool.poetry.group.dev.dependencies]`.

Also update the header comment:
```toml
#   pip install -e ".[dev]"             core + dev tools (pytest, ruff, ty, etc.)
```

---

## Step 3: .pre-commit-config.yaml changes

Two changes:

1. **Bump ruff hook** from `v0.9.10` → `v0.15.13` and rename `ruff` → `ruff-check`:
```yaml
# BEFORE:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.9.10
    hooks:
      - id: ruff

# AFTER:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.15.13
    hooks:
      - id: ruff-check
```

2. **Replace mypy hook** with ty:
```yaml
# BEFORE:
      - id: mypy
        name: mypy
        entry: poetry run mypy src/

# AFTER:
      - id: ty
        name: ty
        entry: poetry run ty check src/
```

---

## Step 4: .github/workflows/ci.yml

```yaml
# BEFORE:
      - name: Run mypy
        run: poetry run mypy src/

# AFTER:
      - name: Run ty
        run: poetry run ty check src/
```

**Important — do NOT add `--all-extras`** to the install step. doc_kg has no optional GUI extras with mismatched stubs, so the lean `poetry install --no-interaction` is correct and CI will match your dev environment. If you get `unused-ignore-comment` warnings in CI that don't appear locally, add this rule instead of expanding the install:

```toml
[tool.ty.rules]
unresolved-import = "ignore"
unused-ignore-comment = "ignore"   # add only if needed
```

---

## Step 5: Fix diagnostics in source files

### Genuine narrowing issues → fix properly (don't suppress)

If ty reports `invalid-return-type` on a pattern like:

```python
if self._foo is None:
    self._load()
return self._foo  # type: ignore[return-value]
```

Fix with an assert instead of a suppress:

```python
if self._foo is None:
    self._load()
assert self._foo is not None
return self._foo
```

### Third-party false positives → convert the ignore comment

For everything else, convert mypy-style to ty-style:

```python
# BEFORE (mypy):
some_call()  # type: ignore[attr-defined]
some_call()  # type: ignore[return-value]
some_call()  # type: ignore[override]
some_call()  # type: ignore[arg-type]

# AFTER (ty — use the ty error code from the diagnostic output):
some_call()  # ty: ignore[unresolved-attribute]
some_call()  # ty: ignore[invalid-return-type]
some_call()  # ty: ignore[invalid-method-override]
some_call()  # ty: ignore[invalid-argument-type]
```

The ty error code appears in the diagnostic header, e.g. `error[invalid-assignment]`.

### Common ty error codes

| ty code | Typical cause |
|---|---|
| `invalid-assignment` | `param` descriptor (e.g. `param.String(...)`) assigned to `str`-annotated field |
| `unresolved-attribute` | PyQt5/Qt enum attrs (`Qt.Checked`, etc.) |
| `invalid-argument-type` | pyvista `functools.wraps`-decorated methods |
| `missing-argument` | Same pyvista issue |
| `invalid-method-override` | Intentional LSP overrides (`closeEvent`, etc.) |
| `invalid-return-type` | Nullable field returned as non-nullable (fix with assert) |

---

## Step 6: Run ty clean, then verify

```bash
poetry run ty check src/
poetry run ruff check src/
```

Both should report `All checks passed!`

---

## Step 7: Update poetry.lock and commit

```bash
poetry lock
git add pyproject.toml poetry.lock .pre-commit-config.yaml .github/workflows/ci.yml \
        src/doc_kg/   # whichever source files were touched
git commit -m "chore(tooling): migrate mypy → ty, bump to <next-version>"
```

Conventional commit type is `chore(tooling)` — matches the pycode_kg precedent.

---

## Notes

- doc_kg has **no `viz`/`viz3d` optional extras with heavy GUI deps**, so the `unused-ignore-comment` CI/local mismatch that bit pycode_kg should not occur here. The lean CI install is correct.
- ty is faster than mypy and the error messages are more precise. The `unresolved-import = "ignore"` rule is the main compatibility shim needed.
- After the commit, CI should pass on the first try. If it doesn't, check whether any `# type: ignore` comments were left unconverted (ty doesn't recognize the mypy syntax).
