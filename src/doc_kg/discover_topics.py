#!/usr/bin/env python3
"""
discover_topics.py

Corpus-driven topic discovery for DocKG.

Chunks a corpus, embeds each chunk, clusters via K-means, then extracts the
top TF-IDF discriminative terms per cluster to produce a topics catalog YAML
that can be passed directly to ``build-graph --topics-file``.

Typical workflow::

    # 1. Discover topics from the corpus
    from doc_kg.discover_topics import discover_topics
    catalog_path = discover_topics(
        corpus_root="/path/to/corpus",
        output_path="/path/to/corpus/discovered_topics.yaml",
        n_clusters=16,
        n_keywords=12,
    )

    # 2. Review/rename clusters in the YAML, then build:
    #    dockg build-graph --repo /path/to/corpus \\
    #        --topics-file /path/to/corpus/discovered_topics.yaml

Author: Eric G. Suchanek, PhD
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_TFIDF_STOPWORDS = {
    # KJV-specific high-frequency words that don't discriminate topics
    "shall",
    "unto",
    "thee",
    "thou",
    "thy",
    "hath",
    "doth",
    "saith",
    "said",
    "lord",
    "god",
    "king",
    "israel",
    "children",
    "came",
    "went",
    "come",
    "also",
    "upon",
    "them",
    "their",
    "they",
    "have",
    "been",
    "which",
    "that",
    "this",
    "from",
    "with",
    "were",
    "there",
    "then",
    "when",
    "will",
    "made",
    "make",
    "give",
    "take",
    "according",
    "like",
    "even",
    "all",
    "not",
    "but",
    "and",
    "for",
    "the",
    "of",
    "in",
    "to",
    "a",
    "an",
    "be",
    "by",
    "he",
    "his",
    "him",
    "her",
    "she",
    "we",
    "our",
    "us",
    "me",
    "my",
    "it",
    "its",
    "who",
    "what",
    "how",
}


def discover_topics(
    corpus_root: str | Path,
    *,
    output_path: str | Path | None = None,
    n_clusters: int = 16,
    n_keywords: int = 15,
    chunk_strategy: str = "auto",
    sentences_per_chunk: int = 5,
    model: str = "BAAI/bge-small-en-v1.5",
    min_cluster_size: int = 3,
    quiet: bool = False,
) -> tuple[Path, Path]:
    """Discover topics from a corpus using K-means on embeddings.

    Steps:

    1. Walk the corpus and chunk every document (auto-detects verse files).
    2. Embed all chunks with *model*.
    3. Fit K-means with *n_clusters* clusters on the embedding matrix.
    4. For each cluster: compute within-cluster term frequency (coverage-first),
       take the top *n_keywords* characteristic terms.
    5. Write a YAML catalog (``{cluster_label: [kw, ...]}``) to *output_path*.
    6. Save the fitted K-means model alongside the YAML as ``<stem>.kmeans.joblib``
       so ``build-graph --kmeans-model`` can use embedding-based assignment
       (near-100% coverage, no keyword matching needed).

    :param corpus_root: Root of the corpus to analyse.
    :param output_path: Where to write the YAML catalog.  Defaults to
                        ``<corpus_root>/discovered_topics.yaml``.
    :param n_clusters: Number of K-means clusters (= number of topics).
    :param n_keywords: Top characteristic terms to keep per cluster (for the
                       human-readable YAML; not used when --kmeans-model is set).
    :param chunk_strategy: ``"auto"`` detects verse documents automatically;
                           ``"verse"`` forces verse mode;
                           ``"sentence_group"`` uses sentence groups.
    :param sentences_per_chunk: Verses (or sentences) per chunk.
    :param model: Sentence-transformer model name for embedding.
    :param min_cluster_size: Clusters smaller than this are flagged as sparse.
    :param quiet: Suppress Rich console output.
    :return: ``(yaml_path, kmeans_model_path)`` tuple.
    """
    try:
        import numpy as np  # pylint: disable=import-outside-toplevel
        from sklearn.cluster import KMeans  # pylint: disable=import-outside-toplevel
    except ImportError as exc:
        raise ImportError(
            "discover_topics requires scikit-learn. Install with: pip install scikit-learn"
        ) from exc

    try:
        import yaml  # type: ignore[import-untyped]  # pylint: disable=import-outside-toplevel
    except ImportError as exc:
        raise ImportError(
            "discover_topics requires PyYAML. Install with: pip install pyyaml"
        ) from exc

    corpus_root = Path(corpus_root).resolve()
    if output_path is None:
        output_path = corpus_root / "discovered_topics.yaml"
    output_path = Path(output_path)

    if not quiet:
        from rich.console import Console  # pylint: disable=import-outside-toplevel
        from rich.rule import Rule  # pylint: disable=import-outside-toplevel

        console = Console()
        console.print(Rule("DocKG — discover-topics", style="bold cyan"))
        console.print(f"  corpus    : {corpus_root}")
        console.print(f"  clusters  : {n_clusters}")
        console.print(f"  keywords  : {n_keywords}")
        console.print(f"  model     : {model}")
    else:
        console = None  # type: ignore[assignment]

    # ------------------------------------------------------------------
    # Step 1: Chunk corpus
    # ------------------------------------------------------------------
    from doc_kg.chunker import (  # pylint: disable=import-outside-toplevel
        SentenceGroupChunker,
        TextChunker,
        VerseChunker,
        chunker_for,
    )
    from doc_kg.dockg import iter_text_files  # pylint: disable=import-outside-toplevel

    files = list(iter_text_files(corpus_root))
    if not files:
        raise ValueError(f"No text files found under {corpus_root}")

    if not quiet and console:
        console.print(f"\n[bold][1/4][/bold] Chunking {len(files)} file(s)…")

    all_chunks: list[dict] = []
    for abs_path in files:
        try:
            raw_text = abs_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        ck: TextChunker | SentenceGroupChunker | VerseChunker
        if chunk_strategy == "auto" and VerseChunker.is_verse_document(raw_text):
            ck = VerseChunker(verses_per_chunk=sentences_per_chunk)
        elif chunk_strategy == "verse":
            ck = VerseChunker(verses_per_chunk=sentences_per_chunk)
        else:
            ck = chunker_for("sentence_group", sentences_per_chunk=sentences_per_chunk)

        rel = str(abs_path.relative_to(corpus_root))
        chunks = ck.chunk(raw_text, file_path=rel)
        for c in chunks:
            c["_file"] = rel
        all_chunks.extend(chunks)

    if not all_chunks:
        raise ValueError("No chunks produced — check corpus content.")

    if not quiet and console:
        console.print(f"  produced  : {len(all_chunks):,} chunks")

    chunk_texts = [c["text"] for c in all_chunks]

    # ------------------------------------------------------------------
    # Step 2: Embed
    # ------------------------------------------------------------------
    if not quiet and console:
        console.print(f"\n[bold][2/4][/bold] Embedding {len(chunk_texts):,} chunks…")

    from kg_utils.embedder import (  # pylint: disable=import-outside-toplevel
        SentenceTransformerEmbedder,
    )

    embedder = SentenceTransformerEmbedder(model)
    embeddings = np.array(embedder.embed_texts(chunk_texts), dtype="float32")

    if not quiet and console:
        console.print(f"  shape     : {embeddings.shape}")

    # ------------------------------------------------------------------
    # Step 3: K-means clustering
    # ------------------------------------------------------------------
    if not quiet and console:
        console.print(f"\n[bold][3/4][/bold] Fitting K-means (k={n_clusters})…")

    effective_k = min(n_clusters, len(chunk_texts))
    kmeans = KMeans(n_clusters=effective_k, random_state=42, n_init="auto")
    labels = kmeans.fit_predict(embeddings)

    cluster_sizes = {i: int((labels == i).sum()) for i in range(effective_k)}

    # ------------------------------------------------------------------
    # Step 4: Extract per-cluster keywords for maximum coverage
    #
    # Strategy: for each cluster, compute BOTH
    #   (a) within-cluster term frequency  — high recall (terms that actually
    #       appear in most members of the cluster)
    #   (b) within/corpus frequency ratio  — modest discrimination (prefer
    #       terms that appear relatively more inside than outside)
    #
    # We rank by a blend: 0.7 * normalised_within_freq + 0.3 * ratio_score.
    # This gives us coverage-first keywords rather than discrimination-first
    # keywords (which TF-IDF alone provides).
    # ------------------------------------------------------------------
    if not quiet and console:
        console.print("\n[bold][4/4][/bold] Extracting top keywords per cluster…")

    # Tokenise all chunks once; store per-cluster token lists
    tok_re = re.compile(r"[a-z][a-z']{2,30}")

    cluster_token_lists: list[list[str]] = [[] for _ in range(effective_k)]
    all_tokens: list[str] = []
    for i, text in enumerate(chunk_texts):
        tokens = tok_re.findall(text.lower())
        clean = [t for t in tokens if t not in _TFIDF_STOPWORDS]
        cluster_token_lists[labels[i]].extend(clean)
        all_tokens.extend(clean)

    # Corpus-wide counts
    corpus_counts = Counter(all_tokens)
    corpus_total = max(1, len(all_tokens))

    topic_map: dict[str, list[str]] = {}
    cluster_summaries: list[tuple[str, int, list[str]]] = []

    for cluster_id in range(effective_k):
        label = f"cluster_{cluster_id:02d}"
        tokens = cluster_token_lists[cluster_id]
        if not tokens:
            topic_map[label] = []
            cluster_summaries.append((label, cluster_sizes[cluster_id], []))
            continue

        within_counts = Counter(tokens)
        within_total = max(1, len(tokens))

        # Score each term that appears at least twice in this cluster
        scored: list[tuple[float, str]] = []
        for term, within_cnt in within_counts.items():
            if within_cnt < 2 or len(term) < 3:
                continue
            within_freq = within_cnt / within_total
            corpus_freq = corpus_counts[term] / corpus_total
            # Lift: how much more common inside vs corpus
            lift = within_freq / max(corpus_freq, 1e-9)
            # Blend: coverage-first (within_freq) + modest discrimination (lift)
            score = 0.7 * within_freq + 0.3 * min(lift / 10.0, 1.0)
            scored.append((score, term))

        scored.sort(reverse=True)
        keywords = [term for _, term in scored[:n_keywords]]

        topic_map[label] = keywords
        cluster_summaries.append((label, cluster_sizes[cluster_id], keywords[:6]))

    # ------------------------------------------------------------------
    # Write YAML catalog
    # ------------------------------------------------------------------
    output_path.parent.mkdir(parents=True, exist_ok=True)

    catalog_header = (
        f"# Corpus-derived topic catalog\n"
        f"# Source : {corpus_root}\n"
        f"# Clusters: {effective_k}  Keywords per cluster: {n_keywords}\n"
        f"# Model  : {model}\n"
        f"#\n"
        f"# Review and rename cluster_NN labels before using as --topics-file.\n"
        f"# Merge similar clusters, delete noise clusters, add KJV phrases as needed.\n\n"
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(catalog_header)
        yaml.dump(topic_map, f, allow_unicode=True, default_flow_style=False, sort_keys=True)

    # ------------------------------------------------------------------
    # Save K-means model for embedding-based assignment during build-graph
    # ------------------------------------------------------------------
    try:
        import joblib  # pylint: disable=import-outside-toplevel
    except ImportError as exc:
        raise ImportError(
            "discover_topics requires joblib. Install with: pip install joblib"
        ) from exc

    kmeans_path = output_path.with_suffix("").with_suffix(".kmeans.joblib")
    # Store model + cluster label map together so build-graph has everything it needs
    joblib.dump(
        {
            "kmeans": kmeans,
            "labels": [f"cluster_{i:02d}" for i in range(effective_k)],
            "model_name": model,
            "n_clusters": effective_k,
        },
        kmeans_path,
    )

    # ------------------------------------------------------------------
    # Console summary table
    # ------------------------------------------------------------------
    if not quiet and console:
        from rich.table import Table  # pylint: disable=import-outside-toplevel

        console.print(f"\n[green]Catalog written to:[/green]    {output_path}")
        console.print(f"[green]K-means model saved to:[/green] {kmeans_path}\n")

        table = Table(title="Discovered Topic Clusters", show_lines=True)
        table.add_column("Cluster", style="cyan", no_wrap=True)
        table.add_column("Chunks", justify="right")
        table.add_column("Top keywords", style="dim")

        for label, size, preview_kws in sorted(cluster_summaries, key=lambda x: -x[1]):
            sparse_flag = " [yellow]⚠ sparse[/yellow]" if size < min_cluster_size else ""
            table.add_row(label, str(size), ", ".join(preview_kws) + sparse_flag)

        console.print(table)
        console.print(
            f"\n[dim]Use the model for embedding-based (near-100%) coverage:[/dim]\n"
            f"  dockg build-graph --kmeans-model {kmeans_path} --chunk-strategy verse …\n"
            f"\n[dim]Or rename cluster labels in {output_path.name} and use keyword matching:[/dim]\n"
            f"  dockg build-graph --topics-file {output_path} --chunk-strategy verse …\n"
        )

    return output_path, kmeans_path
