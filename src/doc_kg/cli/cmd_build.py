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
from rich.console import Console
from rich.rule import Rule

from doc_kg.cli.group import cli
from doc_kg.cli.options import lancedb_option, model_option, repo_option, sqlite_option
from doc_kg.config import load_exclude_dirs
from doc_kg.kg import DocKG

_console = Console()


@cli.command("build")
@repo_option
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
@click.option(
    "--similar-k",
    type=int,
    default=5,
    show_default=True,
    help=(
        "Max SIMILAR_TO out-edges per chunk (top-k by cosine similarity). "
        "Bounds the graph density on stylistically homogeneous corpora. "
        "Set to 0 to disable the cap (legacy: every pair above --similar-threshold)."
    ),
)
@click.option(
    "--similar-threshold",
    type=float,
    default=0.85,
    show_default=True,
    help="Minimum cosine similarity for a SIMILAR_TO edge.",
)
@click.option(
    "--update",
    is_flag=True,
    default=False,
    help="Incremental update — keep existing data instead of wiping.",
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
def build(
    repo: str,
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
    similar_k: int,
    similar_threshold: float,
    update: bool,
    ext: tuple[str, ...],
    exclude_dir: tuple[str, ...],
) -> None:
    """Build the DocKG from a corpus directory.

    Parses all .md and .txt files under CORPUS_ROOT, builds the structural
    and semantic graph, persists it to SQLite, and indexes it in LanceDB.
    Also discovers SIMILAR_TO edges between semantically related chunks.
    """
    repo_root = Path(repo).resolve()
    db_path = Path(sqlite) if sqlite else repo_root / ".dockg" / "graph.sqlite"
    lancedb_dir = Path(lancedb) if lancedb else repo_root / ".dockg" / "lancedb"
    wipe = not update
    extensions = set(e if e.startswith(".") else f".{e}" for e in ext)
    exclude = load_exclude_dirs(repo_root) | set(exclude_dir)

    kg = DocKG(
        corpus_root=repo_root,
        exclude=exclude or None,
        db_path=db_path,
        lancedb_dir=lancedb_dir,
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

    features = (
        "  ".join(
            f
            for f, on in [
                ("topics", enable_topics),
                ("entities", enable_entities),
                ("keywords", enable_keywords),
            ]
            if on
        )
        or "(none)"
    )

    _console.print(Rule(f"DocKG build — {repo_root.name}", style="bold blue"))
    _console.print(f"  corpus   : {repo_root}")
    _console.print(f"  model    : {model}")
    _console.print(f"  graph store  : {db_path}")
    _console.print(f"  vector index : {lancedb_dir}")
    _console.print(f"  ext      : {', '.join(sorted(extensions))}")
    _console.print(f"  exclude  : {', '.join(sorted(exclude)) if exclude else '(none)'}")
    _console.print(f"  features : {features}")

    # Step 1: Parse corpus → SQLite
    _console.print("\n[bold][1/2][/bold] Parsing corpus \u2192 graph store \u2026")
    graph_stats = kg.build_graph(wipe=wipe)
    for kind, count in sorted(graph_stats.node_counts.items()):
        _console.print(f"  {kind:<12} {count:>6}")
    _console.print(f"  {'─' * 19}")
    _console.print(f"  {'nodes':<12} {graph_stats.total_nodes:>6}  edges {graph_stats.total_edges}")

    # Step 2: SQLite → LanceDB + SIMILAR_TO
    _console.print("\n[bold][2/2][/bold] Embedding nodes \u2192 vector index \u2026")
    idx_stats = kg.index.build(
        kg.store,
        wipe=wipe,
        discover_similar=not no_similar,
        similar_k=similar_k,
        similarity_edge_threshold=similar_threshold,
        quiet=False,
    )
    _console.print(f"  model    : {idx_stats['model_name']}  dim={idx_stats['dim']}")
    _console.print(f"  indexed  : {idx_stats['indexed_rows']} vectors")
    if not no_similar:
        _console.print(f"  SIMILAR_TO: {idx_stats.get('similar_edges_added', 0)} edges")

    _console.print("\n[green]Build complete.[/green]")
    kg.close()


@cli.command("build-graph")
@repo_option
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
    "--update",
    is_flag=True,
    default=False,
    help="Incremental update — keep existing SQLite graph instead of wiping.",
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
    repo: str,
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
    update: bool,
    ext: tuple[str, ...],
    exclude_dir: tuple[str, ...],
) -> None:
    """Build only the SQLite graph from a corpus directory."""
    repo_root = Path(repo).resolve()
    db_path = Path(sqlite) if sqlite else repo_root / ".dockg" / "graph.sqlite"
    wipe = not update
    extensions = set(e if e.startswith(".") else f".{e}" for e in ext)
    exclude = load_exclude_dirs(repo_root) | set(exclude_dir)

    kg = DocKG(
        corpus_root=repo_root,
        db_path=db_path,
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

    _console.print(Rule(f"DocKG build-graph — {repo_root.name}", style="bold blue"))
    _console.print(f"  corpus  : {repo_root}")
    _console.print(f"  graph store : {db_path}")
    _console.print(f"  ext         : {', '.join(sorted(extensions))}")
    _console.print(f"  exclude : {', '.join(sorted(exclude)) if exclude else '(none)'}")

    stats = kg.build_graph(wipe=wipe)
    for kind, count in sorted(stats.node_counts.items()):
        _console.print(f"  {kind:<12} {count:>6}")
    _console.print(f"  {'─' * 19}")
    _console.print(f"  {'nodes':<12} {stats.total_nodes:>6}  edges {stats.total_edges}")
    _console.print("\n[green]Build complete.[/green]")
    kg.close()


@cli.command("build-index")
@repo_option
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
    "--update",
    is_flag=True,
    default=False,
    help="Incremental update — keep existing vectors instead of wiping.",
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
    help="LanceDB write batch size.",
)
@click.option(
    "--encode-batch",
    type=int,
    default=1024,
    show_default=True,
    help="GPU encode batch size (higher = better MPS/CUDA utilisation; tune down if OOM).",
)
def build_index(
    repo: str,
    sqlite: str,
    lancedb: str,
    model: str,
    table: str,
    update: bool,
    no_similar: bool,
    batch: int,
    encode_batch: int,
) -> None:
    """Build only the LanceDB semantic index from an existing SQLite graph."""
    repo_root = Path(repo).resolve()
    db_path = Path(sqlite) if sqlite else repo_root / ".dockg" / "graph.sqlite"
    lancedb_dir = Path(lancedb) if lancedb else repo_root / ".dockg" / "lancedb"
    wipe = not update
    kg = DocKG(
        corpus_root=repo_root,
        db_path=db_path,
        lancedb_dir=lancedb_dir,
        model=model,
        table=table,
    )

    _console.print(Rule(f"DocKG build-index — {db_path.name}", style="bold blue"))
    _console.print(f"  graph store  : {db_path}")
    _console.print(f"  vector index : {lancedb_dir}")
    _console.print(f"  table        : {table}")

    _console.print("\nEmbedding nodes \u2192 vector index \u2026")
    idx_stats = kg.index.build(
        kg.store,
        wipe=wipe,
        batch_size=batch,
        encode_batch_size=encode_batch,
        discover_similar=not no_similar,
        quiet=False,
    )
    _console.print(f"  model    : {idx_stats['model_name']}  dim={idx_stats['dim']}")
    _console.print(f"  indexed  : {idx_stats['indexed_rows']} vectors")
    if not no_similar:
        _console.print(f"  SIMILAR_TO: {idx_stats.get('similar_edges_added', 0)} edges")
    _console.print("\n[green]Build complete.[/green]")
    kg.close()
