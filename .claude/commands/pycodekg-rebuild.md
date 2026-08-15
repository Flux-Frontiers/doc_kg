# PyCodeKG Rebuild

Wipe and rebuild the PyCodeKG SQLite knowledge graph and sqlite-vec semantic index for a repository. Execute the following steps in sequence.

## Command Argument Handling

**Usage:**
- `/pycodekg-rebuild` — Rebuild for the current working directory
- `/pycodekg-rebuild /path/to/repo` — Rebuild for the specified repository

---

## Step 0: Resolve Paths

1. If a path argument was provided, use it as `REPO_ROOT`. Otherwise use the current working directory.
2. Verify the path exists and contains at least one `.py` file:
   ```bash
   find "$REPO_ROOT" -name "*.py" \
     -not -path "*/.venv/*" \
     -not -path "*/__pycache__/*" \
     -not -path "*/.pycodekg/*" | head -5
   ```
3. If no Python files are found, stop and report the issue.

All artifact paths default to `$REPO_ROOT/.pycodekg/` — do not pass `--db` or `--vectors` flags.

---

## Step 1: Rebuild the Knowledge Graph (SQLite + sqlite-vec)

`pycodekg build` always wipes and rebuilds from scratch — no flag needed:

```bash
# Poetry project
poetry run pycodekg build --repo "$REPO_ROOT"

# Direct venv binary
"$REPO_ROOT/.venv/bin/pycodekg" build --repo "$REPO_ROOT"
```

Verify the database was created and is non-empty:
```bash
sqlite3 "$REPO_ROOT/.pycodekg/graph.sqlite" "SELECT COUNT(*) FROM nodes; SELECT COUNT(*) FROM edges;"
```

Capture and report node and edge counts broken down by kind. If both are zero, warn the user — the repo may have no indexable Python files.

---

## Step 2: Verify

Run a quick stats check to confirm both layers are consistent:

```bash
poetry run python -c "
from pycode_kg import PyCodeKG; import json
kg = PyCodeKG(repo_root='$REPO_ROOT')
print(json.dumps(kg.stats(), indent=2))
"
```

If this errors, diagnose and report before proceeding.

---

## Step 3: Report

Present a summary:

```
✓ Repository:    <REPO_ROOT>
✓ SQLite graph:  <REPO_ROOT>/.pycodekg/graph.sqlite  (<N> nodes, <M> edges)
✓ Vector index:  <REPO_ROOT>/.pycodekg/vectors.sqlite  (<V> vectors)

Node breakdown:  module=X  class=X  function=X  method=X  symbol=X
Edge breakdown:  CONTAINS=X  CALLS=X  IMPORTS=X  INHERITS=X  ATTR_ACCESS=X
```

Note: MCP client configs do not need to change — they reference the same paths.

---

## Important Rules

- Only pass `--repo` — all other paths default to `.pycodekg/` automatically.
- Use an absolute path for `--repo`.
- Do NOT modify any source files in the target repository.
- If the repo is large (>50k lines of Python), warn that the embedding step may take several minutes.
