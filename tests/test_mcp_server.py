"""tests/test_mcp_server.py

Import-level regression tests for doc_kg.mcp_server.

The server builds its ``FastMCP`` instance and registers every tool with
module-level decorators, so an incompatible ``mcp`` release breaks it at
*import* time — and only for people installing from PyPI, since a developer's
pinned lock file keeps working.

mcp 2.0 removed the bundled ``mcp.server.fastmcp`` module (FastMCP was split
out into the standalone ``fastmcp`` package), which makes the import at
``mcp_server.py`` line 16 fail outright. `pyproject.toml` pins ``mcp<2`` for
that reason; these tests fail loudly if the pin is lifted without porting the
server, rather than shipping a broken console script.

Note the failure mode is not uniform across the fleet: KGRAG uses the
low-level ``Server`` API, whose class still imports under mcp 2.0 but whose
decorators were removed — so it fails at *call* time instead, and needs a
different test shape.
"""

from __future__ import annotations

import importlib


def test_server_module_imports():
    """The module must import cleanly against the installed mcp release."""
    importlib.import_module("doc_kg.mcp_server")


def test_fastmcp_import_path_exists():
    """``mcp.server.fastmcp`` must exist — mcp 2.0 removed it.

    Asserted directly so the failure names the actual incompatibility rather
    than surfacing as an opaque ImportError from our own module.
    """
    importlib.import_module("mcp.server.fastmcp")


def test_entry_point_target_exists():
    """``dockg-mcp`` resolves to doc_kg.mcp_server:main."""
    server = importlib.import_module("doc_kg.mcp_server")
    assert callable(server.main)


def test_tools_are_registered():
    """The documented tool surface survives registration."""
    server = importlib.import_module("doc_kg.mcp_server")
    names = {t.name for t in _list_tools(server)}
    assert names, "no tools registered"
    for expected in ("graph_stats", "query_docs", "pack_docs", "get_node"):
        assert expected in names, f"{expected} missing from registered tools"


def _list_tools(server):
    """Return the registered FastMCP tools.

    ``FastMCP.list_tools()`` is async; run it on a private loop rather than
    depending on an async test plugin.
    """
    import asyncio

    return asyncio.run(server.mcp.list_tools())
