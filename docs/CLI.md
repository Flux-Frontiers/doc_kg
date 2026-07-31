# DocKG CLI Reference

Full flag reference for every `dockg` subcommand. For quick examples and MCP query patterns see [CHEATSHEET.md](CHEATSHEET.md).

---

## Unified CLI

All commands are available via the `dockg` entry point:

```bash
dockg --help
dockg <command> --help
```

Each subcommand also ships as a dedicated `dockg-<name>` script — useful for shell scripts, Makefiles, and CI pipelines with no `poetry run` required.

| Script alias         | Subcommand           | Description                              |
|----------------------|----------------------|------------------------------------------|
| `dockg-build`        | `dockg build`        | Full pipeline: parse → SQLite → vectors  |
| `dockg-build-graph`  | `dockg build-graph`  | SQLite graph only                        |
| `dockg-build-index`  | `dockg build-index`  | Vector index only                        |
| `dockg-query`        | `dockg query`        | Hybrid semantic + structural query       |
| `dockg-pack`         | `dockg pack`         | Source-grounded passage extraction       |
| `dockg-analyze`      | `dockg analyze`      | Corpus health analysis + report          |
| `dockg-snapshot`     | `dockg snapshot`     | Save / list / show / diff snapshots      |
| `dockg-viz`          | `dockg viz`          | Launch Streamlit visualizer              |
| `dockg-mcp`          | `dockg mcp`          | Start MCP server                         |

---

## `dockg build` — Full pipeline

```bash
dockg build CORPUS_ROOT [OPTIONS]
```

Runs the full pipeline: parse documents → SQLite graph → sqlite-vec semantic index.

| Option           | Default                  | Description                                                   |
|------------------|--------------------------|---------------------------------------------------------------|
| `CORPUS_ROOT`    | required                 | Root directory of documents to index                          |
| `--db`           | `.dockg/graph.sqlite`    | SQLite database path                                          |
| `--vectors-path` | `.dockg/vectors.sqlite`  | sqlite-vec store (the default vector index)                                                               |
| `--lancedb`      | `.dockg/lancedb`         | Legacy LanceDB dir (pre-0.20.0 stores; needs the `[lancedb]` extra)                                       |
| `--model`        | `BAAI/bge-small-en-v1.5` | Sentence-transformer embedding model                          |
| `--update`       | off                      | Incremental update — keep existing data instead of wiping     |
| `--no-similar`   | off                      | Skip computing `SIMILAR_TO` edges                             |
| `--exclude-dir`  | —                        | Exclude a directory at every depth (repeatable)               |

---

## `dockg build-graph` — SQLite only

```bash
dockg build-graph CORPUS_ROOT [OPTIONS]
```

Parses documents and writes the SQLite graph. No embedding model required.

| Option           | Default               | Description                              |
|------------------|-----------------------|------------------------------------------|
| `--db`           | `.dockg/graph.sqlite` | SQLite database path                     |
| `--update`       | off                   | Keep existing data instead of wiping     |
| `--exclude-dir`  | —                     | Exclude a directory (repeatable)         |

---

## `dockg build-index` — vector index only

```bash
dockg build-index [OPTIONS]
```

Reads an existing SQLite graph and builds (or rebuilds) the sqlite-vec vector index.

| Option         | Default                  | Description                        |
|----------------|--------------------------|------------------------------------|
| `--db`         | `.dockg/graph.sqlite`    | SQLite database path               |
| `--vectors-path` | `.dockg/vectors.sqlite`  | sqlite-vec store (the default vector index)                                    |
| `--lancedb`    | `.dockg/lancedb`         | Legacy LanceDB dir (pre-0.20.0 stores; needs the `[lancedb]` extra)            |
| `--model`      | `BAAI/bge-small-en-v1.5` | Sentence-transformer model         |
| `--no-similar` | off                      | Skip `SIMILAR_TO` edge computation |

---

## `dockg query` — Hybrid search

```bash
dockg query QUERY [OPTIONS]
```

| Option    | Default                            | Description                       |
|-----------|------------------------------------|-----------------------------------|
| `QUERY`   | required                           | Natural-language search string    |
| `--db`    | `.dockg/graph.sqlite`              | SQLite database path              |
| `--vectors-path` | `.dockg/vectors.sqlite`          | sqlite-vec store (the default vector index)                                   |
| `--lancedb` | `.dockg/lancedb`                 | Legacy LanceDB dir (pre-0.20.0 stores; needs the `[lancedb]` extra)           |
| `--k`     | `8`                                | Top-K semantic seed hits          |
| `--hop`   | `1`                                | Graph expansion hops              |
| `--rels`  | `CONTAINS,NEXT,REFERENCES,SIMILAR_TO` | Edge types to traverse         |

---

## `dockg pack` — Passage extraction

```bash
dockg pack QUERY [OPTIONS]
```

| Option        | Default               | Description                              |
|---------------|-----------------------|------------------------------------------|
| `QUERY`       | required              | Natural-language search string           |
| `--db`        | `.dockg/graph.sqlite` | SQLite database path                     |
| `--vectors-path` | `.dockg/vectors.sqlite` | sqlite-vec store (the default vector index)                                          |
| `--lancedb`   | `.dockg/lancedb`      | Legacy LanceDB dir (pre-0.20.0 stores; needs the `[lancedb]` extra)                  |
| `--k`         | `8`                   | Top-K semantic seed hits                 |
| `--hop`       | `1`                   | Graph expansion hops                     |
| `--format`    | `md`                  | Output format: `md` or `json`            |
| `--out`       | stdout                | Output file path                         |
| `--max-chars` | `12000`               | Max total characters in pack             |
| `--max-nodes` | `50`                  | Max nodes included                       |

---

## `dockg analyze` — Corpus health report

```bash
dockg analyze [CORPUS_ROOT] [OPTIONS]
```

Runs the full `DocKGAnalyzer` pipeline — baseline stats, per-document metrics, semantic coverage, orphan detection, hot chunks, and actionable insights.

| Option     | Default               | Description                            |
|------------|-----------------------|----------------------------------------|
| `--db`     | `.dockg/graph.sqlite` | SQLite database path                   |
| `--vectors-path` | `.dockg/vectors.sqlite` | sqlite-vec store (the default vector index)                                        |
| `--lancedb`| `.dockg/lancedb`      | Legacy LanceDB dir (pre-0.20.0 stores; needs the `[lancedb]` extra)                |
| `--output` | stdout                | Markdown report output file            |
| `--json`   | off                   | Also emit a JSON snapshot              |
| `--quiet`  | off                   | Suppress Rich output; exit 1 on issues |

---

## `dockg snapshot` — Temporal snapshots

```bash
dockg snapshot save VERSION      # capture current graph metrics
dockg snapshot list              # list all saved snapshots with deltas
dockg snapshot show COMMIT       # full detail + delta vs previous
dockg snapshot diff KEY_A KEY_B  # side-by-side comparison
```

Snapshots are stored in `.dockg/snapshots/`. See [SNAPSHOTS.md](SNAPSHOTS.md) for a full guide.

---

## `dockg viz` — Streamlit visualizer

```bash
dockg viz [OPTIONS]
```

Requires the `[viz]` extra: `pip install 'doc-kg[viz]'`.

| Option       | Default               | Description                  |
|--------------|-----------------------|------------------------------|
| `--db`       | `.dockg/graph.sqlite` | SQLite database path         |
| `--port`     | `8501`                | Streamlit port               |
| `--no-browser` | off               | Suppress automatic browser launch |

---

## `dockg mcp` — MCP server

```bash
dockg mcp [OPTIONS]
```

| Option        | Default               | Description                                 |
|---------------|-----------------------|---------------------------------------------|
| `--repo`      | `.`                   | Corpus root                                 |
| `--db`        | `.dockg/graph.sqlite` | SQLite database path                        |
| `--vectors-path` | `.dockg/vectors.sqlite` | sqlite-vec store (the default vector index)                                             |
| `--lancedb`   | `.dockg/lancedb`      | Legacy LanceDB dir (pre-0.20.0 stores; needs the `[lancedb]` extra)                     |
| `--model`     | `BAAI/bge-small-en-v1.5` | Embedding model                          |
| `--transport` | `stdio`               | Transport mode: `stdio` (agents) or `sse`   |

See [MCP.md](MCP.md) for provider-specific config (Claude Code, GitHub Copilot, Claude Desktop, Cline).

---

## Excluding directories

Exclusions are **additive** across three levels:

1. **Built-in** — `.git`, `.venv`, `__pycache__`, `.dockg`, `.mypy_cache`, etc.
2. **Config** — `[tool.dockg].exclude` in `pyproject.toml` (auto-loaded from corpus root)
3. **CLI** — `--exclude-dir` flags

```toml
# pyproject.toml
[tool.dockg]
exclude = ["archive", "vendor", "generated"]
```

```bash
# CLI adds to the above — all four are excluded plus built-ins
dockg build docs/ --exclude-dir node_modules --exclude-dir dist
```

---

## Git hooks (optional)

Install a pre-commit hook that automatically captures a graph metrics snapshot before each commit:

```bash
dockg install-hooks          # via CLI
bash scripts/install-hooks.sh  # via standalone script
```

Skip the hook for a specific commit:

```bash
DOCKG_SKIP_SNAPSHOT=1 git commit -m "message"
```

---

## Download embedding model for offline use

The default model (`BAAI/bge-small-en-v1.5`) is fetched from HuggingFace on first use. Pre-download for air-gapped or CI environments:

```bash
dockg download-model
dockg download-model --model BAAI/bge-small-en-v1.5
```

Override the cache directory:

```bash
export KGRAG_MODEL_DIR=/path/to/shared/models
```
