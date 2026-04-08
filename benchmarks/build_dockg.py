#!/usr/bin/env python3
"""
build_dockg.py
==============

Standalone DocKG build pipeline for the LongMemEval corpus.

Writes every unique haystack session from the LongMemEval JSON to disk as
Markdown files, then builds a persistent DocKG consisting of a SQLite
structural graph and a LanceDB vector index with full relational structure:
document/section/chunk hierarchy, SIMILAR_TO edges (cosine ≥ 0.85),
HAS_TOPIC, MENTIONS_ENTITY, HAS_KEYWORD, and CO_OCCURS_WITH.

Two build modes are supported:

Standard (single-process)
    The default. Corpus parsing, embedding, and LanceDB ingestion run
    sequentially in a single process.  Suitable for small corpora or
    when worker processes are not available.

Two-phase (multi-worker)
    Activated by ``--workers N`` (N > 1) or ``--emb-cache``.  Separates
    the slow embedding pass from LanceDB ingestion:

        1. build_graph  — corpus parse → SQLite
                          (skipped if SQLite exists and --wipe not given)
        2. build_embeddings — spawn N worker processes, each loading its
                          own SentenceTransformer instance; saves an
                          EmbeddingCache JSON to disk
        3. build_index_from_cache — load vectors from cache → LanceDB
                          (always wipes LanceDB since embeddings are fresh)
                          + batched numpy SIMILAR_TO edge discovery

    The embedding cache persists on disk, so LanceDB can be rebuilt from
    the cache without re-running the model (e.g. after tuning thresholds).

Usage
-----

Download the dataset (one time, ~50 MB)::

    python benchmarks/build_dockg.py /tmp/longmemeval_s_cleaned.json --download

Standard build from scratch::

    python benchmarks/build_dockg.py /tmp/longmemeval_s_cleaned.json --wipe

Two-phase build with 10 workers::

    python benchmarks/build_dockg.py /tmp/longmemeval_s_cleaned.json --wipe --workers 10

Reuse existing graph, re-embed only (no corpus/graph rebuild)::

    python benchmarks/build_dockg.py /tmp/longmemeval_s_cleaned.json --workers 10

Rebuild LanceDB from an existing embedding cache (no re-embedding)::

    python benchmarks/build_dockg.py /tmp/longmemeval_s_cleaned.json \\
        --skip-corpus --emb-cache /tmp/.dockg/embeddings.json

Custom paths::

    python benchmarks/build_dockg.py /tmp/longmemeval_s_cleaned.json --wipe --workers 10 \\
        --corpus-dir /tmp/corpus \\
        --db /tmp/.dockg/graph.sqlite \\
        --lancedb /tmp/.dockg/lancedb \\
        --emb-cache /tmp/.dockg/embeddings.json

Author: Eric G. Suchanek, PhD
Last Revision: 2026-04-07
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Make `src/` importable when running from a source checkout
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

# ---------------------------------------------------------------------------
# Default paths
# ---------------------------------------------------------------------------

_DATA_DIR = REPO_ROOT / "benchmarks" / "data"
DEFAULT_CORPUS_DIR = _DATA_DIR / "longmemeval_corpus"
DEFAULT_DB = _DATA_DIR / ".dockg" / "graph.sqlite"
DEFAULT_LANCEDB = _DATA_DIR / ".dockg" / "lancedb"
DEFAULT_EMB_CACHE = _DATA_DIR / ".dockg" / "embeddings.json"

_LONGMEMEVAL_URL = (
    "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned"
    "/resolve/main/longmemeval_s_cleaned.json"
)


# ---------------------------------------------------------------------------
# Corpus writer
# ---------------------------------------------------------------------------


def _format_session_markdown(sess_id: str, date: str, turns: list[dict]) -> str:
    """Render a LongMemEval session as a Markdown document."""
    lines: list[str] = [
        f"# Session {sess_id}",
        "",
        f"**Date:** {date}",
        "",
    ]
    for turn in turns:
        role = turn.get("role", "user")
        content = (turn.get("content") or "").strip()
        if not content:
            continue
        lines.append(f"## {role.capitalize()}")
        lines.append("")
        lines.append(content)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_corpus(data_file: Path, corpus_dir: Path, *, force: bool = False) -> None:
    """Write every unique haystack session from *data_file* to *corpus_dir*.

    :param data_file: Path to the LongMemEval JSON file.
    :param corpus_dir: Output directory for Markdown session files.
    :param force: Overwrite existing files even if they already exist.
    """
    with open(data_file) as fh:
        data = json.load(fh)

    corpus_dir.mkdir(parents=True, exist_ok=True)
    existing = {p.stem for p in corpus_dir.glob("*.md")}

    written = 0
    skipped = 0

    for entry in data:
        for session, sess_id, date in zip(
            entry["haystack_sessions"],
            entry["haystack_session_ids"],
            entry["haystack_dates"],
        ):
            out_path = corpus_dir / f"{sess_id}.md"
            if not force and sess_id in existing:
                skipped += 1
                continue
            out_path.write_text(_format_session_markdown(sess_id, date, session))
            written += 1
            existing.add(sess_id)

    print(
        f"  Corpus: {written + skipped} unique sessions "
        f"({written} written, {skipped} reused) → {corpus_dir}"
    )


# ---------------------------------------------------------------------------
# KG builder
# ---------------------------------------------------------------------------


def build_kg(
    corpus_dir: Path,
    db_path: Path,
    lancedb_dir: Path,
    *,
    wipe: bool = False,
    model: str | None = None,
    workers: int | None = None,
    emb_cache: Path | None = None,
    similar: bool = True,
) -> None:
    """Build a persistent DocKG from *corpus_dir*.

    When *workers* > 1 or *emb_cache* is given, uses the two-phase build:

    1. ``build_graph`` — corpus parse → SQLite (skipped if SQLite exists and
       *wipe* is False)
    2. ``build_embeddings`` — multi-worker embedding → JSON cache file
    3. ``build_index_from_cache`` — load vectors → LanceDB + SIMILAR_TO edges

    Otherwise falls back to the standard single-process ``DocKG.build``.

    :param corpus_dir: Root directory of the Markdown corpus.
    :param db_path: Path for the SQLite graph database.
    :param lancedb_dir: Directory for the LanceDB vector index.
    :param wipe: Rebuild from scratch (clear existing data).
    :param model: Sentence-transformer model name override.
    :param workers: Worker processes for embedding (enables two-phase build).
    :param emb_cache: Path for the embedding cache JSON (two-phase build).
    """
    from doc_kg.kg import DEFAULT_MODEL, DocKG  # pylint: disable=import-outside-toplevel

    use_two_phase = (workers is not None and workers > 1) or emb_cache is not None
    cache_path = emb_cache or DEFAULT_EMB_CACHE

    print(f"  Mode:    {'two-phase' if use_two_phase else 'standard'} "
          f"({'wipe' if wipe else 'incremental'})")
    print(f"  Corpus:  {corpus_dir}")
    print(f"  SQLite:  {db_path}")
    print(f"  LanceDB: {lancedb_dir}")
    print(f"  Model:   {model or DEFAULT_MODEL}")
    if use_two_phase:
        print(f"  Workers: {workers or 'auto'}")
        print(f"  Cache:   {cache_path}")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    lancedb_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    kg = DocKG(
        corpus_root=corpus_dir,
        db_path=db_path,
        lancedb_dir=lancedb_dir,
        model=model or DEFAULT_MODEL,
    )
    try:
        if use_two_phase:
            # Skip graph rebuild if SQLite already exists and wipe not requested
            if wipe or not db_path.exists():
                graph_stats = kg.build_graph(wipe=wipe)
                print(
                    f"  Graph:   {graph_stats.total_nodes} nodes, "
                    f"{graph_stats.total_edges} edges"
                )
            else:
                print(f"  Graph:   reusing existing SQLite at {db_path}")

            if not wipe and cache_path.exists():
                print(f"  Embed:   reusing existing cache at {cache_path}")
            else:
                kg.build_embeddings(out=cache_path, n_workers=workers)

            # Always wipe LanceDB — embeddings are recomputed fresh so
            # incremental deletes are wasteful and slow.
            stats = kg.build_index_from_cache(cache_path, wipe=True, discover_similar=similar)
        else:
            stats = kg.build(wipe=wipe, discover_similar=similar)
    finally:
        kg.close()

    dt = time.time() - t0
    print(
        f"  Done:    {dt:.1f}s — "
        f"{stats.total_nodes} nodes, {stats.total_edges} edges, "
        f"{stats.indexed_rows} indexed rows"
    )


# ---------------------------------------------------------------------------
# Download helper
# ---------------------------------------------------------------------------


def download_dataset(dest: Path) -> None:
    """Download the LongMemEval-S dataset from HuggingFace."""
    import urllib.request  # pylint: disable=import-outside-toplevel

    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  Downloading LongMemEval-S → {dest}")
    urllib.request.urlretrieve(_LONGMEMEVAL_URL, dest)
    print("  Download complete.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a DocKG from the LongMemEval corpus.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("data_file", help="Path to longmemeval_s_cleaned.json")
    parser.add_argument(
        "--wipe",
        action="store_true",
        help="Rebuild corpus and KG from scratch",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Override sentence-transformer model",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Worker processes for embedding (enables two-phase build)",
    )
    parser.add_argument(
        "--emb-cache",
        default=None,
        help=f"Embedding cache JSON path (two-phase). Default: {DEFAULT_EMB_CACHE}",
    )
    parser.add_argument(
        "--corpus-dir",
        default=str(DEFAULT_CORPUS_DIR),
        help="Corpus output directory",
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB),
        help="SQLite graph database path",
    )
    parser.add_argument(
        "--lancedb",
        default=str(DEFAULT_LANCEDB),
        help="LanceDB vector index directory",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Download the dataset from HuggingFace if data_file does not exist",
    )
    parser.add_argument(
        "--no-similar",
        action="store_true",
        help="Skip SIMILAR_TO edge discovery (recommended for large corpora >100K chunks)",
    )
    parser.add_argument(
        "--skip-corpus",
        action="store_true",
        help="Skip corpus writing (assumes Markdown files already exist)",
    )

    args = parser.parse_args()
    data_file = Path(args.data_file).resolve()

    if not data_file.exists():
        if args.download:
            download_dataset(data_file)
        else:
            sys.exit(
                f"ERROR: data file not found: {data_file}\n"
                f"  Re-run with --download to fetch it automatically."
            )

    print("=" * 60)
    print("  DocKG Build Pipeline")
    print("=" * 60)

    if not args.skip_corpus:
        write_corpus(data_file, Path(args.corpus_dir), force=args.wipe)

    build_kg(
        corpus_dir=Path(args.corpus_dir),
        db_path=Path(args.db),
        lancedb_dir=Path(args.lancedb),
        wipe=args.wipe,
        model=args.model,
        workers=args.workers,
        emb_cache=Path(args.emb_cache) if args.emb_cache else None,
        similar=not args.no_similar,
    )


if __name__ == "__main__":
    main()
