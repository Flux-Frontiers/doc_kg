"""
cmd_build.py

Click subcommands for building the DocKG:

    build       — full pipeline: parse corpus → SQLite → LanceDB + SIMILAR_TO edges
    build-graph — parse corpus → SQLite only
    build-index — SQLite → LanceDB + optional SIMILAR_TO edges

Author: Eric G. Suchanek, PhD
"""

from __future__ import annotations

from pathlib import Path

import click

from doc_kg.cli.main import cli
from doc_kg.cli.options import lancedb_option, model_option, sqlite_option
from doc_kg.config import load_exclude_dirs
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
    "--enable-topics/--no-topics",
    default=True,
    show_default=True,
    help="Enable chunk->topic extraction and HAS_TOPIC edges.",
)
@click.option(
    "--enable-entities/--no-entities",
    default=True,
    show_default=True,
    help="Enable chunk->entity extraction and MENTIONS_ENTITY edges.",
)
@click.option(
    "--enable-keywords/--no-keywords",
    default=True,
    show_default=True,
    help="Enable chunk->keyword extraction and HAS_KEYWORD edges.",
)
@click.option(
    "--emit-cooccur/--no-cooccur",
    default=True,
    show_default=True,
    help="Emit CO_OCCURS_WITH edges among semantic nodes in each chunk.",
)
@click.option(
    "--cooccur-window",
    type=int,
    default=1,
    show_default=True,
    help="Co-occurrence window metadata for emitted CO_OCCURS_WITH edges.",
)
@click.option(
    "--topic-threshold",
    type=float,
    default=0.2,
    show_default=True,
    help="Topic confidence threshold in [0, 1].",
)
@click.option(
    "--topics-file",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="Optional JSON/YAML topic catalog file.",
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
@click.option(
    "--exclude-dir",
    multiple=True,
    metavar="DIR",
    help=(
        "Directory name to exclude at every depth during the file walk (repeatable). "
        "Merged with [tool.dockg].exclude from pyproject.toml."
    ),
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
    enable_topics: bool,
    enable_entities: bool,
    enable_keywords: bool,
    emit_cooccur: bool,
    cooccur_window: int,
    topic_threshold: float,
    topics_file: str | None,
    no_similar: bool,
    wipe: bool,
    ext: tuple[str, ...],
    exclude_dir: tuple[str, ...],
) -> None:
    """Build the DocKG from a corpus directory.

    Parses all .md and .txt files under CORPUS_ROOT, builds the structural
    and semantic graph, persists it to SQLite, and indexes it in LanceDB.
    Also discovers SIMILAR_TO edges between semantically related chunks.
    """
    extensions = set(e if e.startswith(".") else f".{e}" for e in ext)
    exclude = load_exclude_dirs(corpus_root) | set(exclude_dir)

    kg = DocKG(
        corpus_root=Path(corpus_root),
        exclude=exclude or None,
        db_path=Path(sqlite),
        lancedb_dir=Path(lancedb),
        model=model,
        table=table,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        similarity_threshold=similarity_threshold,
        enable_topics=enable_topics,
        enable_entities=enable_entities,
        enable_keywords=enable_keywords,
        emit_cooccur=emit_cooccur,
        cooccur_window=cooccur_window,
        topic_threshold=topic_threshold,
        topics_file=topics_file,
    )

    # Override graph extensions if provided
    if extensions:
        kg.graph.extensions = extensions

    click.echo(f"Building DocKG from: {corpus_root}")
    click.echo(f"  model    : {model}")
    click.echo(f"  sqlite   : {sqlite}")
    click.echo(f"  lancedb  : {lancedb}")
    click.echo(f"  ext      : {', '.join(sorted(extensions))}")
    click.echo(f"  exclude  : {', '.join(sorted(exclude)) if exclude else '(none)'}")
    click.echo(f"  topics   : {'on' if enable_topics else 'off'}")
    click.echo(f"  entities : {'on' if enable_entities else 'off'}")
    click.echo(f"  keywords : {'on' if enable_keywords else 'off'}")

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


@cli.command("build-graph")
@click.argument("corpus_root", default=".", type=click.Path(exists=True, file_okay=False))
@sqlite_option
@model_option
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
    "--enable-topics/--no-topics",
    default=True,
    show_default=True,
    help="Enable chunk->topic extraction and HAS_TOPIC edges.",
)
@click.option(
    "--enable-entities/--no-entities",
    default=True,
    show_default=True,
    help="Enable chunk->entity extraction and MENTIONS_ENTITY edges.",
)
@click.option(
    "--enable-keywords/--no-keywords",
    default=True,
    show_default=True,
    help="Enable chunk->keyword extraction and HAS_KEYWORD edges.",
)
@click.option(
    "--emit-cooccur/--no-cooccur",
    default=True,
    show_default=True,
    help="Emit CO_OCCURS_WITH edges among semantic nodes in each chunk.",
)
@click.option(
    "--cooccur-window",
    type=int,
    default=1,
    show_default=True,
    help="Co-occurrence window metadata for emitted CO_OCCURS_WITH edges.",
)
@click.option(
    "--topic-threshold",
    type=float,
    default=0.2,
    show_default=True,
    help="Topic confidence threshold in [0, 1].",
)
@click.option(
    "--topics-file",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="Optional JSON/YAML topic catalog file.",
)
@click.option(
    "--wipe",
    is_flag=True,
    default=False,
    help="Wipe existing SQLite graph before building.",
)
@click.option(
    "--ext",
    multiple=True,
    default=(".md", ".txt"),
    show_default=True,
    help="File extensions to include (repeatable).",
)
@click.option(
    "--exclude-dir",
    multiple=True,
    metavar="DIR",
    help=(
        "Directory name to exclude at every depth during the file walk (repeatable). "
        "Merged with [tool.dockg].exclude from pyproject.toml."
    ),
)
def build_graph(
    corpus_root: str,
    sqlite: str,
    model: str,
    chunk_size: int,
    chunk_overlap: int,
    similarity_threshold: float,
    enable_topics: bool,
    enable_entities: bool,
    enable_keywords: bool,
    emit_cooccur: bool,
    cooccur_window: int,
    topic_threshold: float,
    topics_file: str | None,
    wipe: bool,
    ext: tuple[str, ...],
    exclude_dir: tuple[str, ...],
) -> None:
    """Build only the SQLite graph from a corpus directory."""
    extensions = set(e if e.startswith(".") else f".{e}" for e in ext)
    exclude = load_exclude_dirs(corpus_root) | set(exclude_dir)

    kg = DocKG(
        corpus_root=Path(corpus_root),
        db_path=Path(sqlite),
        exclude=exclude or None,
        model=model,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        similarity_threshold=similarity_threshold,
        enable_topics=enable_topics,
        enable_entities=enable_entities,
        enable_keywords=enable_keywords,
        emit_cooccur=emit_cooccur,
        cooccur_window=cooccur_window,
        topic_threshold=topic_threshold,
        topics_file=topics_file,
    )

    if extensions:
        kg.graph.extensions = extensions

    click.echo(f"Building DocKG graph from: {corpus_root}")
    click.echo(f"  sqlite   : {sqlite}")
    click.echo(f"  model    : {model}")
    click.echo(f"  ext      : {', '.join(sorted(extensions))}")
    click.echo(f"  exclude  : {', '.join(sorted(exclude)) if exclude else '(none)'}")

    stats = kg.build_graph(wipe=wipe)
    click.echo(f"OK: nodes={stats.total_nodes} edges={stats.total_edges} db={sqlite}")
    kg.close()


@cli.command("build-index")
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
    "--wipe",
    is_flag=True,
    default=False,
    help="Delete existing vectors before indexing.",
)
@click.option(
    "--no-similar",
    is_flag=True,
    default=False,
    help="Skip SIMILAR_TO edge discovery after indexing.",
)
@click.option(
    "--batch",
    type=int,
    default=256,
    show_default=True,
    help="Embedding batch size.",
)
def build_index(
    corpus_root: str,
    sqlite: str,
    lancedb: str,
    model: str,
    table: str,
    wipe: bool,
    no_similar: bool,
    batch: int,
) -> None:
    """Build only the LanceDB semantic index from an existing SQLite graph."""
    kg = DocKG(
        corpus_root=Path(corpus_root),
        db_path=Path(sqlite),
        lancedb_dir=Path(lancedb),
        model=model,
        table=table,
    )

    click.echo(f"Building DocKG index from SQLite: {sqlite}")
    click.echo(f"  lancedb  : {lancedb}")
    click.echo(f"  model    : {model}")
    click.echo(f"  table    : {table}")

    idx_stats = kg.index.build(
        kg.store,
        wipe=wipe,
        batch_size=batch,
        discover_similar=not no_similar,
    )
    click.echo(
        "OK: "
        f"indexed_rows={idx_stats['indexed_rows']} "
        f"dim={idx_stats['dim']} "
        f"table={idx_stats['table']} "
        f"lancedb_dir={idx_stats['lancedb_dir']}"
    )
    if not no_similar:
        click.echo(f"SIMILAR_TO edges: {idx_stats.get('similar_edges_added', 0)}")
    kg.close()
