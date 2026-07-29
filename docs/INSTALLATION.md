# DocKG — Installation Guide

## Requirements

- Python ≥ 3.12, < 3.14
- `pip` or `poetry`

---

## Quick install

```bash
pip install doc-kg
```

That's the recommended path for most users. The core runtime includes the graph store, vector index, chunker, CLI, and MCP server.

---

## Install variants

```bash
# Core only (CLI + MCP, no visualizer)
pip install doc-kg

# With Streamlit / Plotly / PyVis visualizer
pip install 'doc-kg[viz]'

# Everything above
pip install 'doc-kg[all]'

# Development (adds pytest, ruff, mypy, pre-commit, pdoc)
pip install 'doc-kg[dev]'
```

**Cross-KG siblings** (PyCodeKG, KGRAG, AgentKG) are deliberately *not* declared
as extras of `doc-kg`. Each sibling pins its own `transformers` range, and
declaring them here forces the resolver to reconcile every published sibling's
pin against this one — which deadlocks, since `doc-kg` and `pycode-kg` each
depend on the other. Install whichever you need by hand, after `doc-kg`:

```bash
pip install pycode-kg
pip install 'kg-rag @ git+https://github.com/Flux-Frontiers/KGRAG.git'
```

**AgentKG** is not yet on PyPI — install it separately if needed:

```bash
pip install git+https://github.com/Flux-Frontiers/agent_kg.git
```

---

## Poetry install

```bash
poetry add doc-kg                            # core
poetry add 'doc-kg[viz]'                     # core + visualizer
poetry add pycode-kg                         # KG integrations, added separately
poetry add --group dev 'doc-kg[dev]'         # dev tools
```

---

## First-time setup

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install 'doc-kg[dev]'

# Index your corpus
dockg build .

# Run a query
dockg query "your topic"
```

---

## Editable install (contributor)

```bash
git clone https://github.com/Flux-Frontiers/doc_kg.git
cd doc_kg
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pre-commit install
pytest
```

---

## MCP server setup

Start the server:

```bash
dockg-mcp --repo /path/to/your/corpus
```

### Claude Code / Kilo Code

Add to `.mcp.json` in your project root:

```json
{
  "mcpServers": {
    "dockg": {
      "command": "dockg-mcp",
      "args": ["--repo", "."]
    }
  }
}
```

### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "dockg": {
      "command": "/path/to/.venv/bin/dockg-mcp",
      "args": ["--repo", "/path/to/your/corpus"]
    }
  }
}
```

### GitHub Copilot (VS Code)

Add to `.vscode/mcp.json`:

```json
{
  "servers": {
    "dockg": {
      "type": "stdio",
      "command": "dockg-mcp",
      "args": ["--repo", "."]
    }
  }
}
```

### Cline

Add to Cline's MCP settings with the same `stdio` transport and `dockg-mcp` command.

---

## Pre-commit hooks

DocKG ships a pre-commit hook that rebuilds the graph on every commit so the index stays current:

```bash
pre-commit install
```

The hook configuration is in `.pre-commit-config.yaml`. To rebuild manually:

```bash
dockg build .
```

---

## Offline model cache

The sentence-transformer (`BAAI/bge-small-en-v1.5`) is downloaded once and cached. To pre-cache it for offline use:

```bash
dockg download-model
```

Override the cache location with the `KGRAG_MODEL_DIR` environment variable.

---

## Troubleshooting

**`dockg: command not found`** — activate your virtual environment or use `python -m doc_kg`.

**Slow first build** — the model downloads on first run (~90 MB). Subsequent builds use the local cache.

**`lancedb` version conflict** — DocKG requires `lancedb>=0.29.0`. If you see API errors, upgrade: `pip install --upgrade lancedb`.

**Empty query results** — run `dockg build .` first. The graph must be indexed before querying.
