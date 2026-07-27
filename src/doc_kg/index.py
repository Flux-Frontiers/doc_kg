#!/usr/bin/env python3
"""
index.py

SemanticIndex — LanceDB vector index for DocKG.

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
from kg_utils.vector_backend import LanceDBBackend, SqliteVecBackend, VectorBackend
from rich.console import Console

if TYPE_CHECKING:
    from doc_kg.store import GraphStore

# Metadata columns DocKG persists per vector (id + these). Filterable in the
# sqlite backend's ``where`` prefilter; carried through LanceDB rows too.
_META_COLUMNS = ("kind", "name", "title", "file_path")


# ---------------------------------------------------------------------------
# Logging / progress suppression
# ---------------------------------------------------------------------------


def suppress_ingestion_logging() -> None:
    """Suppress verbose progress output during model loading and ingestion."""
    for name in ("sentence_transformers", "transformers", "huggingface_hub", "lancedb"):
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

_DEFAULT_TABLE = "dockg_nodes"
_DEFAULT_KINDS = ("document", "section", "chunk", "topic", "entity", "keyword")

# ---------------------------------------------------------------------------
# Approximate-nearest-neighbour (IVF) index configuration
# ---------------------------------------------------------------------------
# DocKG defaults to an exact flat cosine scan, which is optimal for small
# corpora (sub-millisecond, exact).  Past ``_ANN_THRESHOLD`` rows the scan cost
# grows linearly and an IVF index pays off (measured: ~64 ms flat at 683k rows
# vs single-digit ms indexed).  The index is built automatically at the end of
# a build and consumed transparently by ``search`` — both gated on row count so
# small corpora are never touched.  All knobs are overridable via env so a
# large-corpus build (e.g. the gutenberg bundle) can tune without code changes.
#
# Index type — measured on the 683k-vector gutenberg-all bundle (384-d):
#   IVF_FLAT (default) — keeps full vectors; exact within probed cells, so it's
#     literally the flat scan partitioned.  On real text queries, fidelity to the
#     exact top-10 is 0.91 with 94% top-1 retention at nprobes=50 (the default),
#     vs 0.83 / 81% at nprobes=20 — hence nprobes defaults to 50.  ``refine_factor``
#     is a no-op for FLAT (full vectors already), so it defaults to 0 to avoid a
#     pointless latency tax.  Costs ~1 GB index on disk at this scale.
#   IVF_PQ — ~60× smaller index (product-quantized), but lossy: needs
#     ``refine_factor`` >= 10 to recover recall (0.60 → 0.90 @ nprobes=20).
#     Switch to it (and set DOCKG_ANN_REFINE_FACTOR) only at multi-million
#     scale or under disk pressure.
_ANN_THRESHOLD = int(os.environ.get("DOCKG_ANN_THRESHOLD", "50000"))
_ANN_INDEX_TYPE = os.environ.get("DOCKG_ANN_INDEX_TYPE", "IVF_FLAT")
_ANN_NPROBES = int(os.environ.get("DOCKG_ANN_NPROBES", "50"))
_ANN_REFINE_FACTOR = int(os.environ.get("DOCKG_ANN_REFINE_FACTOR", "0"))


def _is_jsonl_cache(path: Path) -> bool:
    return path.suffix == ".jsonl" or path.name.endswith(".jsonl.gz")


def _open_text_auto(path: Path, mode: str) -> TextIO:
    if path.suffix == ".gz":
        return cast(TextIO, gzip.open(path, mode, encoding="utf-8"))
    return cast(TextIO, open(path, mode, encoding="utf-8"))


class SemanticIndex:
    """LanceDB-backed semantic vector index for DocKG.

    Reads nodes from a :class:`~doc_kg.store.GraphStore`, embeds them, and
    stores the vectors in LanceDB.  The index is **derived and disposable** —
    it can be rebuilt from SQLite at any time without data loss.

    After building the vector index, optionally runs a SIMILAR_TO edge
    discovery pass that writes semantic similarity edges back to the store.

    Example::

        embedder = SentenceTransformerEmbedder()
        idx = SemanticIndex("./lancedb", embedder=embedder)
        idx.build(store, wipe=True)

        hits = idx.search("climate change policy", k=8)
        for h in hits:
            print(h.id, h.distance)

    :param lancedb_dir: Directory for the LanceDB database.
    :param embedder: Embedding backend.
    :param table: LanceDB table name.
    :param index_kinds: Node kinds to embed.
    """

    def __init__(
        self,
        lancedb_dir: str | Path,
        *,
        embedder: Embedder | None = None,
        table: str = _DEFAULT_TABLE,
        index_kinds: Sequence[str] = _DEFAULT_KINDS,
        ann_threshold: int = _ANN_THRESHOLD,
        ann_index_type: str = _ANN_INDEX_TYPE,
        ann_nprobes: int = _ANN_NPROBES,
        ann_refine_factor: int = _ANN_REFINE_FACTOR,
        backend: VectorBackend | None = None,
    ) -> None:
        self.lancedb_dir = Path(lancedb_dir)
        self.embedder: Embedder = embedder or SentenceTransformerEmbedder()
        self.table_name = table
        self.index_kinds = tuple(index_kinds)
        # ANN index policy (see module-level _ANN_* constants).  ``ann_threshold``
        # <= 0 disables IVF entirely (always exact flat scan).  ANN applies only
        # to the LanceDB backend; the sqlite-vec backend is always exact.
        self.ann_threshold = int(ann_threshold)
        self.ann_index_type = str(ann_index_type)
        self.ann_nprobes = int(ann_nprobes)
        self.ann_refine_factor = int(ann_refine_factor)
        # Vector store backend (LanceDB by default, constructed lazily so the
        # embedder's ``dim`` — which may load the model — is only touched on use).
        self._backend: VectorBackend | None = backend

    # ------------------------------------------------------------------
    # Backend
    # ------------------------------------------------------------------

    def _get_backend(self) -> VectorBackend:
        """Return the vector backend, constructing the default LanceDB one lazily.

        The default preserves DocKG's historical behaviour: a LanceDB store at
        :attr:`lancedb_dir` with the same ANN gating policy. Pass a
        :class:`~kg_utils.vector_backend.SqliteVecBackend` (via ``backend=`` or a
        ``vector_backend`` config key upstream) for the exact sqlite-vec store.
        """
        if self._backend is None:
            self._backend = LanceDBBackend(
                self.lancedb_dir,
                table=self.table_name,
                dim=self.embedder.dim,
                meta_columns=_META_COLUMNS,
                ann_threshold=self.ann_threshold,
                ann_nprobes=self.ann_nprobes,
                ann_refine_factor=self.ann_refine_factor,
                ann_index_type=self.ann_index_type,
            )
        return self._backend

    def _lance_table(self) -> Any:
        """The underlying LanceDB table if the backend is LanceDB, else ``None``.

        Used only for LanceDB-specific ingest telemetry / compaction, which are
        no-ops on the sqlite-vec backend.
        """
        backend = self._get_backend()
        return backend._table() if isinstance(backend, LanceDBBackend) else None

    def _finalize_backend(self, *, quiet: bool) -> None:
        """Post-ingest steps: LanceDB compaction + ANN index (no-ops on sqlite)."""
        backend = self._get_backend()
        if not isinstance(backend, LanceDBBackend):
            return
        tbl = backend._table()
        # Avoid synchronous compaction in the hot ingest loop; do it once here.
        with contextlib.suppress(Exception):
            stats = tbl.stats()
            frag_stats = stats.get("fragment_stats", {}) if isinstance(stats, dict) else {}
            if int(frag_stats.get("num_fragments", 0) or 0) >= 256:
                tbl.compact_files()
        # Build the IVF index now that all rows are loaded (no-op below threshold).
        backend.maybe_create_ann_index(quiet=quiet)

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
        :param batch_size: LanceDB write batch size.
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
        lance_tbl = self._lance_table()  # None on sqlite-vec

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
                # Buffer multiple encode batches so LanceDB gets fewer, larger fragments.
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
                            frags = small = None
                            if lance_tbl is not None:
                                stats = lance_tbl.stats()
                                if isinstance(stats, dict):
                                    frag_stats = stats.get("fragment_stats", {})
                                    frags = frag_stats.get("num_fragments")
                                    small = frag_stats.get("num_small_fragments")
                                else:
                                    frag_stats = getattr(stats, "fragment_stats", None)
                                    frags = getattr(frag_stats, "num_fragments", None)
                                    small = getattr(frag_stats, "num_small_fragments", None)
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
                                f"fragments={frags} small={small} "
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

        # LanceDB compaction (if fragmented) + IVF index build; no-op on sqlite-vec.
        self._finalize_backend(quiet=quiet)

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
            "table": self.table_name,
            "lancedb_dir": str(self.lancedb_dir),
            "kinds": list(self.index_kinds),
            "similar_edges_added": similar_edges_added,
        }

    # ------------------------------------------------------------------
    # Two-phase build: precompute → cache file → LanceDB
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

        Pure embedding pass — no LanceDB writes.  Call :meth:`build_from_cache`
        afterwards to populate the vector index from the saved file.

        :param store: Source :class:`~doc_kg.store.GraphStore`.
        :param out: Output path for the cache JSON.
        :param n_workers: Worker processes for embedding (default: CPU count / 2).
        :param batch_size: Per-worker embedding batch size.
        :param device: Embedding device (``"cpu"``/``"mps"``/``"cuda"``); ``None``
            resolves via ``KG_EMBED_DEVICE`` then auto-detect.  GPU devices force
            single-process embedding (see :class:`~doc_kg.embedder_worker.CorpusEmbedder`).
        :param only_missing: Incremental embedding — skip nodes whose ``id`` is already
            present in the LanceDB table, so only new/changed nodes are embedded.
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

        :param only_missing: Skip nodes whose ``id`` is already in the LanceDB
            table (incremental embedding). No-op when the table is absent.
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
        """Build (or rebuild) the LanceDB index from a pre-computed embedding cache.

        Skips the model-inference pass entirely — loads float32 vectors from
        *cache_path* and writes them straight to LanceDB.  The cache must have
        been produced by :meth:`precompute_embeddings`.

        :param store: :class:`~doc_kg.store.GraphStore` (needed for SIMILAR_TO writes).
        :param cache_path: Path to the :class:`~doc_kg.embedder_worker.EmbeddingCache` JSON.
        :param wipe: If ``True``, delete all existing vectors first.
        :param batch_size: LanceDB write batch size.
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

        # LanceDB compaction + IVF index; no-op on sqlite-vec.
        self._finalize_backend(quiet=quiet)

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
            "table": self.table_name,
            "lancedb_dir": str(self.lancedb_dir),
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
        """Build LanceDB index from streaming JSONL cache without loading all rows in RAM."""
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

        # LanceDB compaction + IVF index; no-op on sqlite-vec.
        self._finalize_backend(quiet=quiet)

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
            "table": self.table_name,
            "lancedb_dir": str(self.lancedb_dir),
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

        Replaces the per-chunk LanceDB ANN loop with a blocked NumPy matmul.
        Since all chunk vectors are L2-normalised by the embedder
        (``normalize_embeddings=True``), cosine similarity equals the dot
        product, so one BLAS SGEMM call per block gives exact similarities
        with no per-query Python↔LanceDB round-trip overhead.

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
            metadata columns ``file_path`` and ``kind``.  Valid on both backends:
            LanceDB evaluates it as a prefilter; sqlite-vec compiles it to a
            ``rowid IN (SELECT rowid FROM vec_meta WHERE <where>)`` subquery.
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
        return (
            f"SemanticIndex(lancedb_dir={self.lancedb_dir!r}, "
            f"table={self.table_name!r}, embedder={self.embedder!r})"
        )


# ---------------------------------------------------------------------------
# Backend factory
# ---------------------------------------------------------------------------

_SQLITE_ALIASES = frozenset({"sqlite", "sqlite-vec", "sqlite_vec", "sqlitevec", "vec0"})
_LANCE_ALIASES = frozenset({"lancedb", "lance"})
_AUTO_ALIASES = frozenset({"auto", ""})


def resolve_backend_name(
    vector_backend: str | None,
    *,
    lancedb_dir: str | Path,
    vectors_path: str | Path | None = None,
) -> str:
    """Resolve ``"auto"`` (the default) to a concrete backend by what exists.

    ``auto`` prefers an existing ``vectors.sqlite`` sidecar; else an existing
    LanceDB store (don't silently change an un-migrated corpus's store type);
    else sqlite-vec for a fresh build (migration-forward). Concrete names pass
    through unchanged.

    :param vector_backend: ``"auto"`` / ``None`` / ``"lancedb"`` / ``"sqlite-vec"``.
    :param lancedb_dir: LanceDB directory (also locates the sqlite sidecar).
    :param vectors_path: Explicit sqlite path override.
    :return: ``"lancedb"`` or ``"sqlite-vec"``.
    """
    key = (vector_backend or "auto").strip().lower()
    if key not in _AUTO_ALIASES:
        return key
    vpath = Path(vectors_path) if vectors_path else sqlite_vectors_path(lancedb_dir)
    if vpath.exists():
        return "sqlite-vec"
    if Path(lancedb_dir).exists():
        return "lancedb"
    return "sqlite-vec"


def sqlite_vectors_path(lancedb_dir: str | Path) -> Path:
    """Derive the sidecar ``vectors.sqlite`` path next to ``graph.sqlite``.

    DocKG's LanceDB store lives at ``<store>/.dockg/lancedb``; the sqlite-vec
    sidecar sits alongside it at ``<store>/.dockg/vectors.sqlite``.

    :param lancedb_dir: The LanceDB directory (``.../.dockg/lancedb``).
    :return: ``.../.dockg/vectors.sqlite``.
    """
    return Path(lancedb_dir).parent / "vectors.sqlite"


def make_backend(
    vector_backend: str,
    *,
    lancedb_dir: str | Path,
    dim: int,
    table: str = _DEFAULT_TABLE,
    vectors_path: str | Path | None = None,
    ann_threshold: int = _ANN_THRESHOLD,
    ann_nprobes: int = _ANN_NPROBES,
    ann_refine_factor: int = _ANN_REFINE_FACTOR,
    ann_index_type: str = _ANN_INDEX_TYPE,
    dtype: str = "float",
) -> VectorBackend:
    """Construct a :class:`~kg_utils.vector_backend.VectorBackend` by name.

    :param vector_backend: ``"lancedb"`` (default) or ``"sqlite-vec"``.
    :param lancedb_dir: LanceDB directory; also used to derive the sqlite sidecar.
    :param dim: Embedding dimensionality.
    :param table: LanceDB table name (ignored by the sqlite backend).
    :param vectors_path: Explicit ``vectors.sqlite`` path (sqlite only); defaults
        to :func:`sqlite_vectors_path`.
    :param vector_backend: ``"auto"`` (default), ``"lancedb"``, or ``"sqlite-vec"``.
    :param dtype: ``"float"`` or ``"int8"`` (sqlite only).
    :raises ValueError: On an unknown backend name.
    """
    key = resolve_backend_name(vector_backend, lancedb_dir=lancedb_dir, vectors_path=vectors_path)
    if key in _SQLITE_ALIASES:
        path = Path(vectors_path) if vectors_path else sqlite_vectors_path(lancedb_dir)
        return SqliteVecBackend(path, dim=dim, meta_columns=_META_COLUMNS, dtype=dtype)
    if key in _LANCE_ALIASES:
        return LanceDBBackend(
            lancedb_dir,
            table=table,
            dim=dim,
            meta_columns=_META_COLUMNS,
            ann_threshold=ann_threshold,
            ann_nprobes=ann_nprobes,
            ann_refine_factor=ann_refine_factor,
            ann_index_type=ann_index_type,
        )
    raise ValueError(
        f"unknown vector_backend {vector_backend!r} (expected 'lancedb' or 'sqlite-vec')"
    )


# ---------------------------------------------------------------------------
# LanceDB → sqlite-vec conversion (no re-embedding)
# ---------------------------------------------------------------------------


def convert_lancedb_to_sqlite(
    lancedb_dir: str | Path,
    *,
    table: str = _DEFAULT_TABLE,
    vectors_path: str | Path | None = None,
    dtype: str = "float",
    wipe: bool = True,
    batch_size: int = 5000,
    validate: bool = True,
    quiet: bool = False,
) -> dict[str, Any]:
    """Convert an existing LanceDB vector table into a ``vectors.sqlite`` store.

    Reads ``id``/``kind``/``name``/``title``/``file_path``/``vector`` straight
    out of LanceDB (the ``text`` embed-blob is intentionally dropped — hydration
    comes from the authoritative SQLite GraphStore) and writes them to a
    :class:`~kg_utils.vector_backend.SqliteVecBackend`.  No model is loaded and
    no re-embedding happens.

    :param lancedb_dir: The source LanceDB directory.
    :param table: Source table name.
    :param vectors_path: Destination sqlite path (default: sidecar next to it).
    :param dtype: ``"float"`` (fp32) or ``"int8"`` (3× smaller; assumes unit-norm).
    :param wipe: Drop any existing destination store first.
    :param validate: Verify row count and re-read 5 random vectors (cosine ≥ 0.9999).
    :param quiet: Suppress the summary line.
    :return: Stats dict ``{converted, dim, dtype, vectors_path, validated}``.
    :raises FileNotFoundError: If the source table is absent.
    :raises RuntimeError: If validation fails.
    """
    import lancedb  # pylint: disable=import-outside-toplevel
    import numpy as np  # pylint: disable=import-outside-toplevel

    lancedb_dir = Path(lancedb_dir)
    db = lancedb.connect(str(lancedb_dir))
    if table not in db.list_tables().tables:
        raise FileNotFoundError(f"LanceDB table {table!r} not found in {lancedb_dir}")
    tbl = db.open_table(table)
    # Project only the columns we persist — never load the big ``text`` blob.
    # ``columns=`` exists on newer LanceDB; on versions whose ``to_arrow()`` lacks
    # it we fall back to a full read (TypeError). The ty stub tracks the older
    # signature, hence the suppression.
    wanted = ["id", *[c for c in _META_COLUMNS if c != "id"], "vector"]
    try:
        arrow = tbl.to_arrow(columns=wanted)  # ty: ignore[unknown-argument]
    except TypeError:
        arrow = tbl.to_arrow()

    ids = arrow.column("id").to_pylist()
    cols = {c: arrow.column(c).to_pylist() for c in _META_COLUMNS if c in arrow.column_names}
    vectors = np.asarray(arrow.column("vector").to_pylist(), dtype=np.float32)

    # Drop the bootstrap dummy row if it lingers.
    keep = [i for i, nid in enumerate(ids) if nid and nid != "__dummy__"]
    ids = [ids[i] for i in keep]
    vectors = vectors[keep]
    for c in cols:
        cols[c] = [cols[c][i] for i in keep]

    dim = int(vectors.shape[1]) if vectors.size else 0
    dest = Path(vectors_path) if vectors_path else sqlite_vectors_path(lancedb_dir)
    backend = SqliteVecBackend(dest, dim=dim, meta_columns=_META_COLUMNS, dtype=dtype)
    backend.open(wipe=wipe)

    rows = [
        {
            "id": ids[i],
            **{c: (cols.get(c) or [None] * len(ids))[i] or "" for c in _META_COLUMNS},
            "vector": vectors[i],
        }
        for i in range(len(ids))
    ]
    converted = backend.upsert(rows, batch_size=batch_size)

    validated = False
    if validate:
        if backend.count() != len(ids):
            raise RuntimeError(f"row-count mismatch: source {len(ids)} vs sqlite {backend.count()}")
        # Re-read a handful of vectors and confirm cosine ≈ 1.0 vs the source.
        # (int8 quantization loosens the tolerance.)
        tol = 0.999 if dtype == "int8" else 0.9999
        step = max(1, len(ids) // 5)
        sample = list(range(0, len(ids), step))[:5]
        for idx_i in sample:
            src = vectors[idx_i]
            hits = backend.search(src.tolist(), 1)
            if not hits or hits[0]["id"] != ids[idx_i]:
                raise RuntimeError(f"self-query did not return {ids[idx_i]!r}")
            sim = 1.0 - float(hits[0]["_distance"])
            if sim < tol:
                raise RuntimeError(
                    f"vector {ids[idx_i]!r} cosine {sim:.5f} < {tol} after conversion"
                )
        validated = True

    if not quiet:
        Console().print(
            f"  converted {converted:,} vectors → {dest} "
            f"(dim={dim}, dtype={dtype}, validated={validated})"
        )
    return {
        "converted": converted,
        "dim": dim,
        "dtype": dtype,
        "vectors_path": str(dest),
        "validated": validated,
    }


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
    """Extract a distance value from a LanceDB result row."""
    for key in ("_distance", "distance"):
        if key in row and row[key] is not None:
            return float(row[key])
    if "score" in row and row["score"] is not None:
        return 1.0 / (1.0 + float(row["score"]))
    return float(fallback_rank)
