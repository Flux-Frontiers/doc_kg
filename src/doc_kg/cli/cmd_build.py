"""
cmd_build.py

Click subcommands for building the DocKG:

    build       — full pipeline: parse corpus → SQLite → vector index + SIMILAR_TO edges
    build-graph — parse corpus → SQLite only
    build-index — SQLite → vector index + optional SIMILAR_TO edges
    build-embeddings — SQLite → embedding cache JSON only
    build-index-from-cache — embedding cache JSON → vector index
    build-two-phase — SQLite → embedding cache → vector index (stable pipeline)
    convert-index — legacy LanceDB store → sqlite-vec store (no re-embedding)

The vector index is a sqlite-vec store at ``<repo>/.dockg/vectors.sqlite``.  The
``--lancedb``/``--table`` options address the pre-0.20.0 LanceDB store, which is
read-only legacy and needs the ``[lancedb]`` extra; see ``--vector-backend``.

Author: Eric G. Suchanek, PhD
"""

from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console
from rich.rule import Rule

from doc_kg.cli.group import cli
from doc_kg.cli.options import (
    lancedb_option,
    model_option,
    repo_option,
    sqlite_option,
    vector_backend_option,
    vectors_path_option,
)
from doc_kg.config import load_exclude_dirs
from doc_kg.kg import DocKG

_console = Console()
_INDEX_KIND_CHOICES = ["document", "section", "chunk", "topic", "entity", "keyword"]


def _parse_topics_prefix(topics_prefix: tuple[str, ...]) -> dict[str, str]:
    """Parse ``PREFIX=FILE`` pairs from ``--topics-prefix`` into a mapping.

    :param topics_prefix: Tuple of ``"PREFIX=FILE"`` strings.
    :return: ``{prefix: file_path}`` dict, empty if no entries provided.
    """
    result: dict[str, str] = {}
    for entry in topics_prefix:
        if "=" not in entry:
            raise click.BadParameter(
                f"--topics-prefix must be in PREFIX=FILE format, got: {entry!r}"
            )
        prefix, _, file_path = entry.partition("=")
        result[prefix.strip()] = file_path.strip()
    return result


@cli.command("build")
@repo_option
@sqlite_option
@lancedb_option
@vector_backend_option
@vectors_path_option
@model_option
@click.option(
    "--table",
    default="dockg_nodes",
    show_default=True,
    help="LanceDB table name (legacy backend only; ignored by sqlite-vec).",
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
    "--topics-prefix",
    multiple=True,
    metavar="PREFIX=FILE",
    help=(
        "Per-path topic catalog override (repeatable). "
        "Format: PREFIX=PATH_TO_YAML, e.g. "
        "'sacred-texts/=/path/to/sacred_texts_topics.yaml'. "
        "First matching prefix wins; overrides --topics-file for matched files."
    ),
)
@click.option(
    "--chunk-strategy",
    type=click.Choice(["semantic", "sentence_group", "fixed", "verse"]),
    default="semantic",
    show_default=True,
    help=(
        "Chunking strategy. 'semantic' (default) auto-detects verse documents "
        "and switches to the verse chunker automatically. "
        "Use 'verse' to force verse mode for all files."
    ),
)
@click.option(
    "--kmeans-model",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help=(
        "Path to a *.kmeans.joblib model produced by 'dockg pipeline discover-topics'. "
        "Enables embedding-based K-means topic assignment (near-100% coverage) "
        "instead of keyword matching."
    ),
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
@click.option(
    "--keep-cache/--delete-cache",
    default=False,
    show_default=True,
    help="Keep the intermediate embeddings.json cache after indexing.",
)
def build(
    repo: str,
    sqlite: str,
    lancedb: str,
    vector_backend: str | None,
    vectors_path: str | None,
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
    topics_prefix: tuple[str, ...],
    chunk_strategy: str,
    kmeans_model: str | None,
    no_similar: bool,
    similar_k: int,
    similar_threshold: float,
    update: bool,
    ext: tuple[str, ...],
    exclude_dir: tuple[str, ...],
    keep_cache: bool,
) -> None:
    """Build the DocKG from a corpus directory.

    Parses all .md and .txt files under CORPUS_ROOT, builds the structural
    and semantic graph, persists it to SQLite, and indexes it in the vector
    store (sqlite-vec by default; see --vector-backend).  Also discovers
    SIMILAR_TO edges between semantically related chunks.
    """
    repo_root = Path(repo).resolve()
    db_path = Path(sqlite) if sqlite else repo_root / ".dockg" / "graph.sqlite"
    lancedb_dir = Path(lancedb) if lancedb else repo_root / ".dockg" / "lancedb"
    wipe = not update
    extensions = set(e if e.startswith(".") else f".{e}" for e in ext)
    exclude = load_exclude_dirs(repo_root) | set(exclude_dir)
    topics_file_map = _parse_topics_prefix(topics_prefix)

    kg = DocKG(
        corpus_root=repo_root,
        exclude=exclude or None,
        db_path=db_path,
        lancedb_dir=lancedb_dir,
        model=model,
        table=table,
        vector_backend=vector_backend,
        vectors_path=vectors_path,
        chunk_strategy=chunk_strategy,
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
        topics_file_map=topics_file_map or None,
        kmeans_model_path=kmeans_model,
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
    _console.print(f"  vector index : {kg.vector_store_path}")
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

    # Step 2a: SQLite → JSON embedding cache (embedding only, no vector-store writes)
    cache_path = kg.db_path.parent / "embeddings.json"
    _console.print("\n[bold][2/3][/bold] Embedding nodes \u2192 JSON cache \u2026")
    kg.build_embeddings(out=cache_path, quiet=False)

    # Step 2b: JSON cache → vector index + SIMILAR_TO (no embedder in memory)
    _console.print("\n[bold][3/3][/bold] JSON cache \u2192 vector index \u2026")
    idx_stats = kg.build_index_from_cache(
        cache_path=cache_path,
        wipe=wipe,
        discover_similar=not no_similar,
        similar_k=similar_k,
        similarity_edge_threshold=similar_threshold,
    )
    _console.print(f"  model    : {kg.model_name}  dim={idx_stats.index_dim}")
    _console.print(f"  indexed  : {idx_stats.indexed_rows} vectors")
    if not no_similar:
        _console.print(f"  SIMILAR_TO: {idx_stats.similar_edges_added or 0} edges")

    # The cache is an intermediate artifact — the vectors now live in the index.
    if not keep_cache:
        try:
            cache_path.unlink(missing_ok=True)
            _console.print(f"  cache    : deleted {cache_path}")
        except OSError as exc:
            _console.print(f"  cache    : failed to delete {cache_path} ({exc})")

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
    "--topics-prefix",
    multiple=True,
    metavar="PREFIX=FILE",
    help=(
        "Per-path topic catalog override (repeatable). "
        "Format: PREFIX=PATH_TO_YAML, e.g. "
        "'sacred-texts/=/path/to/sacred_texts_topics.yaml'. "
        "First matching prefix wins; overrides --topics-file for matched files."
    ),
)
@click.option(
    "--chunk-strategy",
    type=click.Choice(["semantic", "sentence_group", "fixed", "verse"]),
    default="semantic",
    show_default=True,
    help=(
        "Chunking strategy. 'semantic' (default) auto-detects verse documents "
        "and switches to the verse chunker automatically. "
        "Use 'verse' to force verse mode for all files."
    ),
)
@click.option(
    "--kmeans-model",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help=(
        "Path to a *.kmeans.joblib model produced by 'dockg pipeline discover-topics'. "
        "Enables embedding-based K-means topic assignment (near-100% coverage) "
        "instead of keyword matching."
    ),
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
    topics_prefix: tuple[str, ...],
    chunk_strategy: str,
    kmeans_model: str | None,
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
    topics_file_map = _parse_topics_prefix(topics_prefix)

    kg = DocKG(
        corpus_root=repo_root,
        db_path=db_path,
        exclude=exclude or None,
        model=model,
        chunk_strategy=chunk_strategy,
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
        topics_file_map=topics_file_map or None,
        kmeans_model_path=kmeans_model,
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
    help="LanceDB table name (legacy backend only; ignored by sqlite-vec).",
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
    default=8192,
    show_default=True,
    help="Vector-store write batch size (rows per insert).",
)
@click.option(
    "--encode-batch",
    type=int,
    default=128,
    show_default=True,
    help="Encode page/batch size; the encode call is hard-capped at 128 (memory scales batch x seq^2, throughput flat above ~128).",
)
@click.option(
    "--device",
    type=click.Choice(["auto", "cpu", "mps", "cuda"]),
    default="auto",
    show_default=True,
    help="Embedding device override.",
)
@click.option(
    "--index-kind",
    "index_kinds",
    multiple=True,
    type=click.Choice(_INDEX_KIND_CHOICES),
    help=("Restrict embedded node kinds (repeatable). If omitted, embeds all default kinds."),
)
@vectors_path_option
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
    device: str,
    index_kinds: tuple[str, ...],
    vectors_path: str | None,
) -> None:
    """Build only the semantic vector index from an existing SQLite graph."""
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
        device=device,
        vectors_path=vectors_path,
    )

    if index_kinds:
        kg.index.index_kinds = tuple(index_kinds)

    _console.print(Rule(f"DocKG build-index — {db_path.name}", style="bold blue"))
    _console.print(f"  graph store  : {db_path}")
    _console.print(f"  vector index : {kg.vector_store_path}")
    if kg.resolved_vector_backend == "lancedb":
        _console.print(f"  table        : {table}")
    if index_kinds:
        _console.print(f"  kinds        : {', '.join(index_kinds)}")

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


@cli.command("build-embeddings")
@repo_option
@sqlite_option
@model_option
@click.option(
    "--out",
    type=click.Path(dir_okay=False),
    default=None,
    help=(
        "Output path for embedding cache. Supported: .json, .json.gz, .jsonl, .jsonl.gz "
        "(default: <sqlite_dir>/embeddings.json)."
    ),
)
@click.option(
    "--workers",
    type=int,
    default=None,
    help="Worker processes for embedding (default: CPU count / 2).",
)
@click.option(
    "--embed-batch",
    type=int,
    default=64,
    show_default=True,
    help="Per-worker embedding batch size for cache generation.",
)
@click.option(
    "--device",
    type=click.Choice(["auto", "cpu", "mps", "cuda"]),
    default="auto",
    show_default=True,
    help="Embedding device override.",
)
@click.option(
    "--index-kind",
    "index_kinds",
    multiple=True,
    type=click.Choice(_INDEX_KIND_CHOICES),
    help="Restrict embedded node kinds (repeatable).",
)
def build_embeddings(
    repo: str,
    sqlite: str,
    model: str,
    out: str | None,
    workers: int | None,
    embed_batch: int,
    device: str,
    index_kinds: tuple[str, ...],
) -> None:
    """Build only the embedding cache JSON from an existing SQLite graph."""
    repo_root = Path(repo).resolve()
    db_path = Path(sqlite) if sqlite else repo_root / ".dockg" / "graph.sqlite"
    kg = DocKG(
        corpus_root=repo_root,
        db_path=db_path,
        model=model,
        device=device,
    )

    if index_kinds:
        kg.index.index_kinds = tuple(index_kinds)

    _console.print(Rule(f"DocKG build-embeddings — {db_path.name}", style="bold blue"))
    _console.print(f"  graph store  : {db_path}")
    if index_kinds:
        _console.print(f"  kinds        : {', '.join(index_kinds)}")

    cache_path = kg.build_embeddings(
        out=Path(out) if out else None,
        n_workers=workers,
        batch_size=embed_batch,
        quiet=False,
    )
    _console.print(f"\n[green]Embeddings cache complete:[/green] {cache_path}")
    kg.close()


@cli.command("build-index-from-cache")
@repo_option
@sqlite_option
@lancedb_option
@model_option
@click.option(
    "--table",
    default="dockg_nodes",
    show_default=True,
    help="LanceDB table name (legacy backend only; ignored by sqlite-vec).",
)
@click.option(
    "--cache",
    "cache_path",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help=(
        "Path to embedding cache (.json/.json.gz/.jsonl/.jsonl.gz) "
        "(default: <sqlite_dir>/embeddings.json)."
    ),
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
@vectors_path_option
def build_index_from_cache(
    repo: str,
    sqlite: str,
    lancedb: str,
    model: str,
    table: str,
    cache_path: str | None,
    update: bool,
    no_similar: bool,
    vectors_path: str | None,
) -> None:
    """Build the vector index from an embedding cache JSON (no model inference)."""
    repo_root = Path(repo).resolve()
    db_path = Path(sqlite) if sqlite else repo_root / ".dockg" / "graph.sqlite"
    lancedb_dir = Path(lancedb) if lancedb else repo_root / ".dockg" / "lancedb"
    cache = Path(cache_path) if cache_path else db_path.parent / "embeddings.json"
    wipe = not update

    kg = DocKG(
        corpus_root=repo_root,
        db_path=db_path,
        lancedb_dir=lancedb_dir,
        model=model,
        table=table,
        vectors_path=vectors_path,
    )

    _console.print(Rule(f"DocKG build-index-from-cache — {db_path.name}", style="bold blue"))
    _console.print(f"  graph store  : {db_path}")
    _console.print(f"  vector index : {kg.vector_store_path}")
    if kg.resolved_vector_backend == "lancedb":
        _console.print(f"  table        : {table}")
    _console.print(f"  cache        : {cache}")

    stats = kg.build_index_from_cache(
        cache,
        wipe=wipe,
        discover_similar=not no_similar,
    )
    _console.print(f"  indexed  : {stats.indexed_rows} vectors")
    _console.print(f"  model    : {kg.model_name}  dim={stats.index_dim}")
    if not no_similar:
        _console.print(f"  SIMILAR_TO: {stats.similar_edges_added or 0} edges")
    _console.print("\n[green]Build complete.[/green]")
    kg.close()


@cli.command("build-two-phase")
@repo_option
@sqlite_option
@lancedb_option
@model_option
@click.option(
    "--table",
    default="dockg_nodes",
    show_default=True,
    help="LanceDB table name (legacy backend only; ignored by sqlite-vec).",
)
@click.option(
    "--cache",
    "cache_path",
    type=click.Path(dir_okay=False),
    default=None,
    help=(
        "Embedding cache path. Supported: .json, .json.gz, .jsonl, .jsonl.gz "
        "(default: <sqlite_dir>/embeddings.jsonl)."
    ),
)
@click.option(
    "--workers",
    type=int,
    default=None,
    help="Worker processes for embedding (default: CPU count / 2).",
)
@click.option(
    "--embed-batch",
    type=int,
    default=64,
    show_default=True,
    help="Per-worker embedding batch size for cache generation.",
)
@click.option(
    "--device",
    type=click.Choice(["auto", "cpu", "mps", "cuda"]),
    default="auto",
    show_default=True,
    help="Embedding device override.",
)
@click.option(
    "--index-kind",
    "index_kinds",
    multiple=True,
    type=click.Choice(_INDEX_KIND_CHOICES),
    help="Restrict embedded node kinds (repeatable).",
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
    "--keep-cache/--delete-cache",
    default=True,
    show_default=True,
    help="Keep or delete embedding cache after successful indexing.",
)
@vectors_path_option
def build_two_phase(
    repo: str,
    sqlite: str,
    lancedb: str,
    model: str,
    table: str,
    cache_path: str | None,
    workers: int | None,
    embed_batch: int,
    device: str,
    index_kinds: tuple[str, ...],
    update: bool,
    no_similar: bool,
    keep_cache: bool,
    vectors_path: str | None,
) -> None:
    """Run the stable two-phase pipeline: cache embeddings, then index from cache."""
    repo_root = Path(repo).resolve()
    db_path = Path(sqlite) if sqlite else repo_root / ".dockg" / "graph.sqlite"
    lancedb_dir = Path(lancedb) if lancedb else repo_root / ".dockg" / "lancedb"
    cache = Path(cache_path) if cache_path else db_path.parent / "embeddings.jsonl"
    wipe = not update

    kg = DocKG(
        corpus_root=repo_root,
        db_path=db_path,
        lancedb_dir=lancedb_dir,
        model=model,
        table=table,
        device=device,
        vectors_path=vectors_path,
    )

    if index_kinds:
        kg.index.index_kinds = tuple(index_kinds)

    _console.print(Rule(f"DocKG build-two-phase — {db_path.name}", style="bold blue"))
    _console.print(f"  graph store  : {db_path}")
    _console.print(f"  vector index : {kg.vector_store_path}")
    if kg.resolved_vector_backend == "lancedb":
        _console.print(f"  table        : {table}")
    _console.print(f"  cache        : {cache}")
    if index_kinds:
        _console.print(f"  kinds        : {', '.join(index_kinds)}")

    _console.print("\n[bold][1/2][/bold] Embedding nodes → cache …")
    cache_out = kg.build_embeddings(
        out=cache,
        n_workers=workers,
        batch_size=embed_batch,
        quiet=False,
    )
    _console.print(f"  cache    : {cache_out}")

    _console.print("\n[bold][2/2][/bold] Cache → vector index …")
    stats = kg.build_index_from_cache(
        cache_out,
        wipe=wipe,
        discover_similar=not no_similar,
    )
    _console.print(f"  indexed  : {stats.indexed_rows} vectors")
    _console.print(f"  model    : {kg.model_name}  dim={stats.index_dim}")
    if not no_similar:
        _console.print(f"  SIMILAR_TO: {stats.similar_edges_added or 0} edges")

    if not keep_cache:
        try:
            cache_out.unlink(missing_ok=True)
            _console.print(f"  cache    : deleted {cache_out}")
        except OSError as exc:
            _console.print(f"  cache    : failed to delete {cache_out} ({exc})")

    _console.print("\n[green]Build complete.[/green]")
    kg.close()


@cli.command("reindex-fts")
@repo_option
@sqlite_option
def reindex_fts(repo: str, sqlite: str) -> None:
    """Backfill the FTS5 lexical (BM25) index on an existing graph.

    Rebuilds ``nodes_fts`` from chunk text already in SQLite — no re-embedding,
    no vector-store changes.  Use this to add hybrid lexical retrieval to corpora
    built before the lexical index existed.
    """
    from doc_kg.store import GraphStore  # pylint: disable=import-outside-toplevel

    repo_root = Path(repo).resolve()
    db_path = Path(sqlite) if sqlite else repo_root / ".dockg" / "graph.sqlite"
    if not db_path.exists():
        raise click.ClickException(f"No graph store at {db_path}")

    _console.print(Rule(f"DocKG reindex-fts — {repo_root.name}", style="bold blue"))
    _console.print(f"  graph store : {db_path}")
    store = GraphStore(db_path)
    n = store.rebuild_fts()
    store.close()
    if n:
        _console.print("\n[green]Lexical index ready.[/green]")
    else:
        _console.print("\n[yellow]No lexical index built (FTS5 unavailable or no chunks).[/yellow]")


@cli.command("convert-index")
@repo_option
@lancedb_option
@click.option(
    "--table", default="dockg_nodes", show_default=True, help="Source LanceDB table name."
)
@click.option(
    "--to",
    "to_backend",
    type=click.Choice(["sqlite-vec"]),
    default="sqlite-vec",
    show_default=True,
    help="Target backend.",
)
@click.option(
    "--dtype",
    type=click.Choice(["fp32", "int8"]),
    default="fp32",
    show_default=True,
    help="fp32 (exact) or int8 (3x smaller; assumes unit-norm vectors).",
)
@click.option(
    "--vectors-path",
    default=None,
    type=click.Path(),
    help="Destination sqlite path (default: <repo>/.dockg/vectors.sqlite).",
)
@click.option("--wipe/--no-wipe", default=True, show_default=True, help="Overwrite destination.")
@click.option(
    "--delete-lancedb",
    is_flag=True,
    default=False,
    help="After a VALIDATED conversion, delete the source LanceDB directory "
    "to reclaim space. No-op if validation fails.",
)
def convert_index(
    repo: str,
    lancedb: str,
    table: str,
    to_backend: str,
    dtype: str,
    vectors_path: str | None,
    wipe: bool,
    delete_lancedb: bool,
) -> None:
    """Convert an existing LanceDB vector index to a sqlite-vec store.

    Reads vectors straight out of LanceDB and writes ``vectors.sqlite`` — no
    model load, no re-embedding. Validates row count and re-reads a sample of
    vectors to confirm the conversion is lossless (fp32) / near-lossless (int8).
    With ``--delete-lancedb`` the source LanceDB dir is removed *only after*
    validation succeeds.
    """
    import shutil  # pylint: disable=import-outside-toplevel

    from doc_kg.index import convert_lancedb_to_sqlite  # pylint: disable=import-outside-toplevel

    repo_root = Path(repo).resolve()
    lancedb_dir = Path(lancedb) if lancedb else repo_root / ".dockg" / "lancedb"

    _console.print(Rule(f"DocKG convert-index — {repo_root.name}", style="bold blue"))
    _console.print(f"  source lancedb : {lancedb_dir}")
    _console.print(f"  target backend : {to_backend} (dtype={dtype})")

    stats = convert_lancedb_to_sqlite(
        lancedb_dir,
        table=table,
        vectors_path=vectors_path,
        dtype="int8" if dtype == "int8" else "float",
        wipe=wipe,
    )
    if not stats["validated"]:
        raise click.ClickException("conversion validation failed")
    _console.print("\n[green]Conversion complete and validated.[/green]")

    if delete_lancedb:
        # Guarded: only reached after validation passed above.
        if lancedb_dir.exists():
            shutil.rmtree(lancedb_dir)
            _console.print(f"[yellow]Deleted source LanceDB dir:[/yellow] {lancedb_dir}")
