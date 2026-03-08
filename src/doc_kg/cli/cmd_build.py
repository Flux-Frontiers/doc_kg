"""
cmd_build.py

Click subcommand for building the DocKG:

  build  — full pipeline: parse corpus → SQLite → LanceDB + SIMILAR_TO edges

Author: Eric G. Suchanek, PhD
"""

from __future__ import annotations

from pathlib import Path

import click

from doc_kg.cli.main import cli
from doc_kg.cli.options import lancedb_option, model_option, sqlite_option
from doc_kg.kg import DocKG


@cli.command("build")
@click.argument("corpus_root", default=".", type=click.Path(exists=True, file_okay=False))
@sqlite_option
@lancedb_option
@model_option
@click.option(
    "--table",
    default="dockg_nodes",
    show_default=True,
    help="LanceDB table name.",
)
@click.option(
    "--chunk-size",
    type=int,
    default=512,
    show_default=True,
    help="Approximate max characters per chunk.",
)
@click.option(
    "--chunk-overlap",
    type=int,
    default=64,
    show_default=True,
    help="Character overlap between consecutive chunks.",
)
@click.option(
    "--similarity-threshold",
    type=float,
    default=0.75,
    show_default=True,
    help="Cosine similarity threshold for semantic split detection.",
)
@click.option(
    "--no-similar",
    is_flag=True,
    default=False,
    help="Skip SIMILAR_TO edge discovery after indexing.",
)
@click.option("--wipe", is_flag=True, default=False, help="Wipe existing data before building.")
@click.option(
    "--ext",
    multiple=True,
    default=(".md", ".txt"),
    show_default=True,
    help="File extensions to include (repeatable).",
)
def build(
    corpus_root: str,
    sqlite: str,
    lancedb: str,
    model: str,
    table: str,
    chunk_size: int,
    chunk_overlap: int,
    similarity_threshold: float,
    no_similar: bool,
    wipe: bool,
    ext: tuple[str, ...],
) -> None:
    """Build the DocKG from a corpus directory.

    Parses all .md and .txt files under CORPUS_ROOT, builds the structural
    and semantic graph, persists it to SQLite, and indexes it in LanceDB.
    Also discovers SIMILAR_TO edges between semantically related chunks.
    """
    extensions = set(e if e.startswith(".") else f".{e}" for e in ext)

    kg = DocKG(
        corpus_root=Path(corpus_root),
        db_path=Path(sqlite),
        lancedb_dir=Path(lancedb),
        model=model,
        table=table,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        similarity_threshold=similarity_threshold,
    )

    # Override graph extensions if provided
    if extensions:
        kg.graph.extensions = extensions

    click.echo(f"Building DocKG from: {corpus_root}")
    click.echo(f"  model    : {model}")
    click.echo(f"  sqlite   : {sqlite}")
    click.echo(f"  lancedb  : {lancedb}")
    click.echo(f"  ext      : {', '.join(sorted(extensions))}")

    # Step 1: Parse corpus → SQLite
    click.echo("\n[1/2] Parsing corpus → SQLite …")
    graph_stats = kg.build_graph(wipe=wipe)
    click.echo(f"      nodes: {graph_stats.total_nodes}  {graph_stats.node_counts}")
    click.echo(f"      edges: {graph_stats.total_edges}  {graph_stats.edge_counts}")

    # Step 2: SQLite → LanceDB + SIMILAR_TO
    click.echo("\n[2/2] Embedding nodes → LanceDB …")
    # Pass discover_similar flag through index.build()
    idx_stats = kg.index.build(
        kg.store,
        wipe=wipe,
        discover_similar=not no_similar,
    )
    click.echo(f"      indexed: {idx_stats['indexed_rows']} vectors  dim={idx_stats['dim']}")
    if not no_similar:
        click.echo(f"      SIMILAR_TO edges: {idx_stats.get('similar_edges_added', 0)}")

    click.echo("\nOK: DocKG build complete.")
    kg.close()
