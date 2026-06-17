#!/usr/bin/env python3
"""
embedder_worker.py

CorpusEmbedder — Stage 3 of the multipass analysis pipeline.

Multi-process corpus embedding using spawn-safe workers. Each worker loads
its own ``SentenceTransformer`` instance independently — no shared state,
no GIL contention.

Produces a JSON cache containing aligned (embeddings, texts, metadata)
triples consumable by the ManifoldAnalyzer and downstream analysis.

Usage::

    from doc_kg.embedder_worker import CorpusEmbedder

    embedder = CorpusEmbedder("all-mpnet-base-v2", n_workers=4)
    cache = embedder.embed(texts, metadata)
    embedder.save_cache(cache, Path("embeddings.json"))

Author: Eric G. Suchanek, PhD
"""

from __future__ import annotations

import gzip
import json
import logging
import multiprocessing
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from kg_utils.embedder import load_sentence_transformer

logger = logging.getLogger(__name__)

#: Default embedding model for the multipass pipeline.
#: Matches diary_kg: nomic-embed-text-v1 (768-d, asymmetric retrieval).
PIPELINE_MODEL: str = "BAAI/bge-small-en-v1.5"

#: Texts per recycled shard in parallel embedding. With maxtasksperchild=1 the
#: pool spawns a fresh worker per shard, so this is the cadence at which each
#: worker's accumulated allocator/heap state is reset. Sized so the per-shard
#: model reload (~seconds) is a small fraction of the shard's embedding work.
_RECYCLE_SHARD: int = 25_000


# ============================================================================
# Spawn-safe top-level worker function
# ============================================================================


def _embed_shard(args: tuple) -> tuple[int, list[list[float]]]:
    """Worker function: embed a shard of texts with per-batch progress reporting.

    Must be a top-level function (not a method) for pickle-safe multiprocessing
    with the ``spawn`` start method.

    :param args: Tuple of ``(texts, model_name, batch_size, worker_id,
        progress_queue, device)``.  *progress_queue* receives ``int`` counts
        after each batch and ``None`` as a sentinel when the shard is finished
        (pass ``None`` to skip progress reporting, e.g. sequential mode).
        *device* pins this worker's model to a concrete device (e.g. ``"cpu"``);
        ``None`` falls back to ``KG_EMBED_DEVICE`` / auto-detect.  Pinning is what
        keeps N parallel CPU workers from each auto-selecting MPS and stacking N
        GPU allocations into an OOM.
    :return: ``(worker_id, vectors)`` tuple so callers can reassemble in order.
    """
    texts, model_name, batch_size, worker_id, progress_queue, device = args

    # Suppress noisy logging in workers
    logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
    logging.getLogger("transformers").setLevel(logging.WARNING)

    # kg_utils' load_sentence_transformer auto-detects the device and returns a
    # model already moved onto it. When a worker is pinned (e.g. ``"cpu"`` for
    # parallel CPU shards), move it explicitly so inference runs on the pinned
    # device rather than each worker's auto-selected accelerator — what keeps N
    # parallel CPU workers from each running encode() on MPS and OOMing.
    model = load_sentence_transformer(model_name)
    if device:
        model = model.to(device)

    # Nomic v1 requires a task prefix for asymmetric retrieval mode
    if "nomic-ai/" in model_name:
        texts = [f"search_document: {t}" for t in texts]

    all_vecs = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        vecs = model.encode(
            batch,
            convert_to_numpy=True,
            show_progress_bar=False,
            normalize_embeddings=True,
        )
        all_vecs.extend(vecs)
        if progress_queue is not None:
            progress_queue.put(len(batch))

    if progress_queue is not None:
        progress_queue.put(None)  # sentinel: shard complete

    return worker_id, [np.asarray(v, dtype="float32").tolist() for v in all_vecs]


# ============================================================================
# Embedding cache
# ============================================================================


@dataclass
class EmbeddingCache:
    """Aligned cache of embeddings, texts, and metadata.

    :param model: Model name used for embedding.
    :param dim: Embedding dimension.
    :param texts: Original texts (aligned with vectors).
    :param vectors: Float32 embedding vectors.
    :param metadata: Per-text metadata dicts (aligned with texts/vectors).
    :param created_at: ISO timestamp of cache creation.
    """

    model: str
    dim: int
    texts: list[str]
    vectors: list[list[float]]
    metadata: list[dict] = field(default_factory=list)
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(tz=UTC).isoformat()

    @property
    def n_vectors(self) -> int:
        """Return the number of embedding vectors in this batch."""
        return len(self.vectors)


# ============================================================================
# CorpusEmbedder
# ============================================================================


def _resolve_device(device: str | None) -> str | None:
    """Resolve the embedding device: explicit arg > ``KG_EMBED_DEVICE`` > auto.

    Returns a concrete device string (``"cpu"`` / ``"mps"`` / ``"cuda"``) so the
    value can both pin workers *and* gate parallelism.  Returns ``None`` only when
    torch is unavailable, in which case callers treat it as "let the loader
    decide".

    :param device: Explicit device override, or ``None``.
    :return: Resolved device string, or ``None`` if undeterminable.
    """
    sel = (device or os.environ.get("KG_EMBED_DEVICE", "")).strip().lower()
    if sel:
        return sel
    try:
        import torch  # pylint: disable=import-outside-toplevel

        if torch.cuda.is_available():
            return "cuda"
        return "mps" if torch.backends.mps.is_available() else "cpu"
    except Exception:  # noqa: BLE001
        return None


class CorpusEmbedder:
    """Multi-process corpus embedding engine.

    :param model_name: HuggingFace model name.
    :param n_workers: Number of parallel workers (default: CPU count / 2).
    :param batch_size: Per-worker batch size.
    :param device: Embedding device (``"cpu"``/``"mps"``/``"cuda"``).  ``None``
        resolves via ``KG_EMBED_DEVICE`` then auto-detect.  A GPU device forces
        single-process embedding — the GPU can't be shared across spawn workers,
        so N workers would stack N allocations and OOM.  Only CPU fans out.
    """

    def __init__(
        self,
        model_name: str = PIPELINE_MODEL,
        *,
        n_workers: int | None = None,
        batch_size: int = 64,
        device: str | None = None,
    ) -> None:
        self.model_name = model_name
        self.n_workers = n_workers or max(1, (os.cpu_count() or 2) // 2)
        self.batch_size = batch_size
        self.device = _resolve_device(device)

    def embed(
        self,
        texts: list[str],
        metadata: list[dict] | None = None,
        *,
        sample_n: int | None = None,
    ) -> EmbeddingCache:
        """Embed texts using multiprocessing pool.

        :param texts: Texts to embed.
        :param metadata: Optional per-text metadata (aligned with texts).
        :param sample_n: If set, evenly sample N texts before embedding.
        :return: :class:`EmbeddingCache` with all embeddings.
        """
        if metadata is None:
            metadata = [{} for _ in texts]

        # Temporal sampling if requested
        if sample_n and sample_n < len(texts):
            indices = [round(i * (len(texts) - 1) / (sample_n - 1)) for i in range(sample_n)]
            indices = sorted(set(indices))
            texts = [texts[i] for i in indices]
            metadata = [metadata[i] for i in indices]

        if not texts:
            return EmbeddingCache(model=self.model_name, dim=0, texts=[], vectors=[])

        t0 = time.monotonic()

        # Parallel embedding only pays off on CPU. A GPU device (mps/cuda) can't
        # be shared across spawn workers without stacking allocations into an
        # OOM, so it always runs single-process here — the guard that keeps any
        # caller (per-book ingest, diaries, consolidated build) from re-tripping
        # the multi-worker MPS OOM.
        on_gpu = (self.device or "") in {"mps", "cuda"}
        if len(texts) < 50 or self.n_workers <= 1 or on_gpu:
            vectors = self._embed_sequential(texts)
        else:
            vectors = self._embed_parallel(texts)

        elapsed = time.monotonic() - t0
        dim = len(vectors[0]) if vectors else 0

        logger.info(
            "Embedded %d texts (%d-dim) in %.1fs with %d workers",
            len(texts),
            dim,
            elapsed,
            self.n_workers,
        )

        return EmbeddingCache(
            model=self.model_name,
            dim=dim,
            texts=texts,
            vectors=vectors,
            metadata=metadata,
        )

    def _embed_sequential(self, texts: list[str]) -> list[list[float]]:
        """Embed in the main process (small inputs or single worker)."""
        _, vectors = _embed_shard((texts, self.model_name, self.batch_size, 0, None, self.device))
        return vectors

    def _embed_parallel(self, texts: list[str]) -> list[list[float]]:
        """Embed using multiprocessing pool with rich progress."""
        from rich.progress import (  # pylint: disable=import-outside-toplevel
            BarColumn,
            MofNCompleteColumn,
            Progress,
            SpinnerColumn,
            TextColumn,
            TimeElapsedColumn,
            TimeRemainingColumn,
        )

        # Split into MANY small shards (>> n_workers) rather than one giant shard
        # per worker. Combined with ``maxtasksperchild=1`` below, the pool spawns a
        # FRESH process for each shard: long-lived embedding workers accumulate
        # allocator/heap/GC state that decays throughput over a large run, and
        # recycling resets every worker to a clean process — keeping throughput
        # flat regardless of corpus size. ``_RECYCLE_SHARD`` is large enough that
        # the per-shard model reload stays a small fraction of the shard's work,
        # but small enough to recycle well before degradation sets in. For small
        # inputs it collapses back to ~one shard per worker.
        per_worker = (len(texts) + self.n_workers - 1) // self.n_workers
        shard_size = max(self.batch_size, min(_RECYCLE_SHARD, per_worker))
        shards_base = [
            (texts[start : start + shard_size], self.model_name, self.batch_size, i)
            for i, start in enumerate(range(0, len(texts), shard_size))
        ]

        # Use spawn to avoid fork-unsafe tokenizer/CUDA issues
        ctx = multiprocessing.get_context("spawn")
        n_shards = len(shards_base)
        results: dict[int, list[list[float]]] = {}
        stop_event = threading.Event()

        try:
            # Manager.Queue() is a proxy — picklable across spawn boundary
            with multiprocessing.Manager() as manager:
                progress_queue = manager.Queue()
                shards = [(*s, progress_queue, self.device) for s in shards_base]

                # maxtasksperchild=1 → a fresh worker per shard (see above).
                with ctx.Pool(processes=self.n_workers, maxtasksperchild=1) as pool:
                    with Progress(
                        SpinnerColumn(),
                        TextColumn("[progress.description]{task.description}"),
                        BarColumn(),
                        MofNCompleteColumn(),
                        TimeElapsedColumn(),
                        TimeRemainingColumn(),
                    ) as progress:
                        task = progress.add_task(
                            f"  Embedding ({self.n_workers} workers, {n_shards} recycled shards)",
                            total=len(texts),
                        )

                        def _drain() -> None:
                            """Consume per-batch counts from the queue, advance the bar."""
                            done = 0
                            while done < n_shards and not stop_event.is_set():
                                try:
                                    item = progress_queue.get(timeout=0.05)
                                except Exception:  # queue.Empty or OS error  # pylint: disable=broad-exception-caught
                                    continue
                                if item is None:
                                    done += 1
                                else:
                                    progress.advance(task, item)

                        drain_thread = threading.Thread(target=_drain, daemon=True)
                        drain_thread.start()

                        for worker_id, shard_vecs in pool.imap_unordered(_embed_shard, shards):
                            results[worker_id] = shard_vecs

                        drain_thread.join(timeout=5.0)

        except Exception as exc:  # pylint: disable=broad-exception-caught
            stop_event.set()
            logger.warning("Multiprocessing failed (%s), falling back to sequential", exc)
            return self._embed_sequential(texts)
        finally:
            stop_event.set()

        # Reassemble in original shard order
        all_vectors: list[list[float]] = []
        for i in range(n_shards):
            all_vectors.extend(results[i])
        return all_vectors

    @staticmethod
    def save_cache(cache: EmbeddingCache, path: Path) -> None:
        """Save embedding cache to JSON file.

        :param cache: Cache to save.
        :param path: Output path.
        """
        path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "model": cache.model,
            "dim": cache.dim,
            "n_vectors": cache.n_vectors,
            "created_at": cache.created_at,
            "texts": cache.texts,
            "metadata": cache.metadata,
            "embeddings": cache.vectors,
        }

        logger.info("Saving %d embeddings to %s …", cache.n_vectors, path)
        print(
            f"  cache    : saving {cache.n_vectors:,} vectors to {path.name} …",
            flush=True,
        )
        t0 = time.monotonic()

        open_fn = gzip.open if path.suffix == ".gz" else open
        with open_fn(path, "wt", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

        elapsed = time.monotonic() - t0
        size_mb = path.stat().st_size / 1_048_576
        logger.info(
            "Saved %d embeddings to %s (%.0f MB) in %.1fs",
            cache.n_vectors,
            path,
            size_mb,
            elapsed,
        )
        print(f"  cache    : saved {size_mb:,.0f} MB in {elapsed:.1f}s", flush=True)

    @staticmethod
    def load_cache(path: Path) -> EmbeddingCache:
        """Load embedding cache from JSON file.

        :param path: Path to JSON cache.
        :return: :class:`EmbeddingCache`.
        """
        size_mb = path.stat().st_size / 1_048_576
        logger.info("Loading embedding cache: %s (%.0f MB) …", path.name, size_mb)
        t0 = time.monotonic()

        open_fn = gzip.open if path.suffix == ".gz" else open
        with open_fn(path, "rt", encoding="utf-8") as f:
            data = json.load(f)

        elapsed = time.monotonic() - t0
        n = len(data.get("embeddings", []))
        logger.info("Cache loaded: %d vectors in %.1fs", n, elapsed)

        return EmbeddingCache(
            model=data.get("model", "unknown"),
            dim=data.get("dim", 0),
            texts=data.get("texts", []),
            vectors=data.get("embeddings", []),
            metadata=data.get("metadata", []),
            created_at=data.get("created_at", ""),
        )
