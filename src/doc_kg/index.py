#!/usr/bin/env python3
"""
index.py

SemanticIndex — semantic vector index for DocKG.

Backed by a sqlite-vec store (``vectors.sqlite``). LanceDB support, kept as a
read-only legacy backend from 0.20.0, was removed in 0.29.0 with the SDK's.

Mirrors PyCodeKG's index.py with the following additions:

1. Default model is BAAI/bge-small-en-v1.5 — wins across literary and
   technical retrieval benchmarks; same model as PyCodeKG.

2. After building the vector index, ``build()`` optionally runs a
   SIMILAR_TO edge discovery pass: each chunk is queried against its
   k-nearest neighbors and edges are written back to the GraphStore when
   cosine similarity exceeds *similarity_edge_threshold*.  This creates
   the semantic graph layer that makes DocKG more than a pure vector store.

3. ``_build_index_text()`` is adapted for document nodes: uses title,
   section context, and chunk text instead of kind/qualname/docstring.

Author: Eric G. Suchanek, PhD
"""

from __future__ import annotations

import contextlib
import gc
import gzip
import json
import logging
import os
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, TextIO, cast

from kg_utils.embed import DEFAULT_MODEL
from kg_utils.embedder import Embedder, SentenceTransformerEmbedder
from kg_utils.vector_backend import SqliteVecBackend, VectorBackend
from rich.console import Console

if TYPE_CHECKING:
    from doc_kg.store import GraphStore

# Metadata columns DocKG persists per vector (id + these). Filterable in the
# sqlite backend's ``where`` prefilter.
_META_COLUMNS = ("kind", "name", "title", "file_path")


# ---------------------------------------------------------------------------
# Logging / progress suppression
# ---------------------------------------------------------------------------


def suppress_ingestion_logging() -> None:
    """Suppress verbose progress output during model loading and ingestion."""
    for name in ("sentence_transformers", "transformers", "huggingface_hub"):
        logging.getLogger(name).setLevel(logging.WARNING)

    try:
        import transformers  # pylint: disable=import-outside-toplevel

        transformers.logging.set_verbosity_error()
    except (ImportError, AttributeError):
        pass

    try:
        import tqdm as _tqdm  # pylint: disable=import-outside-toplevel

        _orig_init = _tqdm.tqdm.__init__

        def _silent_init(self, *args, **kwargs):
            kwargs["disable"] = True
            _orig_init(self, *args, **kwargs)

        _tqdm.tqdm.__init__ = _silent_init

        try:
            import tqdm.auto as _tqdm_auto  # pylint: disable=import-outside-toplevel

            if _tqdm_auto.tqdm is not _tqdm.tqdm:
                _tqdm_auto.tqdm.__init__ = _silent_init
        except ImportError:
            pass
    except (ImportError, AttributeError):
        pass


# Embedder and SentenceTransformerEmbedder are imported from kg_utils.embedder
# above — re-exported here for backward compatibility.


def make_embedder(model_name: str = DEFAULT_MODEL, *, device: str = "auto") -> Embedder:
    """Construct a sentence-transformer embedder with optional device override.

    :param model_name: Embedding model name or alias.
    :param device: ``auto`` (default), ``cpu``, ``mps``, or ``cuda``.
    :return: Configured embedder instance.
    """
    emb = SentenceTransformerEmbedder(model_name)
    if device != "auto":
        emb_any: Any = emb
        emb_any.model = emb_any.model.to(device)
        emb_any.device = device
    return emb


# ---------------------------------------------------------------------------
# Seed hit
# ---------------------------------------------------------------------------


@dataclass
class SeedHit:
    """A single result from a semantic vector search.

    :param id: Node ID.
    :param kind: Node kind (``document``, ``section``, ``chunk``).
    :param name: Short name.
    :param title: Section or document title.
    :param file_path: Corpus-relative file path.
    :param distance: Vector distance (lower = more similar).
    :param rank: Zero-based rank in the result list.
    """

    id: str
    kind: str
    name: str
    title: str
    file_path: str
    distance: float
    rank: int


# ---------------------------------------------------------------------------
# SemanticIndex
# ---------------------------------------------------------------------------

_DEFAULT_KINDS = ("document", "section", "chunk", "topic", "entity", "keyword")


def _is_jsonl_cache(path: Path) -> bool:
    return path.suffix == ".jsonl" or path.name.endswith(".jsonl.gz")


def _open_text_auto(path: Path, mode: str) -> TextIO:
    if path.suffix == ".gz":
        return cast(TextIO, gzip.open(path, mode, encoding="utf-8"))
    return cast(TextIO, open(path, mode, encoding="utf-8"))


class SemanticIndex:
    """Semantic vector index for DocKG.

    Reads nodes from a :class:`~doc_kg.store.GraphStore`, embeds them, and
    stores the vectors in a sqlite-vec store (``vectors.sqlite``).  The index is
    **derived and disposable** — it can be rebuilt from SQLite at any time
    without data loss.

    After building the vector index, optionally runs a SIMILAR_TO edge
    discovery pass that writes semantic similarity edges back to the store.

    Example::

        embedder = SentenceTransformerEmbedder()
        idx = SemanticIndex("./.dockg/vectors.sqlite", embedder=embedder)
        idx.build(store, wipe=True)

        hits = idx.search("climate change policy", k=8)
        for h in hits:
            print(h.id, h.distance)

    Changed in 0.29.0: the first parameter was ``lancedb_dir``, a *directory*
    the sqlite-vec store was derived beside. It is now ``vectors_path``, the
    store's file, as in :class:`kg_utils.semantic.SemanticIndex`; ``table``
    and the ``ann_*`` options went with LanceDB.

    :param vectors_path: The ``vectors.sqlite`` store.
    :param embedder: Embedding backend.
    :param index_kinds: Node kinds to embed.
    :param backend: Vector backend; defaults to a sqlite-vec store at
        *vectors_path*, constructed on first use.
    """

    def __init__(
        self,
        vectors_path: str | Path,
        *,
        embedder: Embedder | None = None,
        index_kinds: Sequence[str] = _DEFAULT_KINDS,
        backend: VectorBackend | None = None,
    ) -> None:
        self.vectors_path = Path(vectors_path)
        self.embedder: Embedder = embedder or SentenceTransformerEmbedder()
        self.index_kinds = tuple(index_kinds)
        # Vector store backend (sqlite-vec by default, constructed lazily so the
        # embedder's ``dim`` — which may load the model — is only touched on use).
        self._backend: VectorBackend | None = backend

    # ------------------------------------------------------------------
    # Backend
    # ------------------------------------------------------------------

    def _get_backend(self) -> VectorBackend:
        """Return the vector backend, constructing the sqlite-vec store lazily.

        Deferred so the embedder's ``dim`` (which may load the model) is only
        touched when the index is built or searched.
        """
        if self._backend is None:
            self._backend = sqlite_backend(self.vectors_path, dim=self.embedder.dim)
        return self._backend

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(
        self,
        store: GraphStore,
        *,
        wipe: bool = False,
        batch_size: int = 8192,
        encode_batch_size: int = 128,
        quiet: bool = False,
        discover_similar: bool = True,
        similar_k: int = 5,
        similarity_edge_threshold: float = 0.85,
        similar_max_degree: int = 0,
    ) -> dict:
        """Build (or rebuild) the vector index from *store*.

        After indexing, optionally discovers SIMILAR_TO edges between
        semantically close chunk nodes and writes them back to *store*.

        :param store: Authoritative :class:`~doc_kg.store.GraphStore`.
        :param wipe: If ``True``, delete all existing vectors first.
        :param batch_size: Vector-store write batch size.
        :param encode_batch_size: Nodes fetched per streaming page and fed to
                                   ``model.encode()``.  Attention memory scales
                                   with ``batch x seq^2`` and throughput is flat
                                   above ~128 on CPU/MPS, so the encode sub-batch
                                   is hard-capped at 128 regardless (default 128;
                                   raise only for large-VRAM CUDA with short seqs).
        :param quiet: Suppress progress output (default: ``False``).
        :param discover_similar: If ``True``, run SIMILAR_TO edge discovery.
        :param similar_k: k-nearest neighbors to examine per chunk.
        :param similarity_edge_threshold: Minimum cosine similarity to emit a
                                          SIMILAR_TO edge (0–1).
        :return: Stats dict.
        """
        if quiet:
            suppress_ingestion_logging()

        import numpy as np  # pylint: disable=import-outside-toplevel

        # Count without loading any text — used for the progress bar and chunk pre-alloc.
        n_total = store.count_nodes(kinds=list(self.index_kinds))
        n_chunks = store.count_nodes(kinds=["chunk"]) if discover_similar else 0

        if not quiet:
            Console().print(f"  nodes    : {n_total:,} to embed")
        backend = self._get_backend()
        backend.open(wipe=wipe)

        indexed = 0
        all_ids: list[str] = []
        telemetry_every = 25
        # Per-batch ingest telemetry is noisy on long corpus builds; silent
        # unless DOCKG_EMBED_TELEMETRY is set truthy. The periodic allocator
        # cache-release below still runs regardless.
        show_telemetry = os.getenv("DOCKG_EMBED_TELEMETRY", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        write_batch_size = max(int(batch_size), int(encode_batch_size))
        pending_rows: list[dict[str, Any]] = []
        pending_ids: list[str] = []
        # Fixed encode sub-batch for the whole run. Long-run backend drift is
        # handled by releasing allocator caches at each telemetry checkpoint
        # (below), never by reloading the model mid-run: a reload discards a
        # caller-supplied shared embedder (e.g. DiaryKG reuses its transformer's
        # model) and on MPS risks a second-load SIGBUS.
        eff_encode_batch = min(max(64, int(encode_batch_size)), 128)
        # Pre-allocate a contiguous (n_chunks × dim) matrix for chunk vectors so
        # the SIMILAR_TO ANN pass has a compact array rather than 300K+ loose ndarrays.
        chunk_pair_ids: list[str] = []
        chunk_pair_vecs: Any = (
            np.empty((n_chunks, self.embedder.dim), dtype=np.float32)
            if discover_similar and n_chunks > 0
            else None
        )
        chunk_vec_idx = 0

        if not quiet:
            from rich.progress import (  # pylint: disable=import-outside-toplevel
                BarColumn,
                MofNCompleteColumn,
                Progress,
                SpinnerColumn,
                TextColumn,
                TimeElapsedColumn,
                TimeRemainingColumn,
            )

            _progress_ctx: contextlib.AbstractContextManager = Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                TimeElapsedColumn(),
                TimeRemainingColumn(),
            )
        else:
            _progress_ctx = contextlib.nullcontext()

        with _progress_ctx as prog:
            task_id = prog.add_task("  Embedding", total=n_total) if prog is not None else None
            batches = 0
            window_embed_s = 0.0
            window_add_s = 0.0
            window_rows = 0
            # Stream nodes in encode_batch_size pages — never hold all node dicts in RAM.
            for enc_nodes in store.iter_nodes(
                kinds=list(self.index_kinds), batch_size=encode_batch_size
            ):
                batches += 1
                enc_texts = [_build_index_text(n) for n in enc_nodes]
                t_embed0 = time.perf_counter()
                embedder_any: Any = self.embedder
                # Hard-cap the encode sub-batch at 128 from row 0: transformer
                # attention memory scales with batch x seq^2, so a larger batch on
                # long (near-max-sequence) chunks allocates many GB per encode and
                # OOMs / stalls MPS.  Throughput is flat above ~128 on CPU/MPS, so
                # the cap costs nothing and protects even an explicit large override.
                eff_batch = eff_encode_batch
                enc_vecs: list[list[float]] = []
                for i in range(0, len(enc_texts), eff_batch):
                    sub = enc_texts[i : i + eff_batch]
                    try:
                        sub_vecs = embedder_any.embed_texts(sub, eff_batch)
                    except TypeError:
                        sub_vecs = self.embedder.embed_texts(sub)
                    enc_vecs.extend(sub_vecs)
                window_embed_s += time.perf_counter() - t_embed0
                window_rows += len(enc_nodes)

                if discover_similar and chunk_pair_vecs is not None:
                    enc_arr = np.asarray(enc_vecs, dtype=np.float32)
                    for node, vec in zip(enc_nodes, enc_arr):
                        if node["id"].startswith("chunk:"):
                            chunk_pair_ids.append(node["id"])
                            chunk_pair_vecs[chunk_vec_idx] = vec
                            chunk_vec_idx += 1

                ids = [n["id"] for n in enc_nodes]

                # Stale-row deletion (incremental builds) and the wipe-build
                # skip-delete fast path both live in backend.upsert() now.
                # Buffer multiple encode batches into fewer, larger writes.
                rows = [
                    {
                        "id": n["id"],
                        "kind": n["kind"],
                        "name": n["name"],
                        "title": n.get("title") or "",
                        "file_path": n.get("file_path") or "",
                        "text": text,
                        "vector": vec,
                    }
                    for n, text, vec in zip(enc_nodes, enc_texts, enc_vecs)
                ]
                pending_rows.extend(rows)
                pending_ids.extend(ids)

                if len(pending_rows) >= write_batch_size:
                    t_add0 = time.perf_counter()
                    backend.upsert(pending_rows, batch_size=len(pending_rows))
                    indexed += len(pending_rows)
                    all_ids.extend(pending_ids)
                    pending_rows = []
                    pending_ids = []
                    window_add_s += time.perf_counter() - t_add0

                if not quiet and batches % telemetry_every == 0:
                    with contextlib.suppress(Exception):
                        if show_telemetry:
                            embed_ms = (
                                (window_embed_s / max(window_rows, 1)) * 1000.0
                                if window_rows
                                else 0.0
                            )
                            add_ms = (
                                (window_add_s / max(window_rows, 1)) * 1000.0
                                if window_rows
                                else 0.0
                            )

                            Console().print(
                                f"  ingest   : batch={batches} rows={indexed:,} "
                                f"embed_ms_per_row={embed_ms:.3f} add_ms_per_row={add_ms:.3f} "
                                f"encode_batch_eff={eff_batch}"
                            )

                        # Long MPS/CUDA runs can degrade as allocator caches grow.
                        # Proactively release backend caches at telemetry checkpoints.
                        with contextlib.suppress(Exception):
                            import torch  # pylint: disable=import-outside-toplevel

                            if torch.cuda.is_available():
                                torch.cuda.empty_cache()
                            elif torch.backends.mps.is_available():
                                torch.mps.empty_cache()
                        gc.collect()
                        window_embed_s = 0.0
                        window_add_s = 0.0
                        window_rows = 0

                if prog is not None and task_id is not None:
                    prog.advance(task_id, len(enc_nodes))

        if pending_rows:
            backend.upsert(pending_rows, batch_size=len(pending_rows))
            indexed += len(pending_rows)
            all_ids.extend(pending_ids)

        # SIMILAR_TO edge discovery — a blocked NumPy matmul, backend-independent.
        similar_edges_added = 0
        if discover_similar and chunk_pair_ids and chunk_pair_vecs is not None:
            similar_edges_added = self._discover_similar_edges(
                store,
                None,
                chunk_pair_ids,
                chunk_pair_vecs[:chunk_vec_idx],
                k=similar_k,
                threshold=similarity_edge_threshold,
                max_degree=similar_max_degree,
                quiet=quiet,
            )

        return {
            "indexed_rows": indexed,
            "dim": self.embedder.dim,
            "model_name": getattr(self.embedder, "model_name", repr(self.embedder)),
            "vectors_path": str(self.vectors_path),
            "kinds": list(self.index_kinds),
            "similar_edges_added": similar_edges_added,
        }

    # ------------------------------------------------------------------
    # Two-phase build: precompute → cache file → vector index
    # ------------------------------------------------------------------

    def _existing_index_ids(self) -> set[str]:
        """Return node ids already vectorized in the store (empty if absent).

        Delegates to the backend. Used by incremental embedding (``only_missing``)
        to skip nodes that already have a vector.

        :return: Set of existing node ids, or an empty set if the store is absent.
        """
        return self._get_backend().existing_ids()

    def prune(self, keep_ids: set[str], *, quiet: bool = False) -> int:
        """Delete index rows whose id is not in *keep_ids* (orphans of removed nodes).

        After an incremental (``only_missing``) embed + upsert, vectors for nodes that
        no longer exist in the graph (e.g. a removed/renamed book) would linger and
        return stale hits. This removes them so the index matches the current graph.

        :param keep_ids: Node ids that should remain in the index.
        :param quiet: Suppress the summary line.
        :return: Number of orphan rows deleted.
        """
        existing = self._existing_index_ids()
        orphans = [i for i in existing if i not in keep_ids]
        if not orphans:
            return 0
        backend = self._get_backend()
        backend.open(wipe=False)
        removed = backend.delete_ids(orphans)
        if not quiet:
            Console().print(f"  pruned {removed:,} orphan vectors from the index")
        return removed

    def precompute_embeddings(
        self,
        store: GraphStore,
        out: Path,
        *,
        n_workers: int | None = None,
        batch_size: int = 64,
        device: str | None = None,
        only_missing: bool = False,
        quiet: bool = False,
    ) -> Path:
        """Embed all index nodes and save to an :class:`~doc_kg.embedder_worker.EmbeddingCache` JSON.

        Pure embedding pass — no vector-store writes.  Call :meth:`build_from_cache`
        afterwards to populate the vector index from the saved file.

        :param store: Source :class:`~doc_kg.store.GraphStore`.
        :param out: Output path for the cache JSON.
        :param n_workers: Worker processes for embedding (default: CPU count / 2).
        :param batch_size: Per-worker embedding batch size.
        :param device: Embedding device (``"cpu"``/``"mps"``/``"cuda"``); ``None``
            resolves via ``KG_EMBED_DEVICE`` then auto-detect.  GPU devices force
            single-process embedding (see :class:`~doc_kg.embedder_worker.CorpusEmbedder`).
        :param only_missing: Incremental embedding — skip nodes whose ``id`` is already
            present in the vector store, so only new/changed nodes are embedded.
            Pair with ``build_from_cache(wipe=False)`` to upsert. No-op (embeds all)
            when the table doesn't exist yet. Honored on the ``.json`` path only.
        :param quiet: Suppress progress output.
        :return: Path to the saved cache file (*out*).
        """
        if _is_jsonl_cache(out):
            # pylint: disable=import-outside-toplevel
            from kg_utils.embedder import resolve_device

            # A GPU device can't fan out across spawn workers, and the single-process
            # stream reuses the (possibly caller-shared) embedder — no second model
            # load, so no MPS double-load SIGBUS. CPU streams in parallel via
            # CorpusEmbedder.embed_to_cache: multi-process AND bounded memory
            # (peak scales with shard size, not corpus size — the 689k-node OOM fix).
            if resolve_device(device) in {"mps", "cuda"}:
                return self._precompute_embeddings_jsonl_stream(
                    store, out, batch_size=batch_size, quiet=quiet
                )
            return self._precompute_embeddings_parallel_stream(
                store,
                out,
                n_workers=n_workers,
                batch_size=batch_size,
                device=device,
                only_missing=only_missing,
                quiet=quiet,
            )

        from doc_kg.embedder_worker import (  # pylint: disable=import-outside-toplevel
            CorpusEmbedder,
        )

        if quiet:
            suppress_ingestion_logging()

        texts, metadata = self._read_texts_metadata(store, only_missing=only_missing, quiet=quiet)

        model_name = getattr(self.embedder, "model_name", DEFAULT_MODEL)
        corp_embedder = CorpusEmbedder(
            model_name=model_name,
            n_workers=n_workers,
            batch_size=batch_size,
            device=device,
        )

        if not quiet:
            Console().print(
                f"  nodes    : {len(texts):,} to embed  ({corp_embedder.n_workers} workers)"
            )

        cache = corp_embedder.embed(texts, metadata)
        CorpusEmbedder.save_cache(cache, out)

        if not quiet:
            Console().print(f"  cache    : {out}  ({cache.n_vectors:,} vectors, dim={cache.dim})")

        return out

    def _read_texts_metadata(
        self, store: GraphStore, *, only_missing: bool, quiet: bool
    ) -> tuple[list[str], list[dict]]:
        """Read index nodes (optionally dropping already-vectorized ones) as
        aligned ``(texts, metadata)`` ready for embedding.

        :param only_missing: Skip nodes whose ``id`` is already in the vector
            store (incremental embedding). No-op when the store is absent.
        """
        nodes = self._read_nodes(store)
        if only_missing:
            existing = self._existing_index_ids()
            if existing:
                before = len(nodes)
                nodes = [n for n in nodes if n["id"] not in existing]
                if not quiet:
                    Console().print(
                        f"  incremental: {before - len(nodes):,} already vectorized, "
                        f"{len(nodes):,} new to embed"
                    )
        texts = [_build_index_text(n) for n in nodes]
        metadata = [
            {
                "id": n["id"],
                "kind": n["kind"],
                "name": n["name"],
                "title": n.get("title") or "",
                "file_path": n.get("file_path") or "",
            }
            for n in nodes
        ]
        return texts, metadata

    def _precompute_embeddings_parallel_stream(
        self,
        store: GraphStore,
        out: Path,
        *,
        n_workers: int | None,
        batch_size: int,
        device: str | None,
        only_missing: bool,
        quiet: bool,
    ) -> Path:
        """Embed via the multi-process ``CorpusEmbedder``, streaming vectors to a
        JSONL cache so peak memory scales with shard size, not corpus size.

        The CPU counterpart to :meth:`_precompute_embeddings_jsonl_stream` (which
        is single-process for GPU). Output is the same JSONL format consumed by
        :meth:`build_from_cache`.
        """
        from doc_kg.embedder_worker import (  # pylint: disable=import-outside-toplevel
            CorpusEmbedder,
        )

        if quiet:
            suppress_ingestion_logging()

        texts, metadata = self._read_texts_metadata(store, only_missing=only_missing, quiet=quiet)
        model_name = getattr(self.embedder, "model_name", DEFAULT_MODEL)
        corp_embedder = CorpusEmbedder(
            model_name=model_name,
            n_workers=n_workers,
            batch_size=batch_size,
            device=device,
        )

        if not quiet:
            Console().print(
                f"  nodes    : {len(texts):,} to embed  "
                f"({corp_embedder.n_workers} workers, streaming JSONL)"
            )

        corp_embedder.embed_to_cache(texts, metadata, out_path=out)

        if not quiet:
            size_mb = out.stat().st_size / 1_048_576
            Console().print(f"  cache    : {out}  ({len(texts):,} vectors, {size_mb:,.0f} MB)")

        return out

    def _precompute_embeddings_jsonl_stream(
        self,
        store: GraphStore,
        out: Path,
        *,
        batch_size: int,
        quiet: bool,
    ) -> Path:
        """Stream embeddings to JSONL/JSONL.GZ without holding a full cache in RAM."""
        if quiet:
            suppress_ingestion_logging()

        out.parent.mkdir(parents=True, exist_ok=True)
        total = store.count_nodes(kinds=list(self.index_kinds))
        model_name = getattr(self.embedder, "model_name", DEFAULT_MODEL)
        dim = int(getattr(self.embedder, "dim", 0) or 0)
        written = 0

        if not quiet:
            from rich.console import Console  # pylint: disable=import-outside-toplevel

            Console().print(f"  nodes    : {total:,} to embed  (streaming JSONL)")

        if not quiet:
            from rich.progress import (  # pylint: disable=import-outside-toplevel
                BarColumn,
                MofNCompleteColumn,
                Progress,
                SpinnerColumn,
                TextColumn,
                TimeElapsedColumn,
                TimeRemainingColumn,
            )

            _progress_ctx: contextlib.AbstractContextManager = Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                TimeElapsedColumn(),
                TimeRemainingColumn(),
            )
        else:
            _progress_ctx = contextlib.nullcontext()

        # The MPS allocator caches freed blocks and never returns them, so a long
        # streaming embed grows unbounded ("other allocations") and OOMs. Evict
        # the cache each batch to keep GPU memory flat — mirrors the eviction the
        # index-build path already does. Store the eviction callable (or None) so
        # we never reassign the imported module.
        mps_empty_cache: Callable[[], None] | None = None
        try:
            import torch  # pylint: disable=import-outside-toplevel

            if hasattr(torch, "mps") and torch.backends.mps.is_available():
                mps_empty_cache = torch.mps.empty_cache
        except Exception:  # noqa: BLE001
            mps_empty_cache = None

        with _open_text_auto(out, "wt") as f:
            header = {
                "__meta__": {
                    "version": 1,
                    "model": model_name,
                    "dim": dim,
                    "created_at": datetime.now(tz=UTC).isoformat(),
                }
            }
            f.write(json.dumps(header, ensure_ascii=False, separators=(",", ":")) + "\n")

            with _progress_ctx as prog:
                task_id = prog.add_task("  Embedding", total=total) if prog is not None else None
                for enc_nodes in store.iter_nodes(
                    kinds=list(self.index_kinds), batch_size=max(1, int(batch_size))
                ):
                    texts = [_build_index_text(n) for n in enc_nodes]
                    embedder_any: Any = self.embedder
                    try:
                        vecs = embedder_any.embed_texts(texts, batch_size)
                    except TypeError:
                        vecs = self.embedder.embed_texts(texts)

                    for n, text, vec in zip(enc_nodes, texts, vecs):
                        row = {
                            "id": n["id"],
                            "kind": n["kind"],
                            "name": n["name"],
                            "title": n.get("title") or "",
                            "file_path": n.get("file_path") or "",
                            "text": text,
                            "vector": vec,
                        }
                        f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                        written += 1

                    f.flush()
                    if mps_empty_cache is not None:
                        mps_empty_cache()
                    if prog is not None and task_id is not None:
                        prog.advance(task_id, len(enc_nodes))

        if not quiet:
            from rich.console import Console  # pylint: disable=import-outside-toplevel

            size_mb = out.stat().st_size / 1_048_576
            Console().print(
                f"  cache    : {out}  ({written:,} vectors, dim={dim}, {size_mb:,.0f} MB)"
            )

        return out

    def build_from_cache(
        self,
        store: GraphStore,
        cache_path: Path,
        *,
        wipe: bool = False,
        batch_size: int = 256,
        quiet: bool = False,
        discover_similar: bool = True,
        similar_k: int = 5,
        similarity_edge_threshold: float = 0.85,
        similar_max_degree: int = 0,
    ) -> dict:
        """Build (or rebuild) the vector index from a pre-computed embedding cache.

        Skips the model-inference pass entirely — loads float32 vectors from
        *cache_path* and writes them straight to the backend.  The cache must have
        been produced by :meth:`precompute_embeddings`.

        :param store: :class:`~doc_kg.store.GraphStore` (needed for SIMILAR_TO writes).
        :param cache_path: Path to the :class:`~doc_kg.embedder_worker.EmbeddingCache` JSON.
        :param wipe: If ``True``, delete all existing vectors first.
        :param batch_size: Vector-store write batch size.
        :param quiet: Suppress progress output.
        :param discover_similar: Run SIMILAR_TO edge discovery after indexing.
        :param similar_k: k-nearest neighbours per chunk for SIMILAR_TO discovery.
        :param similarity_edge_threshold: Minimum cosine similarity for a SIMILAR_TO edge.
        :return: Stats dict (same schema as :meth:`build`).
        """
        if _is_jsonl_cache(cache_path):
            return self._build_from_jsonl_cache(
                store,
                cache_path,
                wipe=wipe,
                batch_size=batch_size,
                quiet=quiet,
                discover_similar=discover_similar,
                similar_k=similar_k,
                similarity_edge_threshold=similarity_edge_threshold,
                similar_max_degree=similar_max_degree,
            )

        import numpy as np  # pylint: disable=import-outside-toplevel

        from doc_kg.embedder_worker import (  # pylint: disable=import-outside-toplevel
            CorpusEmbedder,
        )

        if quiet:
            suppress_ingestion_logging()

        if not quiet:
            from rich.console import Console  # pylint: disable=import-outside-toplevel

            size_mb = cache_path.stat().st_size / 1_048_576
            Console().print(f"  cache    : loading {cache_path.name} ({size_mb:,.0f} MB) …")

        cache = CorpusEmbedder.load_cache(cache_path)

        if not quiet:
            from rich.console import Console  # pylint: disable=import-outside-toplevel

            Console().print(f"  nodes    : {cache.n_vectors:,} from cache ({cache_path.name})")

        backend = self._get_backend()
        backend.open(wipe=wipe)

        indexed = 0
        all_ids: list[str] = []
        n_chunks_cache = sum(1 for m in cache.metadata if m["id"].startswith("chunk:"))
        chunk_pair_ids: list[str] = []
        chunk_pair_vecs: Any = (
            np.empty((n_chunks_cache, cache.dim), dtype=np.float32)
            if discover_similar and n_chunks_cache > 0
            else None
        )
        chunk_vec_idx = 0

        if not quiet:
            from rich.progress import (  # pylint: disable=import-outside-toplevel
                BarColumn,
                MofNCompleteColumn,
                Progress,
                SpinnerColumn,
                TextColumn,
                TimeElapsedColumn,
                TimeRemainingColumn,
            )

            _progress_ctx: contextlib.AbstractContextManager = Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                TimeElapsedColumn(),
                TimeRemainingColumn(),
            )
        else:
            _progress_ctx = contextlib.nullcontext()

        with _progress_ctx as prog:
            task_id = (
                prog.add_task("  Indexing from cache", total=cache.n_vectors)
                if prog is not None
                else None
            )
            for i in range(0, cache.n_vectors, batch_size):
                batch_meta = cache.metadata[i : i + batch_size]
                batch_texts = cache.texts[i : i + batch_size]
                batch_vecs_raw = cache.vectors[i : i + batch_size]

                vec_arr = np.asarray(batch_vecs_raw, dtype=np.float32)

                if discover_similar and chunk_pair_vecs is not None:
                    for meta, vec in zip(batch_meta, vec_arr):
                        if meta["id"].startswith("chunk:"):
                            chunk_pair_ids.append(meta["id"])
                            chunk_pair_vecs[chunk_vec_idx] = vec
                            chunk_vec_idx += 1

                ids = [m["id"] for m in batch_meta]
                rows = [
                    {
                        "id": m["id"],
                        "kind": m["kind"],
                        "name": m["name"],
                        "title": m.get("title") or "",
                        "file_path": m.get("file_path") or "",
                        "text": text,
                        "vector": vec.tolist(),
                    }
                    for m, text, vec in zip(batch_meta, batch_texts, vec_arr)
                ]
                backend.upsert(rows, batch_size=len(rows))
                indexed += len(rows)
                all_ids.extend(ids)
                if prog is not None and task_id is not None:
                    prog.advance(task_id, len(batch_meta))

        similar_edges_added = 0
        if discover_similar and chunk_pair_ids and chunk_pair_vecs is not None:
            similar_edges_added = self._discover_similar_edges(
                store,
                None,
                chunk_pair_ids,
                chunk_pair_vecs[:chunk_vec_idx],
                k=similar_k,
                threshold=similarity_edge_threshold,
                max_degree=similar_max_degree,
                quiet=quiet,
            )

        return {
            "indexed_rows": indexed,
            "dim": cache.dim,
            "model_name": cache.model,
            "vectors_path": str(self.vectors_path),
            "kinds": list(self.index_kinds),
            "similar_edges_added": similar_edges_added,
        }

    def _build_from_jsonl_cache(
        self,
        store: GraphStore,
        cache_path: Path,
        *,
        wipe: bool,
        batch_size: int,
        quiet: bool,
        discover_similar: bool,
        similar_k: int,
        similarity_edge_threshold: float,
        similar_max_degree: int,
    ) -> dict:
        """Build the vector index from a streaming JSONL cache, without loading all rows in RAM."""
        import numpy as np  # pylint: disable=import-outside-toplevel

        if quiet:
            suppress_ingestion_logging()

        if not quiet:
            from rich.console import Console  # pylint: disable=import-outside-toplevel

            size_mb = cache_path.stat().st_size / 1_048_576
            Console().print(f"  cache    : loading {cache_path.name} ({size_mb:,.0f} MB) …")

        backend = self._get_backend()
        backend.open(wipe=wipe)
        indexed = 0
        model_name = "unknown"
        dim = 0
        pending_rows: list[dict[str, Any]] = []
        pending_ids: list[str] = []
        chunk_pair_ids: list[str] = []
        chunk_vecs_list: list[Any] = [] if discover_similar else []

        with _open_text_auto(cache_path, "rt") as f:
            first = f.readline()
            if first:
                first_obj = json.loads(first)
                meta = first_obj.get("__meta__", {}) if isinstance(first_obj, dict) else {}
                model_name = str(meta.get("model") or model_name)
                dim = int(meta.get("dim") or dim)

            for line in f:
                if not line.strip():
                    continue
                row = json.loads(line)
                rid = row["id"]
                vec = row["vector"]
                if not dim:
                    dim = len(vec)

                pending_rows.append(
                    {
                        "id": rid,
                        "kind": row.get("kind", ""),
                        "name": row.get("name", ""),
                        "title": row.get("title") or "",
                        "file_path": row.get("file_path") or "",
                        "text": row.get("text") or "",
                        "vector": vec,
                    }
                )
                pending_ids.append(rid)

                if discover_similar and rid.startswith("chunk:"):
                    chunk_pair_ids.append(rid)
                    chunk_vecs_list.append(vec)

                if len(pending_rows) >= max(1, int(batch_size)):
                    backend.upsert(pending_rows, batch_size=len(pending_rows))
                    indexed += len(pending_rows)
                    pending_rows = []
                    pending_ids = []

        if pending_rows:
            backend.upsert(pending_rows, batch_size=len(pending_rows))
            indexed += len(pending_rows)

        similar_edges_added = 0
        if discover_similar and chunk_pair_ids and chunk_vecs_list:
            chunk_pair_vecs = np.asarray(chunk_vecs_list, dtype=np.float32)
            similar_edges_added = self._discover_similar_edges(
                store,
                None,
                chunk_pair_ids,
                chunk_pair_vecs,
                k=similar_k,
                threshold=similarity_edge_threshold,
                max_degree=similar_max_degree,
                quiet=quiet,
            )

        return {
            "indexed_rows": indexed,
            "dim": dim,
            "model_name": model_name,
            "vectors_path": str(self.vectors_path),
            "kinds": list(self.index_kinds),
            "similar_edges_added": similar_edges_added,
        }

    # ------------------------------------------------------------------
    # SIMILAR_TO edge discovery
    # ------------------------------------------------------------------

    def _discover_similar_edges(
        self,
        store: GraphStore,
        tbl: Any,
        chunk_ids: list[str],
        chunk_vecs: Any,
        *,
        k: int,
        threshold: float,
        max_degree: int = 0,
        quiet: bool,
        flush_every: int = 1000,
        block_size: int = 512,
    ) -> int:
        """Find semantically similar chunk pairs and write SIMILAR_TO edges.

        A blocked NumPy matmul rather than one vector query per chunk.
        Since all chunk vectors are L2-normalised by the embedder
        (``normalize_embeddings=True``), cosine similarity equals the dot
        product, so one BLAS SGEMM call per block gives exact similarities
        with no per-query round-trip overhead.

        The ``(block_size × n_chunks)`` sims matrix is clamped adaptively to
        stay under ~256 MB regardless of corpus size (e.g. block_size auto-
        clamps to 128 for a 500 k-chunk corpus at 384-d).

        Pairs above *threshold* are emitted as undirected SIMILAR_TO edges
        (canonicalized as (lo_id, hi_id) where ``lo_id < hi_id``
        lexicographically).  The SQLite PRIMARY KEY on (src, rel, dst)
        deduplicates the symmetric pairs that arise from processing both
        directions of each edge.

        When *max_degree* > 0 the scan collects candidates first, then
        enforces a hard per-node cap with a greedy high-similarity selection
        pass.

        :param store: GraphStore to write edges into.
        :param tbl: Accepted for call-site compatibility; not used.
        :param chunk_ids: Chunk node IDs in the same order as *chunk_vecs*.
        :param chunk_vecs: Float32 ndarray of shape ``(n_chunks, dim)``.
                           Must be L2-normalised (sentence-transformers with
                           ``normalize_embeddings=True`` guarantees this).
        :param k: Maximum SIMILAR_TO out-edges per source chunk (0 = unlimited).
        :param threshold: Minimum cosine similarity for a SIMILAR_TO edge (0–1).
        :param max_degree: Cap total SIMILAR_TO edges per node (0 = unlimited).
        :param quiet: Suppress progress output.
        :param flush_every: Flush accumulated edges to SQLite after this many
            (ignored when *max_degree* > 0 — writes are deferred until pruning).
        :param block_size: Source rows per matmul block before adaptive clamping.
        :return: Total number of edges added.
        """
        import heapq  # pylint: disable=import-outside-toplevel

        import numpy as np  # pylint: disable=import-outside-toplevel

        from doc_kg.dockg import DocEdge  # pylint: disable=import-outside-toplevel

        if not chunk_ids:
            return 0

        n_chunks = len(chunk_ids)

        # Contiguous float32 is required for BLAS SGEMM.
        X = np.ascontiguousarray(chunk_vecs, dtype=np.float32)

        # Clamp block_size so the (B × N) sims matrix stays under ~256 MB.
        _bytes_per_row = n_chunks * 4
        eff_block = max(64, min(block_size, (256 * 1024 * 1024) // max(_bytes_per_row, 1)))

        # k=0 means no cap — include all neighbours above threshold.
        eff_k = min(k, n_chunks - 1) if k > 0 else n_chunks - 1

        edges: list[DocEdge] = []
        total_edges = 0

        # Per-node degree cap: {node_id: min-heap of (sim, lo_id, hi_id)}
        # Each heap keeps the top-max_degree edges by similarity for that node.
        node_heap: dict[str, list] = {} if max_degree > 0 else {}

        if not quiet:
            from rich.progress import (  # pylint: disable=import-outside-toplevel
                BarColumn,
                MofNCompleteColumn,
                Progress,
                SpinnerColumn,
                TextColumn,
                TimeElapsedColumn,
                TimeRemainingColumn,
            )

            _sim_ctx: contextlib.AbstractContextManager = Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                TimeElapsedColumn(),
                TimeRemainingColumn(),
            )
        else:
            _sim_ctx = contextlib.nullcontext()

        with _sim_ctx as sim_prog:
            sim_task = (
                sim_prog.add_task("  SIMILAR_TO scan", total=n_chunks)
                if sim_prog is not None
                else None
            )

            for block_start in range(0, n_chunks, eff_block):
                block_end = min(block_start + eff_block, n_chunks)

                # (B, dim) @ (dim, N) → (B, N) exact cosine similarities via BLAS.
                sims = X[block_start:block_end] @ X.T

                for i in range(block_end - block_start):
                    src_idx = block_start + i
                    src_id = chunk_ids[src_idx]
                    row = sims[i]

                    row[src_idx] = -1.0  # exclude self-match

                    # All neighbours at or above the threshold.
                    (above,) = np.where(row >= threshold)
                    if not above.size:
                        continue

                    # Keep top-eff_k by similarity (argpartition: O(N), not O(N log N)).
                    if above.size > eff_k:
                        top_idx = np.argpartition(row[above], -eff_k)[-eff_k:]
                        above = above[top_idx]

                    for j in above.tolist():
                        sim = float(row[j])
                        dst_id = chunk_ids[j]
                        lo_id, hi_id = (src_id, dst_id) if src_id < dst_id else (dst_id, src_id)

                        if max_degree > 0:
                            entry = (sim, lo_id, hi_id)
                            for nid in (lo_id, hi_id):
                                h = node_heap.setdefault(nid, [])
                                heapq.heappush(h, entry)
                                if len(h) > max_degree:
                                    heapq.heappop(h)  # drop weakest
                        else:
                            edges.append(
                                DocEdge(
                                    src=lo_id,
                                    rel="SIMILAR_TO",
                                    dst=hi_id,
                                    evidence={"similarity": round(sim, 4)},
                                )
                            )
                            if len(edges) >= flush_every:
                                store._upsert_edges(edges)
                                total_edges += len(edges)
                                edges = []

                del sims  # release block memory before next allocation

                if sim_prog is not None and sim_task is not None:
                    sim_prog.advance(sim_task, block_end - block_start)

        if max_degree > 0:
            # Candidate set: union of per-node top-max_degree heaps.
            candidates: dict[tuple[str, str], float] = {}
            for heap in node_heap.values():
                for sim, lo, hi in heap:
                    key = (lo, hi)
                    if key not in candidates or sim > candidates[key]:
                        candidates[key] = sim

            # Hard cap selection: highest-similarity edges first while both
            # endpoints still have degree budget available.
            degree: dict[str, int] = {}
            selected: list[DocEdge] = []
            ordered = sorted(candidates.items(), key=lambda item: item[1], reverse=True)
            for (lo, hi), sim in ordered:
                if degree.get(lo, 0) >= max_degree or degree.get(hi, 0) >= max_degree:
                    continue
                selected.append(
                    DocEdge(
                        src=lo,
                        rel="SIMILAR_TO",
                        dst=hi,
                        evidence={"similarity": round(sim, 4)},
                    )
                )
                degree[lo] = degree.get(lo, 0) + 1
                degree[hi] = degree.get(hi, 0) + 1

            edges = selected

        if edges:
            store._upsert_edges(edges)
            total_edges += len(edges)

        return total_edges

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(self, query: str, k: int = 8, *, where: str | None = None) -> list[SeedHit]:
        """Semantic vector search.

        :param query: Natural-language query string.
        :param k: Number of results to return.
        :param where: Optional SQL filter applied as a *prefilter* (evaluated
            before the vector search, so the ``k`` nearest are drawn from the
            matching subset rather than filtered afterwards).  Built against the
            metadata columns ``file_path`` and ``kind``.  sqlite-vec compiles it
            to a ``rowid IN (SELECT rowid FROM vec_meta WHERE <where>)`` subquery.
        :return: List of :class:`SeedHit` ordered by ascending distance.
        """
        backend = self._get_backend()
        qvec = self.embedder.embed_query(query)
        raw = backend.search(qvec, k, where=where)

        hits: list[SeedHit] = []
        for rank, row in enumerate(raw):
            dist = _extract_distance(row, rank)
            hits.append(
                SeedHit(
                    id=row["id"],
                    kind=row.get("kind", ""),
                    name=row.get("name", ""),
                    title=row.get("title", ""),
                    file_path=row.get("file_path", ""),
                    distance=dist,
                    rank=rank,
                )
            )
        return hits

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _read_nodes(self, store: GraphStore) -> list[dict]:
        return store.query_nodes(kinds=list(self.index_kinds))

    def __repr__(self) -> str:
        return f"SemanticIndex(vectors_path={self.vectors_path!r}, embedder={self.embedder!r})"


# ---------------------------------------------------------------------------
# Vector store
# ---------------------------------------------------------------------------


def sqlite_backend(vectors_path: str | Path, *, dim: int, dtype: str = "float") -> SqliteVecBackend:
    """The sqlite-vec store DocKG keeps its vectors in, with DocKG's metadata columns.

    Replaced ``make_backend()`` in 0.29.0, when LanceDB support was removed and
    there was no backend left to choose.

    :param vectors_path: The ``vectors.sqlite`` file.
    :param dim: Embedding dimensionality.
    :param dtype: ``"float"`` or ``"int8"``.
    :return: An unopened :class:`~kg_utils.vector_backend.SqliteVecBackend`.
    """
    return SqliteVecBackend(vectors_path, dim=dim, meta_columns=_META_COLUMNS, dtype=dtype)


# ---------------------------------------------------------------------------
# Internal utilities
# ---------------------------------------------------------------------------


def _build_index_text(n: dict) -> str:
    """Build the canonical text document used for embedding a node.

    :param n: Node dict with keys ``kind``, ``name``, ``title``, ``file_path``,
              ``char_start``, and optionally ``text``.
    :return: Newline-joined string suitable for embedding.
    """
    parts = [f"KIND: {n['kind']}"]
    if n.get("title"):
        parts.append(f"TITLE: {n['title']}")
    elif n.get("name"):
        parts.append(f"NAME: {n['name']}")
    if n.get("file_path"):
        parts.append(f"FILE: {n['file_path']}")
    if n.get("text"):
        parts.append("TEXT:\n" + n["text"].strip()[:1024])
    return "\n".join(parts)


def _extract_distance(row: dict, fallback_rank: int) -> float:
    """Extract a distance value from a vector-backend result row."""
    for key in ("_distance", "distance"):
        if key in row and row[key] is not None:
            return float(row[key])
    if "score" in row and row["score"] is not None:
        return 1.0 / (1.0 + float(row["score"]))
    return float(fallback_rank)
