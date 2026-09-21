# Release Notes -- v0.27.0

> Released: 2026-09-20

The MCP server closes the graph on shutdown, `query()` and `pack()` reject
bad arguments before touching the index, and the pre-commit hook `dockg
install-hooks` writes finds `dockg` on `PATH` instead of assuming a repo
venv. Together they make DocKG a well-behaved global tool, which is what the
fleet decided it should be.

## What changed

**Tools are global, and the hook says so.** The hook template had
`$REPO_ROOT/.venv/bin/dockg` hard-wired with `|| exit 1`, the shape that left
a sibling repo's hooks failing silently for weeks. It now resolves `dockg`
from `PATH`, the global `uv tool` install, and falls back to a `.venv` copy
only if one exists. Re-run `dockg install-hooks --force` in any repo to pick
it up. The template had no test; it has seven. In the same spirit the `kg`
Poetry group is gone: it held `pycode-kg`, a tool this repo runs but never
imports, and every fleet clone carrying such a copy was a lock entry that
drifted on each release.

**The server cleans up after itself.** `dockg-mcp` closes the graph's SQLite
connection when it shuts down, via `FastMCP(lifespan=...)`, on both the
stdio and SSE transports. It is verified through the MCP SDK's in-process
transport, a real server lifecycle rather than a mocked `close`.

**Arguments are checked once, in one place.** `DocKG.query()` and `pack()`
use `kg_utils.validation` from kgmodule-utils 0.23.0: an empty query, `k`
outside 1 to 100, `hop` outside 0 to 5 or `max_nodes` outside 1 to 500 raises
`ValueError` naming the parameter. `hop=0` and `pack(max_nodes=None)` remain
valid. `DocKG` is not a `KGModule` subclass, so it calls the shared functions
itself rather than inheriting the check.

**The docs stopped pointing users at a venv.** Every worked `.mcp.json`,
Claude Desktop and VS Code example had `"command":
"/absolute/path/to/repo/.venv/bin/dockg"`. They say `dockg` now, with a note
that it is the global tool.

## Upgrading

No rebuild and no migration. `kgmodule-utils` must be at least 0.23.0. A
caller passing an out-of-range `k`, `hop` or `max_nodes`, or an empty query,
now gets a `ValueError` instead of a silent result. If this repo's tooling
was installed with `poetry install --with kg`, drop the `kg`: `pycodekg` comes
from `uv tool install pycode-kg`. After upgrading the global tool, re-run
`dockg install-hooks --force` wherever the hook is installed.

---

_Full changelog: [CHANGELOG.md](CHANGELOG.md)_
