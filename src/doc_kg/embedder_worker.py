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
from kg_utils.embed import resolve_model_path

logger = logging.getLogger(__name__)

#: Default embedding model for the multipass pipeline.
#: Matches diary_kg: nomic-embed-text-v1 (768-d, asymmetric retrieval).
PIPELINE_MODEL: str = "nomic-ai/nomic-embed-text-v1"


def _local_model_path(model_name: str) -> Path:
    """Return the local cache path for *model_name* (dockg-scoped fallback)."""
    return resolve_model_path(model_name, local_fallback=Path.cwd() / ".dockg" / "models")


# ============================================================================
# Spawn-safe top-level worker function
# ============================================================================


def _embed_shard(args: tuple) -> tuple[int, list[list[float]]]:
    """Worker function: embed a shard of texts with per-batch progress reporting.

    Must be a top-level function (not a method) for pickle-safe multiprocessing
    with the ``spawn`` start method.

    :param args: Tuple of ``(texts, model_name, batch_size, worker_id, progress_queue)``.
        *progress_queue* receives ``int`` counts after each batch and ``None`` as a
        sentinel when the shard is finished.  Pass ``None`` for the queue to skip
        progress reporting (e.g. sequential mode).
    :return: ``(worker_id, vectors)`` tuple so callers can reassemble in order.
    """
    texts, model_name, batch_size, worker_id, progress_queue = args

    # Suppress noisy logging in workers
    os.environ["TQDM_DISABLE"] = "1"
    logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
    logging.getLogger("transformers").setLevel(logging.WARNING)

    from sentence_transformers import (  # pylint: disable=import-outside-toplevel
        SentenceTransformer,
    )

    trust_remote = "nomic-ai/" in model_name
    local_path = _local_model_path(model_name)
    if local_path.exists():
        model = SentenceTransformer(str(local_path), trust_remote_code=trust_remote)
    else:
        try:
            model = SentenceTransformer(
                model_name, local_files_only=True, trust_remote_code=trust_remote
            )
        except OSError:
            model = SentenceTransformer(model_name, trust_remote_code=trust_remote)

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


class CorpusEmbedder:
    """Multi-process corpus embedding engine.

    :param model_name: HuggingFace model name.
    :param n_workers: Number of parallel workers (default: CPU count / 2).
    :param batch_size: Per-worker batch size.
    """

    def __init__(
        self,
        model_name: str = PIPELINE_MODEL,
        *,
        n_workers: int | None = None,
        batch_size: int = 64,
    ) -> None:
        self.model_name = model_name
        self.n_workers = n_workers or max(1, (os.cpu_count() or 2) // 2)
        self.batch_size = batch_size

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

        # For small inputs or single worker, run in main process
        if len(texts) < 50 or self.n_workers <= 1:
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
        _, vectors = _embed_shard((texts, self.model_name, self.batch_size, 0, None))
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

        # Split texts into shards
        n = self.n_workers
        shard_size = (len(texts) + n - 1) // n
        shards_base = []
        for i in range(n):
            start = i * shard_size
            end = min(start + shard_size, len(texts))
            if start < len(texts):
                shards_base.append((texts[start:end], self.model_name, self.batch_size, i))

        # Use spawn to avoid fork-unsafe tokenizer/CUDA issues
        ctx = multiprocessing.get_context("spawn")
        n_shards = len(shards_base)
        results: dict[int, list[list[float]]] = {}
        stop_event = threading.Event()

        try:
            # Manager.Queue() is a proxy — picklable across spawn boundary
            with multiprocessing.Manager() as manager:
                progress_queue = manager.Queue()
                shards = [(*s, progress_queue) for s in shards_base]

                with ctx.Pool(processes=n_shards) as pool:
                    with Progress(
                        SpinnerColumn(),
                        TextColumn("[progress.description]{task.description}"),
                        BarColumn(),
                        MofNCompleteColumn(),
                        TimeElapsedColumn(),
                        TimeRemainingColumn(),
                    ) as progress:
                        task = progress.add_task(
                            f"  Embedding ({n_shards} workers)", total=len(texts)
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
        print(f"  cache    : saving {cache.n_vectors:,} vectors to {path.name} …", flush=True)
        t0 = time.monotonic()

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=None)

        elapsed = time.monotonic() - t0
        size_mb = path.stat().st_size / 1_048_576
        logger.info(
            "Saved %d embeddings to %s (%.0f MB) in %.1fs", cache.n_vectors, path, size_mb, elapsed
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

        with open(path, encoding="utf-8") as f:
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
