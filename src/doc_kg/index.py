#!/usr/bin/env python3
"""
index.py

SemanticIndex — LanceDB vector index for DocKG.

Mirrors CodeKG's index.py with the following additions:

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
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from kg_utils.embed import DEFAULT_MODEL
from kg_utils.embedder import Embedder, SentenceTransformerEmbedder

if TYPE_CHECKING:
    from doc_kg.store import GraphStore


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
    ) -> None:
        self.lancedb_dir = Path(lancedb_dir)
        self.embedder: Embedder = embedder or SentenceTransformerEmbedder()
        self.table_name = table
        self.index_kinds = tuple(index_kinds)
        self._tbl = None

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(
        self,
        store: GraphStore,
        *,
        wipe: bool = False,
        batch_size: int = 256,
        encode_batch_size: int = 1024,
        quiet: bool = False,
        discover_similar: bool = True,
        similar_k: int = 5,
        similarity_edge_threshold: float = 0.85,
    ) -> dict:
        """Build (or rebuild) the vector index from *store*.

        After indexing, optionally discovers SIMILAR_TO edges between
        semantically close chunk nodes and writes them back to *store*.

        :param store: Authoritative :class:`~doc_kg.store.GraphStore`.
        :param wipe: If ``True``, delete all existing vectors first.
        :param batch_size: LanceDB write batch size.
        :param encode_batch_size: Tokens fed to ``model.encode()`` per GPU call.
                                   Larger values improve MPS/CUDA utilisation
                                   (default 1024; tune down if OOM).
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

        nodes = self._read_nodes(store)
        if not quiet:
            from rich.console import Console  # pylint: disable=import-outside-toplevel

            Console().print(f"  nodes    : {len(nodes):,} to embed")
        tbl = self._open_table(wipe=wipe)

        indexed = 0
        all_ids: list[str] = []
        # Only pre-allocate the contiguous float32 matrix when SIMILAR_TO discovery
        # is requested — for large corpora (1 M+ nodes × 768 dim × 4 B ≈ 3 GB)
        # the allocation alone causes SIGBUS on macOS when skipping similarity.
        all_vecs_np = (
            np.zeros((len(nodes), self.embedder.dim), dtype=np.float32)
            if discover_similar
            else None
        )

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
            task_id = prog.add_task("  Embedding", total=len(nodes)) if prog is not None else None
            for i in range(0, len(nodes), encode_batch_size):
                enc_nodes = nodes[i : i + encode_batch_size]
                enc_texts = [_build_index_text(n) for n in enc_nodes]
                enc_vecs = self.embedder.embed_texts(enc_texts)
                enc_arr = np.asarray(enc_vecs, dtype=np.float32)
                if all_vecs_np is not None:
                    all_vecs_np[i : i + len(enc_nodes)] = enc_arr

                ids = [n["id"] for n in enc_nodes]

                # On wipe builds the table starts empty — skip delete to avoid
                # scanning growing fragment list (1650+ fragments → O(n²) slowdown).
                # On incremental builds, delete stale rows before re-adding.
                if not wipe:
                    pred = " OR ".join([f"id = '{_escape(nid)}'" for nid in ids])
                    tbl.delete(pred)

                # Write the whole encode batch as one LanceDB fragment (not 256-row slices)
                # — fewer fragments = faster subsequent scans.
                rows = [
                    {
                        "id": n["id"],
                        "kind": n["kind"],
                        "name": n["name"],
                        "title": n.get("title") or "",
                        "file_path": n.get("file_path") or "",
                        "text": text,
                        "vector": vec.tolist(),
                    }
                    for n, text, vec in zip(enc_nodes, enc_texts, enc_arr)
                ]
                tbl.add(rows)
                indexed += len(rows)
                all_ids.extend(ids)
                if prog is not None and task_id is not None:
                    prog.advance(task_id, len(enc_nodes))

        self._tbl = tbl

        # SIMILAR_TO edge discovery
        similar_edges_added = 0
        if discover_similar and all_vecs_np is not None and len(all_ids) > 0:
            similar_edges_added = self._discover_similar_edges(
                store,
                all_ids,
                all_vecs_np,
                k=similar_k,
                threshold=similarity_edge_threshold,
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

    def precompute_embeddings(
        self,
        store: GraphStore,
        out: Path,
        *,
        n_workers: int | None = None,
        batch_size: int = 64,
        quiet: bool = False,
    ) -> Path:
        """Embed all index nodes and save to an :class:`~doc_kg.embedder_worker.EmbeddingCache` JSON.

        Pure embedding pass — no LanceDB writes.  Call :meth:`build_from_cache`
        afterwards to populate the vector index from the saved file.

        :param store: Source :class:`~doc_kg.store.GraphStore`.
        :param out: Output path for the cache JSON.
        :param n_workers: Worker processes for embedding (default: CPU count / 2).
        :param batch_size: Per-worker embedding batch size.
        :param quiet: Suppress progress output.
        :return: Path to the saved cache file (*out*).
        """
        from doc_kg.embedder_worker import (  # pylint: disable=import-outside-toplevel
            CorpusEmbedder,
        )

        if quiet:
            suppress_ingestion_logging()

        nodes = self._read_nodes(store)
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

        model_name = getattr(self.embedder, "model_name", DEFAULT_MODEL)
        corp_embedder = CorpusEmbedder(
            model_name=model_name,
            n_workers=n_workers,
            batch_size=batch_size,
        )

        if not quiet:
            from rich.console import Console  # pylint: disable=import-outside-toplevel

            Console().print(
                f"  nodes    : {len(nodes):,} to embed  ({corp_embedder.n_workers} workers)"
            )

        cache = corp_embedder.embed(texts, metadata)
        CorpusEmbedder.save_cache(cache, out)

        if not quiet:
            from rich.console import Console  # pylint: disable=import-outside-toplevel

            Console().print(f"  cache    : {out}  ({cache.n_vectors:,} vectors, dim={cache.dim})")

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

        tbl = self._open_table(wipe=wipe)

        indexed = 0
        all_ids: list[str] = []
        all_vecs_np = np.zeros((cache.n_vectors, cache.dim), dtype=np.float32)

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
                all_vecs_np[i : i + len(batch_meta)] = vec_arr

                ids = [m["id"] for m in batch_meta]
                if not wipe:
                    pred = " OR ".join([f"id = '{_escape(nid)}'" for nid in ids])
                    tbl.delete(pred)

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
                tbl.add(rows)
                indexed += len(rows)
                all_ids.extend(ids)
                if prog is not None and task_id is not None:
                    prog.advance(task_id, len(batch_meta))

        self._tbl = tbl

        import sys  # pylint: disable=import-outside-toplevel

        print(
            f"DEBUG: indexed={indexed}, all_ids={len(all_ids)}, discover={discover_similar}",
            flush=True,
            file=sys.stderr,
        )

        similar_edges_added = 0
        if discover_similar and all_ids:
            similar_edges_added = self._discover_similar_edges(
                store,
                all_ids,
                all_vecs_np,
                k=similar_k,
                threshold=similarity_edge_threshold,
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

    # ------------------------------------------------------------------
    # SIMILAR_TO edge discovery
    # ------------------------------------------------------------------

    def _discover_similar_edges(
        self,
        store: GraphStore,
        node_ids: list[str],
        vecs: Any,
        *,
        k: int,
        threshold: float,
        quiet: bool,
        row_batch: int = 1024,
        flush_every: int = 1000,
    ) -> int:
        """Find semantically similar chunk pairs and write SIMILAR_TO edges.

        Only chunk nodes participate in SIMILAR_TO (sections and documents
        are already structurally connected via CONTAINS).

        Uses batched numpy matmul — no LanceDB queries, no ``seen`` set.
        Deduplication is handled by enforcing ``src_global_idx < dst_global_idx``
        (upper-triangle only), which is a pure numpy mask operation and
        guarantees each pair appears exactly once across all batches.

        Edges are flushed to SQLite every *flush_every* entries to bound peak
        memory regardless of how many qualifying pairs exist.

        :param store: GraphStore to write edges into.
        :param node_ids: Node IDs in the same order as *vecs*.
        :param vecs: Float32 numpy array of shape ``(N, dim)``.
        :param k: Unused (kept for API compatibility).
        :param threshold: Minimum cosine similarity for a SIMILAR_TO edge.
        :param quiet: Suppress progress output.
        :param row_batch: Matmul row-batch size to bound peak memory.
                          1024 rows × 20 K cols × 4 B ≈ 80 MB per batch.
        :param flush_every: Flush accumulated edges to SQLite after this many.
        :return: Total number of edges added.
        """
        import numpy as np  # pylint: disable=import-outside-toplevel

        from doc_kg.dockg import DocEdge  # pylint: disable=import-outside-toplevel

        chunk_indices = [i for i, nid in enumerate(node_ids) if nid.startswith("chunk:")]
        if not chunk_indices:
            return 0

        chunk_ids = [node_ids[i] for i in chunk_indices]
        chunk_vecs = vecs[chunk_indices]  # direct numpy slice — no copy
        n_chunks = len(chunk_ids)
        n_batches = (n_chunks + row_batch - 1) // row_batch

        edges: list[DocEdge] = []
        total_edges = 0

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
                sim_prog.add_task("  SIMILAR_TO scan", total=n_batches)
                if sim_prog is not None
                else None
            )

            for batch_start in range(0, n_chunks, row_batch):
                batch_end = min(batch_start + row_batch, n_chunks)
                sims = chunk_vecs[batch_start:batch_end] @ chunk_vecs.T

                # All pairs above threshold
                row_idxs, col_idxs = np.where(sims >= threshold)

                # Upper-triangle filter: src_global < dst_global
                # — eliminates self-pairs and ensures each pair appears once
                # across all batches without a Python seen-set.
                src_global = batch_start + row_idxs
                mask = src_global < col_idxs
                if mask.any():
                    filt_ri = row_idxs[mask]  # local row indices into sims
                    filt_ci = col_idxs[mask]  # global col indices
                    filt_src = src_global[mask]  # global src indices
                    sim_vals = sims[filt_ri, filt_ci]

                    for i in range(len(filt_src)):
                        edges.append(
                            DocEdge(
                                src=chunk_ids[filt_src[i]],
                                rel="SIMILAR_TO",
                                dst=chunk_ids[filt_ci[i]],
                                evidence={"similarity": round(float(sim_vals[i]), 4)},
                            )
                        )

                    # Flush to SQLite periodically — bounds peak memory
                    if len(edges) >= flush_every:
                        store._upsert_edges(edges)
                        total_edges += len(edges)
                        edges = []
                if sim_prog is not None and sim_task is not None:
                    sim_prog.advance(sim_task, 1)

        # Final flush
        if edges:
            store._upsert_edges(edges)
            total_edges += len(edges)

        return total_edges

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(self, query: str, k: int = 8) -> list[SeedHit]:
        """Semantic vector search.

        :param query: Natural-language query string.
        :param k: Number of results to return.
        :return: List of :class:`SeedHit` ordered by ascending distance.
        """
        tbl = self._get_table()
        qvec = self.embedder.embed_query(query)
        raw = tbl.search(qvec).metric("cosine").limit(k).to_list()

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

    def _open_table(self, *, wipe: bool = False):
        import lancedb  # pylint: disable=import-outside-toplevel

        self.lancedb_dir.mkdir(parents=True, exist_ok=True)
        db = lancedb.connect(str(self.lancedb_dir))  # type: ignore[attr-defined]

        if self.table_name in db.list_tables().tables:
            if wipe:
                db.drop_table(self.table_name)
            else:
                return db.open_table(self.table_name)

        import numpy as np  # pylint: disable=import-outside-toplevel

        dummy = {
            "id": "__dummy__",
            "kind": "dummy",
            "name": "__dummy__",
            "title": "",
            "file_path": "",
            "text": "__dummy__",
            "vector": np.zeros((self.embedder.dim,), dtype="float32").tolist(),
        }
        tbl = db.create_table(self.table_name, data=[dummy])
        tbl.delete("id = '__dummy__'")
        return tbl

    def _get_table(self):
        if self._tbl is None:
            import lancedb  # pylint: disable=import-outside-toplevel

            db = lancedb.connect(str(self.lancedb_dir))  # type: ignore[attr-defined]
            self._tbl = db.open_table(self.table_name)
        return self._tbl

    def __repr__(self) -> str:
        return (
            f"SemanticIndex(lancedb_dir={self.lancedb_dir!r}, "
            f"table={self.table_name!r}, embedder={self.embedder!r})"
        )


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


def _escape(s: str) -> str:
    """Escape single quotes for use in LanceDB delete predicates."""
    return s.replace("'", "''")
