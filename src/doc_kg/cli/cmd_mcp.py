"""
cmd_mcp.py

Click subcommand for starting the DocKG MCP server:

  mcp  — start the MCP server (thin wrapper around mcp_server.main)
"""

from __future__ import annotations

import click

from doc_kg.cli.main import cli
from doc_kg.cli.options import repo_option
from doc_kg.dockg import DEFAULT_MODEL


@cli.command("mcp")
@repo_option
@click.option(
    "--db",
    default=".dockg/graph.sqlite",
    type=click.Path(),
    help="SQLite database path.",
)
@click.option(
    "--lancedb",
    default=".dockg/lancedb",
    type=click.Path(),
    help="LanceDB directory path.",
)
@click.option(
    "--model",
    default=DEFAULT_MODEL,
    help="Sentence-transformer model name.",
)
@click.option(
    "--transport",
    type=click.Choice(["stdio", "sse"]),
    default="stdio",
    help="MCP transport protocol.",
)
def mcp(repo: str, db: str, lancedb: str, model: str, transport: str) -> None:
    """Start the DocKG MCP server."""
    try:
        import importlib.util  # pylint: disable=import-outside-toplevel

        if importlib.util.find_spec("mcp") is None:
            raise ImportError
    except ImportError:
        raise click.ClickException("'mcp' package not found. Install with: pip install mcp")

    argv = [
        "--repo",
        repo,
        "--db",
        db,
        "--lancedb",
        lancedb,
        "--model",
        model,
        "--transport",
        transport,
    ]

    from doc_kg.mcp_server import main  # pylint: disable=import-outside-toplevel

    main(argv=argv)
