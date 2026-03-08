# DocKG Action

A GitHub composite action that indexes a document corpus into a
[DocKG](https://github.com/Flux-Frontiers/doc_kg) knowledge graph and runs a
thorough analysis.

The action:

1. Installs `doc-kg` from PyPI.
2. Builds a SQLite knowledge graph from the corpus (`dockg-build-graph`).
3. Builds a LanceDB semantic index using a SentenceTransformer model (`dockg-build-index`).
4. Runs `dockg-analyze` to produce a Markdown report and JSON snapshot.
5. Caches the `.dockg/` directory keyed on a hash of all `*.md` and `*.txt` files.
6. Uploads the report and JSON as workflow artifacts.
7. Optionally posts a summary comment to the pull request.
8. Optionally exits non-zero when issues are detected.

---

## Quick start

```yaml
# .github/workflows/dockg.yml
name: DocKG Analysis

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

permissions:
  contents: read
  pull-requests: write   # only needed for post-comment: "true"

jobs:
  analyse:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: ./.github/actions/dockg-action
        with:
          post-comment: "true"
          github-token: ${{ secrets.GITHUB_TOKEN }}
```

---

## Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `python-version` | No | `"3.12"` | Python version (>=3.10, <3.13) |
| `corpus-path` | No | `"."` | Path to the corpus to analyse, relative to the workspace root |
| `report-path` | No | `"dockg_report.md"` | Output path for the Markdown analysis report |
| `json-path` | No | `"dockg_results.json"` | Output path for the JSON analysis snapshot |
| `model` | No | `"all-mpnet-base-v2"` | SentenceTransformer model used for semantic indexing |
| `post-comment` | No | `"false"` | Post an analysis summary to the pull request (`"true"` / `"false"`) |
| `fail-on-issues` | No | `"false"` | Exit non-zero when issues are detected (`"true"` / `"false"`) |
| `github-token` | No | `${{ github.token }}` | Token for posting PR comments (only needed when `post-comment` is `"true"`) |

---

## Outputs

| Output | Description |
|--------|-------------|
| `report-path` | Absolute path to the generated Markdown report |
| `total-nodes` | Total graph nodes analysed |
| `issues-count` | Number of issues detected |

### Consuming outputs

```yaml
- uses: ./.github/actions/dockg-action
  id: dockg
  with:
    post-comment: "false"

- name: Print summary
  run: |
    echo "Nodes   : ${{ steps.dockg.outputs.total-nodes }}"
    echo "Issues  : ${{ steps.dockg.outputs.issues-count }}"
    echo "Report  : ${{ steps.dockg.outputs.report-path }}"
```

---

## Caching

The action caches the `.dockg/` directory (SQLite graph + LanceDB index) using
`actions/cache@v4`. The cache key is:

```
dockg-<runner-os>-<hashFiles('**/*.md', '**/*.txt')>
```

When no document file has changed since the last successful run, the build steps
are skipped and the cached index is used directly. The analysis step always runs
to produce a fresh report.

A fallback restore key `dockg-<runner-os>-` is set so a partial cache is
preferred over a full rebuild when only a few files have changed.

---

## Artifacts

The action uploads a single artifact named `dockg-analysis` containing:

- `dockg_report.md` — Markdown analysis report (configurable via `report-path`)
- `dockg_results.json` — JSON snapshot with full metrics (configurable via `json-path`)

Artifacts are retained for **30 days** by default.

---

## PR comment

When `post-comment: "true"` is set and the workflow is triggered by a
`pull_request` event, the action posts a summary comment to the PR.

The comment includes:

- Total node count
- Issues badge (pass / warning with count)
- Collapsible block with the first 100 lines of the Markdown report

On subsequent runs the existing comment is updated in-place rather than creating
a new one, so the PR comment thread stays clean.

**Required permissions:**

```yaml
permissions:
  pull-requests: write
```

---

## Fail on issues

When `fail-on-issues: "true"` is set, the action exits with a non-zero status
code if the analysis detects any issues. The error message includes the issue
count and report path.

This is useful as a quality gate in CI:

```yaml
- uses: ./.github/actions/dockg-action
  with:
    fail-on-issues: "true"
```

---

## Examples

### Minimal — report only

```yaml
- uses: ./.github/actions/dockg-action
```

### Custom paths and model

```yaml
- uses: ./.github/actions/dockg-action
  with:
    python-version: "3.11"
    corpus-path: "docs"
    report-path: "reports/analysis.md"
    json-path: "reports/analysis.json"
    model: "all-mpnet-base-v2"
```

### Analyse a subdirectory with PR comment

```yaml
- uses: ./.github/actions/dockg-action
  with:
    corpus-path: "docs"
    post-comment: "true"
    github-token: ${{ secrets.GITHUB_TOKEN }}
```

### Strict quality gate

```yaml
- uses: ./.github/actions/dockg-action
  with:
    fail-on-issues: "true"
```

### Full configuration

```yaml
name: DocKG Analysis

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

permissions:
  contents: read
  pull-requests: write

jobs:
  dockg:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: ./.github/actions/dockg-action
        id: analysis
        with:
          python-version: "3.12"
          corpus-path: "."
          report-path: "dockg_report.md"
          json-path: "dockg_results.json"
          model: "all-mpnet-base-v2"
          post-comment: "true"
          fail-on-issues: "false"
          github-token: ${{ secrets.GITHUB_TOKEN }}

      - name: Summary
        run: |
          echo "Nodes  : ${{ steps.analysis.outputs.total-nodes }}"
          echo "Issues : ${{ steps.analysis.outputs.issues-count }}"
```

---

## Pipeline internals

The action runs these CLI tools from the `doc-kg` package in order:

| Step | CLI | Purpose |
|------|-----|---------|
| 1 | `dockg-build-graph` | Walk corpus, chunk documents, write nodes and edges to SQLite |
| 2 | `dockg-build-index` | Embed chunks with SentenceTransformer, write vectors to LanceDB |
| 3 | `dockg-analyze` | Run multi-phase corpus analysis, write Markdown + JSON |

Steps 1 and 2 are skipped on cache hit. Step 3 always runs.

---

## Requirements

- Python >=3.10, <3.13
- `doc-kg` from PyPI (installed automatically)
- `ubuntu-latest`, `macos-latest`, or `windows-latest` runner

---

## Repository structure

```
doc_kg/
├── .github/
│   ├── actions/
│   │   └── dockg-action/
│   │       ├── action.yml                        # Composite action definition
│   │       └── README.md                         # This file
│   └── workflows/
│       ├── ci.yml
│       ├── publish.yml
│       └── snapshots.yml
└── src/
    └── ...
```

---

## License

[PolyForm Noncommercial 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0/)
