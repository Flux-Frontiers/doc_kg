#!/usr/bin/env python3
"""
mcp_server.py — DocKG MCP Server

Exposes the DocKG hybrid query and text-pack pipeline as Model Context Protocol
(MCP) tools for MCP-compatible agents.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from doc_kg import DocKG
from doc_kg.dockg import DEFAULT_MODEL
from doc_kg.store import DEFAULT_RELS

_kg: DocKG | None = None


def _get_kg() -> DocKG:
    """Return the global DocKG instance, raising if not initialised."""
    if _kg is None:
        raise RuntimeError(
            "DocKG not initialised. Run via 'dockg-mcp --repo /path/to/repo'"
        )
    return _kg


mcp = FastMCP(
    "dockg",
    instructions=(
        "DocKG is a hybrid semantic + structural knowledge graph for document corpora. "
        "Use these tools to query document chunks, sections, topics, entities, and edges."
    ),
)


@mcp.tool()
def query_docs(
    q: str,
    k: int = 8,
    hop: int = 1,
    rels: str = "CONTAINS,NEXT,REFERENCES,SIMILAR_TO,HAS_TOPIC,MENTIONS_ENTITY,HAS_KEYWORD,CO_OCCURS_WITH",
    max_nodes: int = 25,
) -> str:
    """Run hybrid semantic + graph query over DocKG and return JSON."""
    rel_tuple = tuple(r.strip() for r in rels.split(",") if r.strip())
    result = _get_kg().query(
        q,
        k=k,
        hop=hop,
        rels=rel_tuple or DEFAULT_RELS,
        max_nodes=max_nodes,
    )
    return result.to_json()


@mcp.tool()
def pack_docs(
    q: str,
    k: int = 8,
    hop: int = 1,
    rels: str = "CONTAINS,NEXT,REFERENCES,SIMILAR_TO,HAS_TOPIC,MENTIONS_ENTITY,HAS_KEYWORD,CO_OCCURS_WITH",
    max_chars: int = 2000,
    max_nodes: int = 15,
) -> str:
    """Run hybrid query and return Markdown text pack."""
    rel_tuple = tuple(r.strip() for r in rels.split(",") if r.strip())
    pack = _get_kg().pack(
        q,
        k=k,
        hop=hop,
        rels=rel_tuple or DEFAULT_RELS,
        max_chars=max_chars,
        max_nodes=max_nodes,
    )
    return pack.to_markdown()


@mcp.tool()
def get_node(node_id: str) -> str:
    """Fetch a single DocKG node by ID and return JSON."""
    node = _get_kg().node(node_id)
    if node is None:
        return json.dumps({"error": f"Node not found: {node_id!r}"})
    return json.dumps(node, indent=2, ensure_ascii=False)


@mcp.tool()
def graph_stats() -> str:
    """Return node/edge count stats for the current DocKG store."""
    stats = _get_kg().stats()
    return json.dumps(stats, indent=2, ensure_ascii=False)


def _parse_args(argv: list | None = None) -> argparse.Namespace:
    """Parse command-line arguments for the DocKG MCP server."""
    p = argparse.ArgumentParser(
        prog="dockg-mcp",
        description="DocKG MCP server — exposes document graph query tools to AI agents.",
    )
    p.add_argument("--repo", default=".", help="Repository root directory")
    p.add_argument(
        "--db",
        default=".dockg/graph.sqlite",
        help="Path to SQLite graph (default: .dockg/graph.sqlite)",
    )
    p.add_argument(
        "--lancedb",
        default=".dockg/lancedb",
        help="Path to LanceDB directory (default: .dockg/lancedb)",
    )
    p.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Sentence-transformer model name (default: {DEFAULT_MODEL})",
    )
    p.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="MCP transport: stdio (default) or sse",
    )
    return p.parse_args(argv)


def main(argv: list | None = None) -> None:
    """Start the DocKG MCP server and expose tools over MCP transport."""
    global _kg

    args = _parse_args(argv)

    repo = Path(args.repo).resolve()
    db = Path(args.db) if Path(args.db).is_absolute() else repo / args.db
    lancedb_dir = (
        Path(args.lancedb) if Path(args.lancedb).is_absolute() else repo / args.lancedb
    )

    if not db.exists():
        print(
            f"WARNING: SQLite database not found at '{db}'.\\n"
            "Run 'dockg build' first.",
            file=sys.stderr,
        )

    print(
        f"DocKG MCP server starting\\n"
        f"  repo     : {repo}\\n"
        f"  db       : {db}\\n"
        f"  lancedb  : {lancedb_dir}\\n"
        f"  model    : {args.model}\\n"
        f"  transport: {args.transport}",
        file=sys.stderr,
    )

    _kg = DocKG(
        corpus_root=repo,
        db_path=db,
        lancedb_dir=lancedb_dir,
        model=args.model,
    )

    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
