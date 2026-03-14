"""
cmd_query.py

Click subcommands for querying DocKG:

  query  — hybrid semantic + graph query, prints a ranked result summary
  pack   — hybrid query + text excerpt packing, outputs Markdown or JSON

Author: Eric G. Suchanek, PhD
"""

from __future__ import annotations

from pathlib import Path

import click

from doc_kg.cli.group import cli
from doc_kg.cli.options import lancedb_option, model_option, repo_option, sqlite_option
from doc_kg.kg import DocKG
from doc_kg.store import DEFAULT_RELS

_DEFAULT_RELS_STR = ",".join(DEFAULT_RELS)


@cli.command("query")
@click.argument("query_text", metavar="QUERY")
@repo_option
@sqlite_option
@lancedb_option
@click.option(
    "--table",
    default="dockg_nodes",
    show_default=True,
    help="LanceDB table name.",
)
@model_option
@click.option("--k", type=int, default=8, show_default=True, help="Top-k semantic hits.")
@click.option("--hop", type=int, default=1, show_default=True, help="Graph expansion hops.")
@click.option(
    "--rels",
    default=_DEFAULT_RELS_STR,
    show_default=True,
    help="Comma-separated edge types to expand.",
)
@click.option(
    "--max-nodes",
    type=int,
    default=25,
    show_default=True,
    help="Maximum nodes to return.",
)
def query(
    query_text: str,
    repo: str,
    sqlite: str,
    lancedb: str,
    table: str,
    model: str,
    k: int,
    hop: int,
    rels: str,
    max_nodes: int,
) -> None:
    """Run a hybrid semantic + graph query and print a ranked result summary."""
    rels_tuple = tuple(r.strip() for r in rels.split(",") if r.strip())

    kg = DocKG(
        corpus_root=Path(repo),
        db_path=Path(sqlite),
        lancedb_dir=Path(lancedb),
        model=model,
        table=table,
    )

    result = kg.query(
        query_text,
        k=k,
        hop=hop,
        rels=rels_tuple,
        max_nodes=max_nodes,
    )
    result.print_summary()
    kg.close()


@cli.command("pack")
@click.argument("query_text", metavar="QUERY")
@repo_option
@sqlite_option
@lancedb_option
@click.option(
    "--table",
    default="dockg_nodes",
    show_default=True,
    help="LanceDB table name.",
)
@model_option
@click.option("--k", type=int, default=8, show_default=True, help="Top-k semantic hits.")
@click.option("--hop", type=int, default=1, show_default=True, help="Graph expansion hops.")
@click.option(
    "--rels",
    default=_DEFAULT_RELS_STR,
    show_default=True,
    help="Comma-separated edge types to expand.",
)
@click.option(
    "--max-chars",
    type=int,
    default=2000,
    show_default=True,
    help="Max characters per text excerpt.",
)
@click.option(
    "--max-nodes",
    type=int,
    default=None,
    help="Max nodes returned in pack (default: no limit).",
)
@click.option(
    "--out",
    type=click.Path(),
    default=None,
    help="Output file path (default: stdout).",
)
@click.option(
    "--fmt",
    type=click.Choice(["md", "json"]),
    default="md",
    show_default=True,
    help="Output format.",
)
def pack(
    query_text: str,
    repo: str,
    sqlite: str,
    lancedb: str,
    table: str,
    model: str,
    k: int,
    hop: int,
    rels: str,
    max_chars: int,
    max_nodes: int | None,
    out: str | None,
    fmt: str,
) -> None:
    """Run a hybrid query and emit text excerpt packs."""
    rels_tuple = tuple(r.strip() for r in rels.split(",") if r.strip())

    kg = DocKG(
        corpus_root=Path(repo),
        db_path=Path(sqlite),
        lancedb_dir=Path(lancedb),
        model=model,
        table=table,
    )

    text_pack = kg.pack(
        query_text,
        k=k,
        hop=hop,
        rels=rels_tuple,
        max_chars=max_chars,
        max_nodes=max_nodes,
    )
    kg.close()

    if out:
        text_pack.save(out, fmt=fmt)
        click.echo(f"OK: wrote pack to {out}")
    else:
        if fmt == "json":
            click.echo(text_pack.to_json())
        else:
            click.echo(text_pack.to_markdown())
