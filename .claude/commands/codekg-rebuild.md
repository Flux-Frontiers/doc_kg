# CodeKG Rebuild

Wipe and rebuild the CodeKG SQLite knowledge graph and LanceDB semantic index for a repository. Execute the following steps in sequence.

## Command Argument Handling

**Usage:**
- `/codekg-rebuild` — Rebuild for the current working directory
- `/codekg-rebuild /path/to/repo` — Rebuild for the specified repository

---

## Step 0: Resolve Paths

1. If a path argument was provided, use it as `REPO_ROOT`. Otherwise use the current working directory.
2. Verify the path exists and contains at least one `.py` file:
   ```bash
   find "$REPO_ROOT" -name "*.py" \
     -not -path "*/.venv/*" \
     -not -path "*/__pycache__/*" \
     -not -path "*/.codekg/*" | head -5
   ```
3. If no Python files are found, stop and report the issue.

All artifact paths default to `$REPO_ROOT/.codekg/` — do not pass `--db`, `--sqlite`, or `--lancedb` flags.

Detect how to invoke CodeKG — try in order:
1. `poetry run codekg-build-sqlite` (preferred if inside a Poetry project)
2. `python -m code_kg build-sqlite` (fallback for pip/venv installs)

Use whichever works and apply it consistently for all commands below. Call this `RUN_PREFIX` (either `poetry run` or nothing, with `python -m code_kg` subcommands).

---

## Step 1: Rebuild the SQLite Knowledge Graph

Run the static analysis build with `--wipe` to replace any existing graph:

```bash
# Poetry
poetry run codekg-build-sqlite --repo "$REPO_ROOT" --wipe

# pip / venv
python -m code_kg build-sqlite --repo "$REPO_ROOT" --wipe
```

Verify the database was created and is non-empty:
```bash
sqlite3 "$REPO_ROOT/.codekg/graph.sqlite" "SELECT COUNT(*) FROM nodes; SELECT COUNT(*) FROM edges;"
```

Capture and report node and edge counts broken down by kind. If both are zero, warn the user — the repo may have no indexable Python files.

---

## Step 2: Rebuild the LanceDB Semantic Index

Run the embedding build with `--wipe`:

```bash
# Poetry
poetry run codekg-build-lancedb --repo "$REPO_ROOT" --wipe

# pip / venv
python -m code_kg build-lancedb --repo "$REPO_ROOT" --wipe
```

Confirm the LanceDB directory was populated:
```bash
ls -lh "$REPO_ROOT/.codekg/lancedb"
```

Capture the number of indexed vectors from the command output.

---

## Step 3: Verify

Run a quick stats check to confirm both layers are consistent:

```bash
# Poetry
poetry run python -c "
from code_kg import CodeKG; import json
kg = CodeKG(repo_root='$REPO_ROOT')
print(json.dumps(kg.stats(), indent=2))
"

# pip / venv
python -c "
from code_kg import CodeKG; import json
kg = CodeKG(repo_root='$REPO_ROOT')
print(json.dumps(kg.stats(), indent=2))
"
```

If this errors, diagnose and report before proceeding.

---

## Step 4: Report

Present a summary:

```
✓ Repository:    <REPO_ROOT>
✓ SQLite graph:  <REPO_ROOT>/.codekg/graph.sqlite  (<N> nodes, <M> edges)
✓ LanceDB index: <REPO_ROOT>/.codekg/lancedb  (<V> vectors)

Node breakdown:  module=X  class=X  function=X  method=X  symbol=X
Edge breakdown:  CONTAINS=X  CALLS=X  IMPORTS=X  INHERITS=X  ATTR_ACCESS=X
```

Note: MCP client configs do not need to change — they reference the same paths.

---

## Important Rules

- Always pass `--wipe` to both build steps — the rebuild is intentional and idempotent.
- Only pass `--repo` — all other paths default to `.codekg/` automatically.
- Use an absolute path for `--repo`.
- Do NOT modify any source files in the target repository.
- If the repo is large (>50k lines of Python), warn that the embedding step may take several minutes.
