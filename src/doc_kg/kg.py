#!/usr/bin/env python3
"""
kg.py

DocKG — top-level orchestrator for the Document Knowledge Graph.

Mirrors the role of CodeKG in the code_kg project.

Owns the full pipeline:
    corpus → DocGraph → GraphStore → SemanticIndex → QueryResult / TextPack

Also defines the structured result types:
    BuildStats, QueryResult, TextPack

Author: Eric G. Suchanek, PhD
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.metadata import version as _pkg_version
from pathlib import Path
from typing import Any

from doc_kg.dockg import DEFAULT_MODEL
from doc_kg.graph import DocGraph
from doc_kg.index import Embedder, SemanticIndex, SentenceTransformerEmbedder
from doc_kg.store import DEFAULT_RELS, GraphStore, ProvMeta

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class BuildStats:
    """Statistics returned by :meth:`DocKG.build`.

    :param corpus_root: Corpus root that was analysed.
    :param db_path: Path to the SQLite database.
    :param total_nodes: Total nodes written to SQLite.
    :param total_edges: Total edges written to SQLite.
    :param node_counts: Node counts broken down by kind.
    :param edge_counts: Edge counts broken down by relation.
    :param indexed_rows: Number of nodes embedded into LanceDB (None if not built).
    :param index_dim: Embedding dimension (None if not built).
    :param similar_edges_added: Number of SIMILAR_TO edges discovered.
    """

    corpus_root: str
    db_path: str
    total_nodes: int
    total_edges: int
    node_counts: dict[str, int]
    edge_counts: dict[str, int]
    indexed_rows: int | None = None
    index_dim: int | None = None
    similar_edges_added: int | None = None

    def to_dict(self) -> dict:
        """Serialise build stats to a JSON-compatible dictionary."""
        return {
            "corpus_root": self.corpus_root,
            "db_path": self.db_path,
            "total_nodes": self.total_nodes,
            "total_edges": self.total_edges,
            "node_counts": self.node_counts,
            "edge_counts": self.edge_counts,
            "indexed_rows": self.indexed_rows,
            "index_dim": self.index_dim,
            "similar_edges_added": self.similar_edges_added,
        }

    def __str__(self) -> str:
        lines = [
            f"corpus_root      : {self.corpus_root}",
            f"db_path          : {self.db_path}",
            f"nodes            : {self.total_nodes}  {self.node_counts}",
            f"edges            : {self.total_edges}  {self.edge_counts}",
        ]
        if self.indexed_rows is not None:
            lines.append(f"indexed          : {self.indexed_rows} vectors  dim={self.index_dim}")
        if self.similar_edges_added is not None:
            lines.append(f"SIMILAR_TO edges : {self.similar_edges_added}")
        return "\n".join(lines)


@dataclass
class QueryResult:
    """Result of a hybrid query (:meth:`DocKG.query`).

    :param query: Original query string.
    :param seeds: Number of semantic seed nodes.
    :param expanded_nodes: Total nodes after graph expansion.
    :param returned_nodes: Nodes returned after filtering.
    :param hop: Hop count used.
    :param rels: Edge relations used for expansion.
    :param nodes: List of node dicts (sorted by rank).  Each node includes a
        ``relevance`` dict with keys ``score`` (float in [0, 1], higher =
        more relevant), ``dist`` (raw cosine distance), ``hop`` (graph hops
        from nearest seed), and ``semantic_boost``.
    :param edges: List of edge dicts within the returned node set.
    """

    query: str
    seeds: int
    expanded_nodes: int
    returned_nodes: int
    hop: int
    rels: list[str]
    nodes: list[dict]
    edges: list[dict]

    def to_dict(self) -> dict:
        """Serialise the query result to a JSON-compatible dictionary."""
        return {
            "query": self.query,
            "seeds": self.seeds,
            "expanded_nodes": self.expanded_nodes,
            "returned_nodes": self.returned_nodes,
            "hop": self.hop,
            "rels": self.rels,
            "nodes": self.nodes,
            "edges": self.edges,
        }

    def to_json(self, *, indent: int = 2) -> str:
        """Serialise the query result to a JSON string."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def print_summary(self) -> None:
        """Print a human-readable summary of the query result to stdout."""
        sep = "=" * 80
        print(sep)
        print(f"QUERY: {self.query}")
        print(
            f"Seeds: {self.seeds} | Expanded: {self.expanded_nodes} "
            f"| Returned: {self.returned_nodes} | hop={self.hop}"
        )
        print(f"Rels: {', '.join(self.rels)}")
        print(sep)
        for n in self.nodes:
            kind_label = f"[{n['kind']}]"
            title = n.get("title") or n.get("name") or n["id"]
            fp = n.get("file_path") or ""
            print(f"{kind_label:12s} {fp:40s} {title}")
            if n.get("text"):
                preview = n["text"].strip().splitlines()[0][:120]
                print(f"    {preview}")
            print()
        print("-" * 80)
        print(f"EDGES (within returned set): {len(self.edges)}")
        print("-" * 80)
        for e in sorted(self.edges, key=lambda x: (x["rel"], x["src"], x["dst"])):
            print(f"  {e['src']} -[{e['rel']}]-> {e['dst']}")
        print(sep)


@dataclass
class TextPack:
    """Result of :meth:`DocKG.pack` — nodes with attached text excerpts.

    Mirrors CodeKG's SnippetPack for document text.

    :param query: Original query string.
    :param seeds: Number of semantic seed nodes.
    :param expanded_nodes: Total nodes after graph expansion.
    :param returned_nodes: Nodes returned after deduplication.
    :param hop: Hop count used.
    :param rels: Edge relations used for expansion.
    :param model: Embedding model name.
    :param nodes: Node dicts, each optionally containing an ``excerpt`` key.
    :param edges: Edge dicts within the returned node set.
    """

    query: str
    seeds: int
    expanded_nodes: int
    returned_nodes: int
    hop: int
    rels: list[str]
    model: str
    nodes: list[dict]
    edges: list[dict]

    def to_dict(self) -> dict:
        """Serialise the pack result to a JSON-compatible dictionary."""
        return {
            "query": self.query,
            "seeds": self.seeds,
            "expanded_nodes": self.expanded_nodes,
            "returned_nodes": self.returned_nodes,
            "hop": self.hop,
            "rels": self.rels,
            "model": self.model,
            "nodes": self.nodes,
            "edges": self.edges,
        }

    def to_json(self, *, indent: int = 2) -> str:
        """Serialise the pack result to a JSON string."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def to_markdown(self) -> str:
        """Render the text pack as a Markdown context document."""
        out: list[str] = []
        out.append("# DocKG Text Pack\n")
        out.append(f"**Query:** `{self.query}`  ")
        out.append(f"**Seeds:** {self.seeds}  ")
        out.append(f"**Expanded nodes:** {self.expanded_nodes} (returned: {self.returned_nodes})  ")
        out.append(f"**hop:** {self.hop}  ")
        out.append(f"**rels:** {', '.join(self.rels)}  ")
        out.append(f"**model:** {self.model}  ")
        out.append("\n---\n")
        out.append("## Nodes\n")

        for n in self.nodes:
            title = n.get("title") or n.get("name") or n["id"]
            out.append(f"### {n['kind']} — `{title}`")
            out.append(f"- id: `{n['id']}`")
            if n.get("file_path"):
                out.append(f"- file: `{n['file_path']}`")
            if n.get("char_start") is not None:
                out.append(f"- offset: {n['char_start']}–{n['char_end']}")
            excerpt = n.get("excerpt") or n.get("text")
            if excerpt:
                out.append("")
                out.append(f"```\n{excerpt.strip()}\n```")
            out.append("")

        out.append("\n---\n")
        out.append("## Edges\n")
        for e in self.edges:
            out.append(f"- `{e['src']}` -[{e['rel']}]-> `{e['dst']}`")
        out.append("")
        return "\n".join(out)

    def save(self, path: str | Path, *, fmt: str = "md") -> None:
        """Write the pack to a file.

        :param path: Output file path.
        :param fmt: ``"md"`` for Markdown or ``"json"`` for JSON.
        """
        text = self.to_markdown() if fmt == "md" else self.to_json()
        Path(path).write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Priority for node ranking (lower = higher priority)
# ---------------------------------------------------------------------------

_KIND_PRIORITY = {"chunk": 0, "section": 1, "document": 2}

# Weighted relation priorities for semantic ranking.
# Intentionally favors topical/entity grounding over weak lexical co-occurrence.
_REL_RANK_WEIGHTS: dict[str, float] = {
    "HAS_TOPIC": 3.0,
    "MENTIONS_ENTITY": 2.5,
    "HAS_KEYWORD": 1.0,
    "SIMILAR_TO": 0.8,
    "REFERENCES": 0.5,
    "CONTAINS": 0.2,
    "NEXT": 0.1,
    "CO_OCCURS_WITH": 0.05,
}


_MIN_CHUNK_CHARS = 50  # micro-fragments below this are noise, not factual asides


def _short_chunk_boost(node: dict, *, threshold: int = 200) -> float:
    """Return a boost for short chunk nodes to surface factual asides.

    Single-sentence factual asides (< *threshold* chars) get a positive boost
    so they rank ahead of same-hop nodes whose embeddings are diluted by longer,
    topically mixed context.  Non-chunk nodes and micro-fragments are unaffected.

    :param node: Node dict with optional ``text`` and ``kind`` keys.
    :param threshold: Character length below which the boost is applied.
    :return: Boost value in [0.0, 1.5].
    """
    if node.get("kind") != "chunk":
        return 0.0
    text = node.get("text") or ""
    if not text:
        return 0.0
    n = len(text)
    if n < _MIN_CHUNK_CHARS or n >= threshold:
        return 0.0
    # Linear scale: 200 chars → 0.0 boost, 50 chars → ~1.1 boost
    return round(1.5 * (1.0 - n / threshold), 4)


def _semantic_rank_boost(node_id: str, edges: list[dict]) -> float:
    """Compute weighted semantic connectivity score for a node.

    Lower-confidence structural relations receive small weights while
    semantic grounding relations (topic/entity) dominate rank impact.

    :param node_id: Node id to score.
    :param edges: Edge dicts with ``src``, ``dst``, and ``rel`` keys.
    :return: Non-negative rank boost score.
    """
    score = 0.0
    for e in edges:
        if e.get("src") != node_id and e.get("dst") != node_id:
            continue
        rel = e.get("rel", "")
        score += _REL_RANK_WEIGHTS.get(rel, 0.0)
    return round(score, 4)


# ---------------------------------------------------------------------------
# DocKG — orchestrator
# ---------------------------------------------------------------------------


class DocKG:
    """Top-level orchestrator for the Document Knowledge Graph.

    Owns and coordinates all four layers:

    * :class:`~doc_kg.graph.DocGraph` — corpus parsing and chunking
    * :class:`~doc_kg.store.GraphStore` — SQLite persistence
    * :class:`~doc_kg.index.SemanticIndex` — LanceDB vector index
    * Query / text-packing logic

    Typical usage::

        kg = DocKG(corpus_root="/path/to/docs")
        stats = kg.build(wipe=True)
        print(stats)

        result = kg.query("how does authentication work?", k=8, hop=1)
        result.print_summary()

        pack = kg.pack("configuration options", k=8, hop=1)
        pack.save("context.md")

    :param corpus_root: Corpus root directory.
    :param db_path: SQLite database path.
    :param lancedb_dir: LanceDB directory.
    :param model: Sentence-transformer model name.
    :param table: LanceDB table name.
    :param chunk_strategy: ``"semantic"`` (default), ``"sentence_group"``, or ``"fixed"``.
    :param sentences_per_chunk: Sentences per chunk for the ``sentence_group`` strategy.
    :param chunk_size: Approximate max characters per chunk.
    :param chunk_overlap: Character overlap between chunks.
    :param similarity_threshold: Semantic split threshold for chunker.
    :param enable_topics: Emit topic nodes and HAS_TOPIC edges.
    :param enable_entities: Emit entity nodes and MENTIONS_ENTITY edges.
    :param enable_keywords: Emit keyword nodes and HAS_KEYWORD edges.
    :param emit_cooccur: Emit CO_OCCURS_WITH edges among semantic nodes (default: False;
                         noisy and dense; use MemoryKG for semantic memory instead).
    :param cooccur_window: Co-occurrence window metadata.
    :param topic_threshold: Topic confidence threshold.
    :param topics_file: Optional topic catalog file (JSON/YAML).
    :param embedder: Optional embedding backend.  When provided, pre-sets ``_embedder``
                     so the lazy-init never fires ``SentenceTransformerEmbedder``.
                     Defaults to ``None`` (preserves existing behaviour).
    """

    def __init__(
        self,
        corpus_root: str | Path,
        db_path: str | Path | None = None,
        lancedb_dir: str | Path | None = None,
        *,
        model: str = DEFAULT_MODEL,
        table: str = "dockg_nodes",
        chunk_strategy: str = "semantic",
        sentences_per_chunk: int = 4,
        chunk_size: int = 512,
        chunk_overlap: int = 64,
        similarity_threshold: float = 0.75,
        enable_topics: bool = True,
        enable_entities: bool = True,
        enable_keywords: bool = True,
        emit_cooccur: bool = False,
        cooccur_window: int = 1,
        topic_threshold: float = 0.2,
        topics_file: str | None = None,
        exclude: set[str] | None = None,
        embedder: Embedder | None = None,
    ) -> None:
        self.corpus_root = Path(corpus_root).resolve()
        self.exclude: set[str] = exclude or set()
        self.db_path = (
            Path(db_path) if db_path is not None else self.corpus_root / ".dockg" / "graph.sqlite"
        )
        self.lancedb_dir = (
            Path(lancedb_dir)
            if lancedb_dir is not None
            else self.corpus_root / ".dockg" / "lancedb"
        )
        self.model_name = model
        self.table_name = table
        self.chunk_strategy = chunk_strategy
        self.sentences_per_chunk = sentences_per_chunk
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.similarity_threshold = similarity_threshold
        self.enable_topics = enable_topics
        self.enable_entities = enable_entities
        self.enable_keywords = enable_keywords
        self.emit_cooccur = emit_cooccur
        self.cooccur_window = cooccur_window
        self.topic_threshold = topic_threshold
        self.topics_file = topics_file

        # Lazy-initialised layers
        self._graph: DocGraph | None = None
        self._store: GraphStore | None = None
        self._index: SemanticIndex | None = None
        self._embedder: Embedder | None = embedder

    # ------------------------------------------------------------------
    # Layer accessors (lazy init)
    # ------------------------------------------------------------------

    @property
    def graph(self) -> DocGraph:
        """Corpus parsing layer (lazy)."""
        if self._graph is None:
            self._graph = DocGraph(
                self.corpus_root,
                exclude=self.exclude or None,
                chunk_strategy=self.chunk_strategy,
                sentences_per_chunk=self.sentences_per_chunk,
                chunk_size=self.chunk_size,
                chunk_overlap=self.chunk_overlap,
                similarity_threshold=self.similarity_threshold,
                enable_topics=self.enable_topics,
                enable_entities=self.enable_entities,
                enable_keywords=self.enable_keywords,
                emit_cooccur=self.emit_cooccur,
                cooccur_window=self.cooccur_window,
                topic_threshold=self.topic_threshold,
                topics_file=self.topics_file,
            )
        return self._graph

    @property
    def store(self) -> GraphStore:
        """SQLite persistence layer (lazy)."""
        if self._store is None:
            self._store = GraphStore(self.db_path)
        return self._store

    @property
    def embedder(self) -> Embedder:
        """Embedding backend (lazy)."""
        if self._embedder is None:
            self._embedder = SentenceTransformerEmbedder(self.model_name)
        return self._embedder

    @property
    def index(self) -> SemanticIndex:
        """LanceDB semantic index (lazy)."""
        if self._index is None:
            self._index = SemanticIndex(
                self.lancedb_dir,
                embedder=self.embedder,
                table=self.table_name,
            )
        return self._index

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self, *, wipe: bool = False, discover_similar: bool = True) -> BuildStats:
        """Full pipeline: corpus parsing → SQLite → LanceDB + SIMILAR_TO edges.

        :param wipe: Clear existing data before writing.
        :param discover_similar: Run SIMILAR_TO edge discovery after indexing.
        :return: :class:`BuildStats`.
        """
        graph_stats = self.build_graph(wipe=wipe)
        index_stats = self.build_index(wipe=wipe, discover_similar=discover_similar)
        graph_stats.indexed_rows = index_stats.indexed_rows
        graph_stats.index_dim = index_stats.index_dim
        graph_stats.similar_edges_added = index_stats.similar_edges_added
        return graph_stats

    def build_graph(self, *, wipe: bool = False) -> BuildStats:
        """Corpus parsing → SQLite only.

        :param wipe: Clear existing graph before writing.
        :return: :class:`BuildStats` (``indexed_rows`` will be ``None``).
        """
        nodes, edges = self.graph.extract(force=wipe).result()
        self.store.write(nodes, edges, wipe=wipe, quiet=False)
        self.store.stamp_meta("doc_kg", _pkg_version("doc_kg"))
        s = self.store.stats()
        return BuildStats(
            corpus_root=str(self.corpus_root),
            db_path=str(self.db_path),
            total_nodes=s["total_nodes"],
            total_edges=s["total_edges"],
            node_counts=s["node_counts"],
            edge_counts=s["edge_counts"],
        )

    def build_embeddings(
        self,
        out: Path | str | None = None,
        *,
        n_workers: int | None = None,
        batch_size: int = 64,
        quiet: bool = False,
    ) -> Path:
        """Embed all nodes and save to a JSON cache file (no LanceDB writes).

        The graph must already exist — run :meth:`build_graph` first.

        :param out: Output path for the embedding cache JSON.
                    Defaults to ``<db_path parent>/embeddings.json``.
        :param n_workers: Worker processes (default: CPU count / 2).
        :param batch_size: Per-worker embedding batch size.
        :param quiet: Suppress progress output.
        :return: Path to the saved cache file.
        """
        if out is None:
            out = self.db_path.parent / "embeddings.json"
        return self.index.precompute_embeddings(
            self.store,
            Path(out),
            n_workers=n_workers,
            batch_size=batch_size,
            quiet=quiet,
        )

    def build_index_from_cache(
        self,
        cache_path: Path | str,
        *,
        wipe: bool = False,
        discover_similar: bool = True,
    ) -> BuildStats:
        """Build the LanceDB index from a pre-computed embedding cache.

        Skips the model inference pass — loads vectors from *cache_path* directly.
        Use :meth:`build_embeddings` to produce the cache.

        :param cache_path: Path to the embedding cache JSON.
        :param wipe: Delete existing vectors before indexing.
        :param discover_similar: Run SIMILAR_TO edge discovery after indexing.
        :return: :class:`BuildStats`.
        """
        idx_stats = self.index.build_from_cache(
            self.store, Path(cache_path), wipe=wipe, discover_similar=discover_similar
        )
        s = self.store.stats()
        return BuildStats(
            corpus_root=str(self.corpus_root),
            db_path=str(self.db_path),
            total_nodes=s["total_nodes"],
            total_edges=s["total_edges"],
            node_counts=s["node_counts"],
            edge_counts=s["edge_counts"],
            indexed_rows=idx_stats["indexed_rows"],
            index_dim=idx_stats["dim"],
            similar_edges_added=idx_stats.get("similar_edges_added"),
        )

    def build_index(self, *, wipe: bool = False, discover_similar: bool = True) -> BuildStats:
        """SQLite → LanceDB only (graph must already exist).

        :param wipe: Delete existing vectors before indexing.
        :param discover_similar: Run SIMILAR_TO edge discovery after indexing.
        :return: :class:`BuildStats` with ``indexed_rows``, ``index_dim``, and
                 ``similar_edges_added`` set.
        """
        from rich.console import Console  # pylint: disable=import-outside-toplevel

        with Console().status("  Loading embedding model\u2026"):
            _ = self.embedder  # warm up: loads SentenceTransformer weights
        idx_stats = self.index.build(self.store, wipe=wipe, discover_similar=discover_similar)
        s = self.store.stats()
        return BuildStats(
            corpus_root=str(self.corpus_root),
            db_path=str(self.db_path),
            total_nodes=s["total_nodes"],
            total_edges=s["total_edges"],
            node_counts=s["node_counts"],
            edge_counts=s["edge_counts"],
            indexed_rows=idx_stats["indexed_rows"],
            index_dim=idx_stats["dim"],
            similar_edges_added=idx_stats.get("similar_edges_added"),
        )

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def query(
        self,
        q: str,
        *,
        k: int = 8,
        hop: int = 1,
        rels: tuple[str, ...] = DEFAULT_RELS,
        max_nodes: int = 25,
    ) -> QueryResult:
        """Hybrid query: semantic seeding + structural expansion.

        :param q: Natural-language query.
        :param k: Top-K semantic hits.
        :param hop: Graph expansion hops.
        :param rels: Edge types to expand.
        :param max_nodes: Maximum nodes to return.
        :return: :class:`QueryResult`.
        """
        hits = self.index.search(q, k=k)
        seed_ids: set[str] = {h.id for h in hits}
        seed_rank: dict[str, dict] = {h.id: {"rank": h.rank, "dist": h.distance} for h in hits}

        meta = self.store.expand(seed_ids, hop=hop, rels=rels)
        all_ids = set(meta.keys())

        # Batch-fetch all expanded nodes in one query instead of N individual lookups.
        node_map = self.store.nodes_batch(all_ids)
        # Only fetch edges for the ranking-boost pass when the expanded set is small
        # enough to be practical.  For large corpora this JOIN dominates query time
        # while the hop+distance signal already handles ranking adequately.
        all_edges = self.store.edges_within(all_ids) if len(all_ids) <= max_nodes * 10 else []

        ranked_nodes: list[dict] = []
        for nid, n in node_map.items():
            prov: ProvMeta = meta[nid]
            base_dist = seed_rank.get(prov.via_seed, {"dist": 1e9})["dist"]
            kind_pri = _KIND_PRIORITY.get(n["kind"], 99)
            semantic_boost = _semantic_rank_boost(nid, all_edges)
            short_boost = _short_chunk_boost(n)
            seed_sim = max(0.0, round(1.0 - base_dist, 4))
            n["relevance"] = {
                "score": seed_sim,
                "dist": round(base_dist, 4),
                "hop": prov.best_hop,
                "semantic_boost": round(semantic_boost, 4),
            }
            n["_rank_key"] = (
                base_dist,
                prov.best_hop,
                -(semantic_boost + short_boost),
                kind_pri,
                n["id"],
            )
            ranked_nodes.append(n)

        ranked_nodes.sort(key=lambda x: x["_rank_key"])

        nodes: list[dict] = []
        kept_ids: set[str] = set()
        for n in ranked_nodes:
            if len(nodes) >= max_nodes:
                break
            kept_ids.add(n["id"])
            nodes.append(n)

        edges = self.store.edges_within(kept_ids)

        # Strip internal ranking keys from public output.
        for n in nodes:
            n.pop("_rank_key", None)

        return QueryResult(
            query=q,
            seeds=len(seed_ids),
            expanded_nodes=len(all_ids),
            returned_nodes=len(nodes),
            hop=hop,
            rels=list(rels),
            nodes=nodes,
            edges=edges,
        )

    # ------------------------------------------------------------------
    # Text pack
    # ------------------------------------------------------------------

    def pack(
        self,
        q: str,
        *,
        k: int = 8,
        hop: int = 1,
        rels: tuple[str, ...] = DEFAULT_RELS,
        max_chars: int = 2000,
        max_nodes: int | None = 15,
    ) -> TextPack:
        """Hybrid query + text excerpt extraction.

        :param q: Natural-language query.
        :param k: Top-K semantic hits.
        :param hop: Graph expansion hops.
        :param rels: Edge types to expand.
        :param max_chars: Maximum characters per text excerpt.
        :param max_nodes: Maximum nodes to return (``None`` for no limit).
        :return: :class:`TextPack`.
        """
        hits = self.index.search(q, k=k)
        seed_rank: dict[str, dict] = {h.id: {"rank": h.rank, "dist": h.distance} for h in hits}
        seed_ids: set[str] = set(seed_rank.keys())

        meta = self.store.expand(seed_ids, hop=hop, rels=rels)
        all_ids = set(meta.keys())

        # Batch-fetch all expanded nodes in one query instead of N individual lookups.
        node_map = self.store.nodes_batch(all_ids)
        all_edges = self.store.edges_within(all_ids)

        # Materialise + rank nodes
        raw_nodes: list[dict] = []
        for nid, n in node_map.items():
            prov: ProvMeta = meta[nid]
            base_dist = seed_rank.get(prov.via_seed, {"dist": 1e9})["dist"]
            kind_pri = _KIND_PRIORITY.get(n["kind"], 99)
            semantic_boost = _semantic_rank_boost(nid, all_edges)
            seed_sim = max(0.0, round(1.0 - base_dist, 4))
            n["relevance"] = {
                "score": seed_sim,
                "dist": round(base_dist, 4),
                "hop": prov.best_hop,
                "semantic_boost": round(semantic_boost, 4),
            }
            n["_rank_key"] = (
                base_dist,
                prov.best_hop,
                -semantic_boost,
                kind_pri,
                n["id"],
            )
            n["_best_hop"] = prov.best_hop
            raw_nodes.append(n)

        raw_nodes.sort(key=lambda x: x["_rank_key"])

        # Deduplicate: skip document/section nodes whose chunks are already included.
        # Chunks rank first (priority 0), so populate the seen set in a pre-pass.
        seen_files_with_chunks: set[str] = {
            n["file_path"] for n in raw_nodes if n["kind"] == "chunk" and n.get("file_path")
        }
        kept: list[dict] = []

        for n in raw_nodes:
            if max_nodes is not None and len(kept) >= max_nodes:
                break
            if (
                n["kind"] in ("document", "section")
                and n.get("file_path") in seen_files_with_chunks
            ):
                continue
            kept.append(n)

        kept_ids: set[str] = {n["id"] for n in kept}
        edges = self.store.edges_within(kept_ids)

        # Attach text excerpts
        for n in kept:
            raw_text = n.get("text") or ""
            if raw_text and len(raw_text) > max_chars:
                n["excerpt"] = raw_text[:max_chars] + "…"
            elif raw_text:
                n["excerpt"] = raw_text

        # Strip internal keys
        for n in kept:
            for key in [k for k in n if k.startswith("_")]:
                del n[key]

        return TextPack(
            query=q,
            seeds=len(seed_ids),
            expanded_nodes=len(all_ids),
            returned_nodes=len(kept),
            hop=hop,
            rels=list(rels),
            model=self.model_name,
            nodes=kept,
            edges=edges,
        )

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        """Return live statistics for this DocKG instance.

        Returns a flat dict conforming to the KGRAG adapter stats contract.
        All counts default to 0 on error so this method never raises.

        :return: Flat dict with ``node_count``, ``edge_count``, and
            per-kind counts: ``document_count``, ``chunk_count``,
            ``section_count``, ``topic_count``, ``entity_count``,
            ``keyword_count``.
        """
        try:
            s = self.store.stats()
            nc = s.get("node_counts", {})
            return {
                "node_count": s.get("total_nodes", 0),
                "edge_count": s.get("total_edges", 0),
                "document_count": nc.get("document", 0),
                "chunk_count": nc.get("chunk", 0),
                "section_count": nc.get("section", 0),
                "topic_count": nc.get("topic", 0),
                "entity_count": nc.get("entity", 0),
                "keyword_count": nc.get("keyword", 0),
            }
        except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            return {
                "node_count": 0,
                "edge_count": 0,
                "document_count": 0,
                "chunk_count": 0,
                "section_count": 0,
                "topic_count": 0,
                "entity_count": 0,
                "keyword_count": 0,
                "error": str(exc),
            }

    def node(self, node_id: str) -> dict | None:
        """Fetch a single node by ID from the store."""
        return self.store.node(node_id)

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        if self._store is not None:
            self._store.close()

    def __enter__(self) -> DocKG:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return (
            f"DocKG(corpus_root={self.corpus_root!r}, "
            f"db_path={self.db_path!r}, "
            f"lancedb_dir={self.lancedb_dir!r}, "
            f"model={self.model_name!r})"
        )
