#!/usr/bin/env python3
"""
index.py

SemanticIndex — LanceDB vector index for DocKG.

Mirrors CodeKG's index.py with the following additions:

1. Default model is a general-text embedding model (all-mpnet-base-v2)
   instead of a code-specific model.

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

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from doc_kg.dockg import DEFAULT_MODEL

if TYPE_CHECKING:
    from doc_kg.store import GraphStore

# ---------------------------------------------------------------------------
# Local model cache (same logic as CodeKG)
# ---------------------------------------------------------------------------


def _local_model_path(model_name: str) -> Path:
    """Return the local cache path for *model_name*.

    Defaults to ``.dockg/models/<model>`` under the current working directory.
    Override via the ``DOCKG_MODEL_DIR`` environment variable.

    :param model_name: HuggingFace model identifier.
    :return: Absolute :class:`~pathlib.Path` to the cached model directory.
    """
    import os  # pylint: disable=import-outside-toplevel

    default = str(Path.cwd() / ".dockg" / "models")
    cache_root = Path(os.environ.get("DOCKG_MODEL_DIR", default))
    safe_name = model_name.replace("/", "--")
    return cache_root / safe_name


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


# ---------------------------------------------------------------------------
# Embedder interface (identical to CodeKG — pluggable)
# ---------------------------------------------------------------------------


class Embedder:
    """Abstract embedding backend.

    :param dim: Embedding dimension (must be set by subclass ``__init__``).
    """

    dim: int

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of strings.

        :param texts: Input strings.
        :return: List of float32 vectors, one per input.
        """
        raise NotImplementedError

    def embed_query(self, query: str) -> list[float]:
        """Embed a single query string.

        :param query: Query string.
        :return: Float32 vector.
        """
        return self.embed_texts([query])[0]


class SentenceTransformerEmbedder(Embedder):
    """Local embedding via ``sentence-transformers``.

    Defaults to ``all-mpnet-base-v2`` — a strong general-text sentence model
    (768 dimensions).  Swap for ``BAAI/bge-small-en-v1.5`` or any
    other HuggingFace model by changing ``DEFAULT_MODEL`` or setting the
    ``DOCKG_MODEL`` environment variable.

    :param model_name: HuggingFace model name or local path.
    """

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        from sentence_transformers import (  # pylint: disable=import-outside-toplevel
            SentenceTransformer,
        )

        local_path = _local_model_path(model_name)
        if local_path.exists():
            self.model = SentenceTransformer(str(local_path))
        else:
            try:
                self.model = SentenceTransformer(model_name, local_files_only=True)
            except OSError:
                self.model = SentenceTransformer(model_name)
        self.model_name = model_name
        self.dim: int = self.model.get_sentence_embedding_dimension() or 384

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of strings into float32 vectors."""
        import numpy as np  # pylint: disable=import-outside-toplevel

        vecs = self.model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return [np.asarray(v, dtype="float32").tolist() for v in vecs]

    def embed_query(self, query: str) -> list[float]:
        """Embed a single query string into a float32 vector."""
        import numpy as np  # pylint: disable=import-outside-toplevel

        vec = self.model.encode([query], normalize_embeddings=True)[0]
        return np.asarray(vec, dtype="float32").tolist()

    def __repr__(self) -> str:
        return f"SentenceTransformerEmbedder(model={self.model_name!r}, dim={self.dim})"


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
        quiet: bool = True,
        discover_similar: bool = True,
        similar_k: int = 5,
        similarity_edge_threshold: float = 0.85,
    ) -> dict:
        """Build (or rebuild) the vector index from *store*.

        After indexing, optionally discovers SIMILAR_TO edges between
        semantically close chunk nodes and writes them back to *store*.

        :param store: Authoritative :class:`~doc_kg.store.GraphStore`.
        :param wipe: If ``True``, delete all existing vectors first.
        :param batch_size: Number of nodes to embed per batch.
        :param quiet: Suppress progress output.
        :param discover_similar: If ``True``, run SIMILAR_TO edge discovery.
        :param similar_k: k-nearest neighbors to examine per chunk.
        :param similarity_edge_threshold: Minimum cosine similarity to emit a
                                          SIMILAR_TO edge (0–1).
        :return: Stats dict.
        """
        if quiet:
            suppress_ingestion_logging()

        nodes = self._read_nodes(store)
        tbl = self._open_table(wipe=wipe)

        indexed = 0
        # Keep vectors in memory for SIMILAR_TO pass
        all_ids: list[str] = []
        all_vecs: list[list[float]] = []

        for i in range(0, len(nodes), batch_size):
            chunk = nodes[i : i + batch_size]
            texts = [_build_index_text(n) for n in chunk]
            vecs = self.embedder.embed_texts(texts)

            ids = [n["id"] for n in chunk]
            if ids:
                pred = " OR ".join([f"id = '{_escape(nid)}'" for nid in ids])
                tbl.delete(pred)

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
                for n, text, vec in zip(chunk, texts, vecs)
            ]
            tbl.add(rows)
            indexed += len(rows)
            all_ids.extend(ids)
            all_vecs.extend(vecs)

        self._tbl = tbl

        # SIMILAR_TO edge discovery
        similar_edges_added = 0
        if discover_similar and all_vecs:
            similar_edges_added = self._discover_similar_edges(
                store,
                all_ids,
                all_vecs,
                k=similar_k,
                threshold=similarity_edge_threshold,
                quiet=quiet,
            )

        return {
            "indexed_rows": indexed,
            "dim": self.embedder.dim,
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
        vecs: list[list[float]],
        *,
        k: int,
        threshold: float,
        quiet: bool,  # pylint: disable=unused-argument
    ) -> int:
        """Find semantically similar chunk pairs and write SIMILAR_TO edges.

        Only chunk nodes participate in SIMILAR_TO (sections and documents
        are already structurally connected via CONTAINS).

        :param store: GraphStore to write edges into.
        :param node_ids: Node IDs in the same order as *vecs*.
        :param vecs: Embedding vectors for each node.
        :param k: k-nearest neighbors to examine.
        :param threshold: Minimum cosine similarity for an edge.
        :param quiet: Suppress progress output.
        :return: Number of edges added.
        """
        from doc_kg.dockg import DocEdge  # pylint: disable=import-outside-toplevel

        # Only chunk nodes get SIMILAR_TO edges
        chunk_indices = [i for i, nid in enumerate(node_ids) if nid.startswith("chunk:")]
        if not chunk_indices:
            return 0

        import numpy as np  # pylint: disable=import-outside-toplevel

        chunk_ids = [node_ids[i] for i in chunk_indices]
        chunk_vecs = np.asarray([vecs[i] for i in chunk_indices], dtype="float32")

        # Cosine similarity matrix (chunked to avoid OOM on large corpora)
        edges: list[DocEdge] = []
        seen: set[frozenset] = set()

        tbl = self._tbl
        if tbl is None:
            return 0

        for ci, (nid, qvec) in enumerate(zip(chunk_ids, chunk_vecs)):
            raw = tbl.search(qvec.tolist()).limit(k + 1).to_list()
            for row in raw:
                candidate = row["id"]
                if candidate == nid:
                    continue
                if not candidate.startswith("chunk:"):
                    continue
                pair = frozenset([nid, candidate])
                if pair in seen:
                    continue
                seen.add(pair)

                # Compute cosine similarity
                ci2 = chunk_ids.index(candidate) if candidate in chunk_ids else -1
                if ci2 == -1:
                    continue
                a, b = chunk_vecs[ci], chunk_vecs[ci2]
                na, nb = np.linalg.norm(a), np.linalg.norm(b)
                if na > 0 and nb > 0:
                    sim = float(np.dot(a, b) / (na * nb))
                else:
                    sim = 0.0

                if sim >= threshold:
                    edges.append(
                        DocEdge(
                            src=nid,
                            rel="SIMILAR_TO",
                            dst=candidate,
                            evidence={"similarity": round(sim, 4)},
                        )
                    )

        if edges:
            store._upsert_edges(edges)

        return len(edges)

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
        raw = tbl.search(qvec).limit(k).to_list()

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
