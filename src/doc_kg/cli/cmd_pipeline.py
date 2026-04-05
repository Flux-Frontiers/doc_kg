"""
cmd_pipeline.py

CLI commands for the multipass analysis pipeline.

Commands:
    dockg pipeline run       — Run the 5-phase analysis pipeline
    dockg pipeline embed     — Multi-process corpus embedding
    dockg pipeline manifold  — Manifold & MRL analysis on embeddings

Author: Eric G. Suchanek, PhD
"""

from __future__ import annotations

from pathlib import Path

import click

from doc_kg.cli.group import cli
from doc_kg.cli.options import model_option, repo_option


@cli.group()
def pipeline() -> None:
    """Multipass analysis pipeline (sampling, chunking, classification, embedding, manifold)."""


# ============================================================================
# pipeline run
# ============================================================================


@pipeline.command("run")
@repo_option
@click.option(
    "--strategy",
    type=click.Choice(["sentence_group", "semantic"]),
    default="sentence_group",
    show_default=True,
    help="Chunking strategy.",
)
@click.option(
    "--sentences",
    default=4,
    show_default=True,
    help="Sentences per chunk (sentence_group strategy).",
)
@click.option(
    "--batch",
    default=20,
    show_default=True,
    help="Number of documents to sample per run.",
)
@click.option(
    "--sampling",
    type=click.Choice(["diversity", "random", "temporal"]),
    default="diversity",
    show_default=True,
    help="Sampling strategy for Phase 1.",
)
@click.option(
    "--n-clusters",
    default=8,
    show_default=True,
    help="K-means clusters for diversity sampling.",
)
@click.option(
    "--supervised-threshold",
    default=0.3,
    show_default=True,
    help="Min confidence for supervised topic classification.",
)
@click.option(
    "--topics-file",
    default=None,
    type=click.Path(exists=True),
    help="Custom topic catalog (YAML/JSON).",
)
@click.option(
    "--max-chunks",
    default=0,
    show_default=True,
    help="Max chunks per document (0 = unlimited).",
)
@click.option(
    "--seed",
    default=42,
    show_default=True,
    help="Random seed for reproducibility.",
)
@click.option(
    "--output",
    default=None,
    type=click.Path(),
    help="Output directory (default: <repo>/.dockg/pipeline).",
)
@model_option
@click.option("--quiet", is_flag=True, help="Suppress progress output.")
def pipeline_run(
    repo: str,
    strategy: str,
    sentences: int,
    batch: int,
    sampling: str,
    n_clusters: int,
    supervised_threshold: float,
    topics_file: str | None,
    max_chunks: int,
    seed: int,
    output: str | None,
    model: str,
    quiet: bool,
) -> None:
    """Run the 5-phase multipass analysis pipeline.

    Phase 1: Diversity Sampling — extract features, cluster, sample
    Phase 2: Chunking — sentence-group or semantic
    Phase 3: Topic Classification — supervised + unsupervised hybrid
    Phase 4: Memory Creation — EntryChunk assembly with provenance
    Phase 5: Structured Output — pipe-delimited with run parameters
    """
    import logging  # pylint: disable=import-outside-toplevel

    from rich.console import Console  # pylint: disable=import-outside-toplevel

    from doc_kg.pipeline import (  # pylint: disable=import-outside-toplevel
        AnalysisPipeline,
        PipelineConfig,
    )

    console = Console()

    if not quiet:
        logging.basicConfig(level=logging.INFO, format="%(message)s")

    config = PipelineConfig(
        corpus_root=Path(repo),
        chunk_strategy=strategy,
        sentences_per_chunk=sentences,
        n_diversity_clusters=n_clusters,
        batch_size=batch,
        supervised_threshold=supervised_threshold,
        n_topic_clusters=n_clusters,
        topics_file=topics_file,
        output_dir=Path(output) if output else None,
        embedding_model=model,
        seed=seed,
        max_chunks_per_doc=max_chunks,
    )

    pipe = AnalysisPipeline(config)

    if not quiet:
        console.print("\n[bold]DocKG Multipass Pipeline[/bold]")
        console.print(f"  Corpus: {repo}")
        console.print(f"  Strategy: {strategy}")
        console.print(f"  Batch: {batch} docs")
        console.print()

    result = pipe.run()

    if not quiet:
        console.print("\n[bold green]Pipeline complete[/bold green]")
        console.print(f"  Run ID:    {result.run_id}")
        console.print(f"  Files:     {result.stats.get('sampled_files', 0)} / "
                       f"{result.stats.get('total_files', 0)}")
        console.print(f"  Chunks:    {result.stats.get('total_chunks', 0)}")
        methods = result.stats.get("classification_methods", {})
        console.print(f"  Topics:    supervised={methods.get('supervised', 0)}, "
                       f"unsupervised={methods.get('unsupervised', 0)}, "
                       f"fallback={methods.get('fallback', 0)}")
        console.print(f"  Time:      {result.elapsed_seconds:.1f}s")
        if result.output_path:
            console.print(f"  Output:    {result.output_path}")


# ============================================================================
# pipeline embed
# ============================================================================


@pipeline.command("embed")
@repo_option
@model_option
@click.option("--workers", default=None, type=int, help="Number of parallel workers.")
@click.option("--batch-size", default=64, show_default=True, help="Per-worker batch size.")
@click.option("--sample-n", default=None, type=int, help="Evenly sample N texts before embedding.")
@click.option(
    "--cache",
    default=None,
    type=click.Path(),
    help="Output cache path (default: <repo>/.dockg/pipeline/embeddings.json).",
)
@click.option("--force", is_flag=True, help="Overwrite existing cache.")
def pipeline_embed(
    repo: str,
    model: str,
    workers: int | None,
    batch_size: int,
    sample_n: int | None,
    cache: str | None,
    force: bool,
) -> None:
    """Multi-process corpus embedding (Stage 3).

    Embeds all corpus text chunks using parallel workers and writes a JSON
    cache consumable by the manifold analyzer.
    """
    from rich.console import Console  # pylint: disable=import-outside-toplevel

    from doc_kg.dockg import iter_text_files  # pylint: disable=import-outside-toplevel
    from doc_kg.embedder_worker import (  # pylint: disable=import-outside-toplevel
        CorpusEmbedder,
    )

    console = Console()
    corpus_root = Path(repo).resolve()

    cache_path = Path(cache) if cache else (corpus_root / ".dockg" / "pipeline" / "embeddings.json")

    if cache_path.exists() and not force:
        console.print(f"[yellow]Cache already exists: {cache_path}[/yellow]")
        console.print("Use --force to overwrite.")
        return

    # Collect texts from corpus
    files = iter_text_files(corpus_root)
    texts: list[str] = []
    metadata: list[dict] = []

    for fp in files:
        try:
            text = fp.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = str(fp.relative_to(corpus_root)).replace("\\", "/")
        texts.append(text[:2048])  # Cap per-doc text for embedding
        metadata.append({"file_path": rel})

    if not texts:
        console.print("[red]No text files found.[/red]")
        return

    console.print("\n[bold]Corpus Embedding[/bold]")
    console.print(f"  Model:   {model}")
    console.print(f"  Files:   {len(texts)}")
    if sample_n:
        console.print(f"  Sample:  {sample_n}")
    console.print()

    embedder = CorpusEmbedder(model, n_workers=workers, batch_size=batch_size)
    result = embedder.embed(texts, metadata, sample_n=sample_n)

    CorpusEmbedder.save_cache(result, cache_path)

    console.print("\n[bold green]Embedding complete[/bold green]")
    console.print(f"  Vectors: {result.n_vectors} x {result.dim}")
    console.print(f"  Cache:   {cache_path}")


# ============================================================================
# pipeline manifold
# ============================================================================


@pipeline.command("manifold")
@click.option(
    "--cache",
    default=None,
    type=click.Path(exists=True),
    help="Path to embedding cache JSON.",
)
@repo_option
@click.option("--max-pca", default=256, show_default=True, help="Max PCA components.")
@click.option(
    "--output",
    default=None,
    type=click.Path(),
    help="Output report path (default: stdout).",
)
def pipeline_manifold(
    cache: str | None,
    repo: str,
    max_pca: int,
    output: str | None,
) -> None:
    """Manifold & MRL analysis on corpus embeddings (Stage 4).

    Analyzes intrinsic dimensionality, PCA elbow, and MRL truncation quality.
    """
    from rich.console import Console  # pylint: disable=import-outside-toplevel

    from doc_kg.embedder_worker import (  # pylint: disable=import-outside-toplevel
        CorpusEmbedder,
    )
    from doc_kg.manifold import ManifoldAnalyzer  # pylint: disable=import-outside-toplevel

    console = Console()
    corpus_root = Path(repo).resolve()

    cache_path = Path(cache) if cache else (corpus_root / ".dockg" / "pipeline" / "embeddings.json")

    if not cache_path.exists():
        console.print(f"[red]No embedding cache found at: {cache_path}[/red]")
        console.print("Run 'dockg pipeline embed' first.")
        return

    console.print("\n[bold]Manifold Analysis[/bold]")
    console.print(f"  Cache: {cache_path}")

    emb_cache = CorpusEmbedder.load_cache(cache_path)
    console.print(f"  Vectors: {emb_cache.n_vectors} x {emb_cache.dim}")
    console.print()

    analyzer = ManifoldAnalyzer(pca_max_components=max_pca)
    report = analyzer.analyze(emb_cache.vectors)

    formatted = analyzer.format_report(report)

    if output:
        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(formatted, encoding="utf-8")
        console.print(f"\n[bold green]Report saved to {out_path}[/bold green]")
    else:
        console.print()
        console.print(formatted)
