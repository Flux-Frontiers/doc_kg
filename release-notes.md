# Release Notes — v0.19.1

> Released: 2026-07-29

A hotfix for 0.19.0. That release went out with an unbounded `mcp>=1.0.0`, and
`mcp` 2.0 has since landed on PyPI — so a clean `pip install doc-kg` now
resolves a combination that `dockg-mcp` cannot import. If you installed 0.19.0
from PyPI, upgrade. If you work from a checkout with a lock file you were never
affected, which is precisely why this reached the index unnoticed.

## What changed

**`mcp` is pinned below 2.0.** mcp 2.0 removed the bundled `mcp.server.fastmcp`
module — FastMCP now ships as the standalone `fastmcp` package — and rebuilt
`mcp.server` around a new set of submodules. DocKG's MCP server imports
`FastMCP` at module scope, so the import fails outright and the console script
dies before registering a single tool. The constraint is now `>=1.0.0,<2`;
lifting it means porting to the standalone package rather than simply widening a
range.

**The gap that let it ship is closed.** The server registers all four tools with
module-level decorators, so an incompatible release breaks at *import* time —
and a developer's pinned lock file masks that entirely, leaving the failure
visible only to someone installing fresh from PyPI. A new test module imports the
server, checks the entry point resolves, and asserts the tool surface survives
registration. One test asserts `mcp.server.fastmcp` exists on its own, so the
next incompatibility names itself instead of surfacing as an opaque
`ImportError` from our own code.

**The break was reproduced, not inferred.** The pin was chosen after installing
mcp 2.0 into a clean environment and confirming that `mcp.server.fastmcp` raises
`ModuleNotFoundError`. Worth knowing if you maintain a sibling package: the
low-level `mcp.server.Server` API *does* still import under 2.0, but its
decorators were removed — so packages built on it fail at call time instead, and
need a different fix and a different test.

## Upgrading

`pip install --upgrade doc-kg`. Nothing to rebuild — no graph, index, or
snapshot format changed, and the only difference in resolved dependencies is
that `mcp` stays on the 1.x line.

If you pinned `doc-kg==0.19.0` and your MCP server stopped starting, this is the
fix. If you install DocKG alongside other KGRAG packages, note that `memory-kg`
is still published with an unbounded `mcp` floor and may pull 2.0 independently
of this release.

---

_Full changelog: [CHANGELOG.md](CHANGELOG.md)_
