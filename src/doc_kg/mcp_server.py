#!/usr/bin/env python3
"""
mcp_server.py — DocKG MCP Server

Serves a document corpus's knowledge graph to any MCP-compatible agent over
the fleet's shared server base, :mod:`kg_utils.mcp`.

The server answers the fleet's canonical tools -- ``stats``, ``query``,
``pack``, ``get_node``, ``neighbors`` -- under the same names as every other
KG server. ``query`` and ``pack`` are DocKG's own: its search fuses dense and
keyword (BM25) seeds, and ``pack`` sizes excerpts in characters and can trace
why each result was retrieved. ``stats``, ``get_node`` and ``neighbors`` are
the shared ones.

The tool list is not kept by hand anywhere: each tool's docstring is its
description, the server's instructions are generated from them, and::

    dockg mcp --manifest

prints the whole list as JSON without opening the graph.

Usage
-----
::

    dockg mcp --repo /path/to/corpus

``--db`` and ``--vectors`` default to ``.dockg/graph.sqlite`` and
``.dockg/vectors.sqlite``; a relative path is taken from ``--repo``.
``dockg-mcp`` is the same command under its older name.

Author: Eric G. Suchanek, PhD

License: Elastic 2.0
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from kg_utils.mcp import Context, KGServer, kg_from, make_server

from doc_kg import DocKG, __version__
from doc_kg.dockg import DEFAULT_MODEL
from doc_kg.store import DEFAULT_RELS

#: Relations ``query`` and ``pack`` follow when the caller names none: the
#: store's defaults plus CO_OCCURS_WITH, as the server has always used.
SERVER_RELS: tuple[str, ...] = (*DEFAULT_RELS, "CO_OCCURS_WITH")

PREAMBLE = (
    "DocKG is a hybrid semantic + structural knowledge graph for a document corpus. "
    "Nodes are documents ('doc:<file>'), sections ('sec:<file>:<heading-slug>'), "
    "chunks ('chunk:<file>:<0000>'), and the topics, entities and keywords drawn "
    "from them ('topic:<slug>', 'entity:<slug>', 'keyword:<slug>'). Edges: CONTAINS "
    "(document → section → chunk), NEXT (reading order), REFERENCES, SIMILAR_TO, "
    "HAS_TOPIC, MENTIONS_ENTITY, HAS_KEYWORD and CO_OCCURS_WITH.\n\n"
    "## Recommended workflows\n\n"
    "- **Orientation**: stats\n"
    "- **Find material on a subject**: query → get_node\n"
    "- **Read it**: pack with a descriptive query; traced=True shows why each "
    "excerpt was retrieved\n"
    "- **Walk the structure**: neighbors(node_id) — a section's chunks, a chunk's "
    "NEXT and SIMILAR_TO neighbours, a topic's members; narrow with rels=[...] or "
    "direction"
)


def query(
    q: str,
    k: int = 8,
    hop: int = 1,
    max_nodes: int = 25,
    rels: list[str] | None = None,
    *,
    ctx: Context,
) -> dict[str, Any]:
    """
    Hybrid search over the corpus: ranked sections, chunks and topics, and the edges among them.

    Seeds fuse dense (vector) and keyword (BM25) matches, then expand through
    the graph. Use ``pack`` instead when you want the text itself.

    :param q: Natural-language query.
    :param k: Seeds to start from (1-100, default 8).
    :param hop: Graph expansion hops from each seed (0-5, default 1).
    :param max_nodes: Most nodes to return (default 25).
    :param rels: Edge types to follow; omit for every relation listed above.
    """
    result = kg_from(ctx).query(
        q, k=k, hop=hop, rels=tuple(rels) if rels else SERVER_RELS, max_nodes=max_nodes
    )
    return result.to_dict()


def pack(
    q: str,
    k: int = 8,
    hop: int = 1,
    max_nodes: int = 15,
    rels: list[str] | None = None,
    max_chars: int = 2000,
    traced: bool = False,
    *,
    ctx: Context,
) -> str:
    """
    Hybrid search rendered as a Markdown pack of text excerpts, ready to read.

    :param q: Natural-language query.
    :param k: Seeds to start from (1-100, default 8).
    :param hop: Graph expansion hops (0-5, default 1).
    :param max_nodes: Most excerpts (default 15).
    :param rels: Edge types to follow; omit for every relation listed above.
    :param max_chars: Longest excerpt, in characters (default 2000).
    :param traced: Attach a provenance path under each excerpt (seed → … →
        node, with a quoted source line at each hop): why it was retrieved.
    """
    result = kg_from(ctx).pack(
        q,
        k=k,
        hop=hop,
        rels=tuple(rels) if rels else SERVER_RELS,
        max_chars=max_chars,
        max_nodes=max_nodes,
        traced=traced,
    )
    return result.to_markdown()


def build_server(
    repo: str | Path,
    db: str | Path | None = None,
    vectors: str | Path | None = None,
    model: str | None = None,
) -> KGServer:
    """Build the DocKG MCP server for one corpus, without opening its graph.

    :param repo: Corpus root the graph was built from.
    :param db: Graph database; ``None`` for ``<repo>/.dockg/graph.sqlite``.
    :param vectors: Vector store; ``None`` for ``<repo>/.dockg/vectors.sqlite``.
    :param model: Embedding model; ``None`` for :data:`DEFAULT_MODEL`.
    :return: The server; serve it with :func:`kg_utils.mcp.run`.
    """
    root = Path(repo).resolve()

    def open_kg() -> DocKG:
        return DocKG(root, db, vectors, model=model or DEFAULT_MODEL)

    server = make_server(
        open_kg, name="dockg", kind="doc", version=__version__, instructions=PREAMBLE
    )
    server.canonical("query")(query)
    server.canonical("pack")(pack)
    return server


def main(argv: list[str] | None = None) -> None:
    """Entry point for ``dockg-mcp``: the same command as ``dockg mcp``.

    :param argv: Arguments; ``None`` for ``sys.argv[1:]``.
    """
    from doc_kg.cli.cmd_mcp import mcp_command  # noqa: PLC0415

    mcp_command.main(args=argv, prog_name="dockg-mcp")


if __name__ == "__main__":
    main()
