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

import contextlib
import json
import os
from dataclasses import dataclass
from importlib.metadata import version as _pkg_version
from pathlib import Path
from typing import Any

from doc_kg.dockg import DEFAULT_MODEL
from doc_kg.graph import DocGraph
from doc_kg.index import Embedder, SemanticIndex, make_backend, make_embedder
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


# ---------------------------------------------------------------------------
# Provenance path tracing (traced pack)
# ---------------------------------------------------------------------------

# Human-readable label for the edge relation connecting two path steps.
_REL_LABELS = {
    "CONTAINS": "contains",
    "NEXT": "then",
    "REFERENCES": "links to",
    "SIMILAR_TO": "similar to",
    "HAS_TOPIC": "on topic",
    "MENTIONS_ENTITY": "mentions",
    "HAS_KEYWORD": "keyword",
    "CO_OCCURS_WITH": "co-occurs with",
}

_QUOTE_MAX_CHARS = 160


def _hop_label(rel: str, evidence: dict | None) -> str:
    """Return a human-readable label for an edge hop.

    :param rel: Edge relation type.
    :param evidence: Optional edge evidence dict (``similarity``, ``href``, …).
    :return: Label such as ``"similar to (0.91)"`` or ``"contains"``.
    """
    base = _REL_LABELS.get(rel, rel.lower().replace("_", " "))
    if evidence:
        if "similarity" in evidence:
            return f"{base} ({evidence['similarity']})"
        if "href" in evidence:
            return f"{base} ({evidence['href']})"
    return base


def _node_quote(node: dict) -> dict | None:
    """Return a one-line quote + citation for *node*, or ``None``.

    Chunk-like nodes are quoted from their source text (first sentence, capped);
    structural/semantic nodes fall back to their title/name.

    :param node: Node dict from the store.
    :return: ``{"text": str, "cite": str}`` or ``None`` when nothing to quote.
    """
    raw = (node.get("text") or "").strip()
    if raw:
        # First line/sentence, collapsed and capped.
        snippet = " ".join(raw.split())
        for sep in (". ", "! ", "? "):
            idx = snippet.find(sep)
            if 0 < idx < _QUOTE_MAX_CHARS:
                snippet = snippet[: idx + 1]
                break
        if len(snippet) > _QUOTE_MAX_CHARS:
            snippet = snippet[:_QUOTE_MAX_CHARS].rstrip() + "…"
        cite = node.get("file_path") or ""
        if cite and node.get("char_start") is not None:
            cite = f"{cite}:{node['char_start']}"
        return {"text": snippet, "cite": cite}
    return None


def _trace_paths(
    seed_ids: set[str],
    node_map: dict[str, dict],
    edges: list[dict],
    targets: set[str],
) -> dict[str, list[dict]]:
    """Reconstruct a shortest provenance path from a seed to each target node.

    Runs a multi-source breadth-first search from *seed_ids* over *edges*
    (treated as undirected, matching :meth:`GraphStore.expand`'s traversal), then
    walks parent pointers back to the nearest seed for every id in *targets*.

    :param seed_ids: Semantic seed node ids (BFS sources, hop 0).
    :param node_map: ``{id: node dict}`` for every expanded node.
    :param edges: Edge dicts (``src``, ``rel``, ``dst``, optional ``evidence``)
        spanning the expanded subgraph.
    :param targets: Node ids to build paths for (the returned/kept nodes).
    :return: ``{node_id: [step, …]}``; each step is a dict with keys ``id``,
        ``kind``, ``title``, ``rel``, ``label``, ``quote``.  Seeds map to a
        single-step path; unreachable targets are omitted.
    """
    # Undirected adjacency: neighbour -> connecting edge dict.
    adj: dict[str, list[tuple[str, dict]]] = {}
    for e in edges:
        adj.setdefault(e["src"], []).append((e["dst"], e))
        adj.setdefault(e["dst"], []).append((e["src"], e))

    # Multi-source BFS: record parent + the edge used to reach each node.
    parent: dict[str, str | None] = {}
    via_edge: dict[str, dict | None] = {}
    frontier: list[str] = []
    for sid in seed_ids:
        if sid in node_map:
            parent[sid] = None
            via_edge[sid] = None
            frontier.append(sid)

    while frontier:
        nxt: list[str] = []
        for nid in frontier:
            for neighbour, edge in adj.get(nid, ()):
                if neighbour in parent or neighbour not in node_map:
                    continue
                parent[neighbour] = nid
                via_edge[neighbour] = edge
                nxt.append(neighbour)
        frontier = nxt

    def _step(node_id: str, edge: dict | None) -> dict:
        node = node_map[node_id]
        rel = edge["rel"] if edge else None
        return {
            "id": node_id,
            "kind": node.get("kind"),
            "title": node.get("title") or node.get("name") or node_id,
            "rel": rel,
            "label": _hop_label(edge["rel"], edge.get("evidence")) if edge else None,
            "quote": _node_quote(node),
        }

    paths: dict[str, list[dict]] = {}
    for tid in targets:
        if tid not in parent:
            continue  # unreachable from any seed within the returned subgraph
        chain: list[dict] = []
        cur: str | None = tid
        while cur is not None:
            chain.append(_step(cur, via_edge[cur]))
            cur = parent[cur]
        chain.reverse()  # seed → … → target
        paths[tid] = chain
    return paths


def _render_path(path: list[dict]) -> str:
    """Render a provenance *path* as an indented Markdown block.

    :param path: List of step dicts from :func:`_trace_paths`.
    :return: Markdown string (arrow chain of titles + per-hop quotes).
    """
    arrow = " → ".join(f"`{s['title']}`" for s in path)
    lines = [f"- provenance: {arrow}"]
    for i, s in enumerate(path):
        prefix = "seed" if i == 0 else s["label"]
        quote = s.get("quote")
        if quote and quote["text"]:
            cite = f"  ({quote['cite']})" if quote.get("cite") else ""
            lines.append(f'    - {prefix}: "{quote["text"]}"{cite}')
        else:
            lines.append(f"    - {prefix}: `{s['title']}`")
    return "\n".join(lines)


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
    :param paths: Optional provenance map ``{node_id: [step, …]}`` populated when
        :meth:`DocKG.pack` is called with ``traced=True``.  Each step is a dict
        with keys ``id``, ``kind``, ``title``, ``rel`` (edge from the previous
        step, ``None`` for the seed), ``label`` (human-readable hop label), and
        ``quote`` (a one-line source excerpt with a ``cite`` file:offset tag).
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
    paths: dict[str, list[dict]] | None = None

    def to_dict(self) -> dict:
        """Serialise the pack result to a JSON-compatible dictionary."""
        d: dict[str, Any] = {
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
        if self.paths is not None:
            d["paths"] = self.paths
        return d

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
            path = (self.paths or {}).get(n["id"])
            if path:
                out.append("")
                out.append(_render_path(path))
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

# Reciprocal-rank-fusion constant for blending the dense (vector) and lexical
# (BM25) seed channels.  Larger -> flatter weighting across ranks.
_RRF_K = 60
# Synthetic cosine-distance assigned to seeds that surface only via the lexical
# channel (no dense vector rank), so downstream distance-based ranking can place
# them.  Must sit at or below the distance of a typical *good* dense hit
# (~0.4-0.5 for bge-small) but not far below it: smaller values let a single
# lexical seed's expansion neighbourhood evict every dense hit from the top-k
# (0.12 cost -14 pp recall@15 on the gutenberg_kg gold set; >=0.40 is plateau-
# optimal).  The per-rank step keeps lexical-only seeds ordered among themselves.
_LEXICAL_SEED_BASE_DIST = 0.45
_LEXICAL_SEED_STEP = 0.01


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


def _lance_where(
    file_prefixes: tuple[str, ...] | None,
    node_kinds: tuple[str, ...] | None,
) -> str | None:
    """Build a LanceDB SQL prefilter from scope constraints.

    Returns ``None`` when no constraints are given so callers can skip the
    ``where`` clause entirely.  String literals are single-quote-escaped; the
    only interpolated values are corpus-derived ``file_path`` prefixes and
    ``kind`` names, never user free-text.

    Prefixes are matched with ``starts_with()`` rather than ``LIKE`` so that
    ``%`` and ``_`` in a prefix match literally — the same semantics as the
    SQLite-side :func:`doc_kg.store._node_filter_sql` and the post-expansion
    :func:`_node_in_scope` guard.

    :param file_prefixes: ``file_path`` prefixes, OR-combined as ``starts_with``.
    :param node_kinds: Allowed ``kind`` values, IN-combined.
    :return: SQL filter string, or ``None`` if unconstrained.
    """
    clauses: list[str] = []
    if file_prefixes:
        ors = " OR ".join(
            f"starts_with(file_path, '{p.replace(chr(39), chr(39) * 2)}')" for p in file_prefixes
        )
        clauses.append(f"({ors})")
    if node_kinds:
        joined = ", ".join(f"'{k.replace(chr(39), chr(39) * 2)}'" for k in node_kinds)
        clauses.append(f"kind IN ({joined})")
    return " AND ".join(clauses) if clauses else None


def _seed_base_dist(nid: str, via_seed: str, seed_rank: dict[str, dict]) -> float:
    """Return the ranking distance for an expanded node.

    Seed nodes rank by their own ``self_dist`` (for lexical-only seeds this
    sits just behind the best dense hit); non-seed nodes inherit the
    conservative ``dist`` of the seed that reached them, so a lexical seed's
    neighbourhood cannot crowd out dense results.

    :param nid: Node id being ranked.
    :param via_seed: Seed id recorded by graph-expansion provenance.
    :param seed_rank: Seed metadata from :meth:`DocKG._fused_seeds`.
    :return: Cosine-distance-scale ranking value (lower = better).
    """
    own = seed_rank.get(nid)
    if own is not None:
        return own.get("self_dist", own["dist"])
    return seed_rank.get(via_seed, {"dist": 1e9})["dist"]


def _node_in_scope(
    node: dict,
    file_prefixes: tuple[str, ...] | None,
    node_kinds: tuple[str, ...] | None,
) -> bool:
    """Return True if ``node`` satisfies the scope constraints.

    Applied as a final guard after graph expansion, which can traverse edges
    (e.g. ``SIMILAR_TO``) into nodes outside the requested scope.

    :param node: Node dict with ``file_path`` and ``kind`` keys.
    :param file_prefixes: Required ``file_path`` prefixes (any match), or None.
    :param node_kinds: Allowed ``kind`` values, or None.
    :return: True if the node is in scope.
    """
    if node_kinds and node.get("kind") not in node_kinds:
        return False
    if file_prefixes:
        fp = node.get("file_path") or ""
        if not any(fp.startswith(p) for p in file_prefixes):
            return False
    return True


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
    :param topics_file_map: Optional per-path-prefix topics catalog mapping.
                            Keys are path prefixes matched against corpus-relative
                            file paths (first match wins).
                            Example: ``{"sacred-texts/": "topics/sacred-texts.yaml"}``.
    :param embedder: Optional embedding backend.  When provided, pre-sets ``_embedder``
                     so the lazy-init never fires ``SentenceTransformerEmbedder``.
                     Defaults to ``None`` (preserves existing behaviour).
    :param device: Embedding device override: ``auto`` (default), ``cpu``, ``mps``, ``cuda``.
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
        topics_file_map: dict[str, str] | None = None,
        kmeans_model_path: str | None = None,
        exclude: set[str] | None = None,
        embedder: Embedder | None = None,
        device: str = "auto",
        vector_backend: str | None = None,
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
        self.device = device
        self.table_name = table
        # Vector store backend: "auto" (default), "lancedb", or "sqlite-vec".
        # Explicit arg wins; else DOCKG_VECTOR_BACKEND env; else "auto" — which
        # picks sqlite-vec for fresh/converted corpora and lancedb only when an
        # un-migrated lancedb store is all that exists (see resolve_backend_name).
        self.vector_backend = vector_backend or os.environ.get("DOCKG_VECTOR_BACKEND") or "auto"
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
        self.topics_file_map = topics_file_map
        self.kmeans_model_path = kmeans_model_path

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
                topics_file_map=self.topics_file_map,
                kmeans_model_path=self.kmeans_model_path,
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
            self._embedder = make_embedder(self.model_name, device=self.device)
        return self._embedder

    @property
    def index(self) -> SemanticIndex:
        """Semantic vector index (lazy). Backend chosen by ``vector_backend``."""
        if self._index is None:
            backend = make_backend(
                self.vector_backend,
                lancedb_dir=self.lancedb_dir,
                dim=self.embedder.dim,
                table=self.table_name,
            )
            self._index = SemanticIndex(
                self.lancedb_dir,
                embedder=self.embedder,
                table=self.table_name,
                backend=backend,
            )
        return self._index

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(
        self,
        *,
        wipe: bool = False,
        discover_similar: bool = True,
        similar_k: int = 5,
        similarity_edge_threshold: float = 0.85,
        similar_max_degree: int = 0,
    ) -> BuildStats:
        """Full pipeline: corpus parsing → SQLite → LanceDB + SIMILAR_TO edges.

        :param wipe: Clear existing data before writing.
        :param discover_similar: Run SIMILAR_TO edge discovery after indexing.
        :param similar_k: Max SIMILAR_TO out-edges per chunk (top-k by score).
                          Set to 0 to disable the cap.
        :param similarity_edge_threshold: Minimum cosine similarity for a SIMILAR_TO edge.
        :param similar_max_degree: Hard per-node degree cap for SIMILAR_TO edges (0 = no cap).
        :return: :class:`BuildStats`.
        """
        graph_stats = self.build_graph(wipe=wipe)
        index_stats = self.build_index(
            wipe=wipe,
            discover_similar=discover_similar,
            similar_k=similar_k,
            similarity_edge_threshold=similarity_edge_threshold,
            similar_max_degree=similar_max_degree,
        )
        graph_stats.indexed_rows = index_stats.indexed_rows
        graph_stats.index_dim = index_stats.index_dim
        graph_stats.similar_edges_added = index_stats.similar_edges_added
        return graph_stats

    def build_graph(self, *, wipe: bool = False, quiet: bool = False) -> BuildStats:
        """Corpus parsing → SQLite only.

        :param wipe: Clear existing graph before writing.
        :param quiet: Suppress progress output.
        :return: :class:`BuildStats` (``indexed_rows`` will be ``None``).
        """
        nodes, edges = self.graph.extract(force=wipe, quiet=quiet).result()
        self.store.write(nodes, edges, wipe=wipe, quiet=quiet)
        self.store.rebuild_fts(quiet=quiet)
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
        device: str | None = None,
        only_missing: bool = False,
        quiet: bool = False,
    ) -> Path:
        """Embed all nodes and save to a JSON cache file (no LanceDB writes).

        The graph must already exist — run :meth:`build_graph` first.

        :param out: Output path for the embedding cache JSON.
                    Defaults to ``<db_path parent>/embeddings.json``.
        :param n_workers: Worker processes (default: CPU count / 2).
        :param batch_size: Per-worker embedding batch size.
        :param device: Embedding device (``"cpu"``/``"mps"``/``"cuda"``); ``None``
            resolves via ``KG_EMBED_DEVICE`` then auto-detect.  GPU devices force
            single-process embedding (the GPU can't be shared across workers).
        :param only_missing: Incremental — embed only nodes not already in the index
            (pair with ``build_index_from_cache(wipe=False)`` to upsert). ``.json``
            cache path only.
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
            device=device,
            only_missing=only_missing,
            quiet=quiet,
        )

    def prune_index(self, *, quiet: bool = False) -> int:
        """Delete index vectors whose node id is no longer in the graph.

        Run after an incremental (``only_missing``) embed + upsert so vectors for
        removed/renamed nodes (e.g. a deleted book) don't linger and return stale
        hits. The graph must reflect the current corpus (rebuild it first).

        :param quiet: Suppress the summary line.
        :return: Number of orphan vectors deleted.
        """
        keep = {n["id"] for n in self.store.query_nodes(kinds=list(self.index.index_kinds))}
        return self.index.prune(keep, quiet=quiet)

    def build_index_from_cache(
        self,
        cache_path: Path | str,
        *,
        wipe: bool = False,
        discover_similar: bool = True,
        similar_k: int = 5,
        similarity_edge_threshold: float = 0.85,
        similar_max_degree: int = 0,
        quiet: bool = False,
    ) -> BuildStats:
        """Build the LanceDB index from a pre-computed embedding cache.

        Skips the model inference pass — loads vectors from *cache_path* directly.
        Use :meth:`build_embeddings` to produce the cache.

        :param cache_path: Path to the embedding cache JSON.
        :param wipe: Delete existing vectors before indexing.
        :param discover_similar: Run SIMILAR_TO edge discovery after indexing.
        :param similar_k: Max SIMILAR_TO out-edges per chunk (top-k by score).
                          Set to 0 to disable the cap.
        :param similarity_edge_threshold: Minimum cosine similarity for a SIMILAR_TO edge.
        :param similar_max_degree: Hard per-node degree cap for SIMILAR_TO edges (0 = no cap).
        :param quiet: Suppress progress output.
        :return: :class:`BuildStats`.
        """
        idx_stats = self.index.build_from_cache(
            self.store,
            Path(cache_path),
            wipe=wipe,
            discover_similar=discover_similar,
            similar_k=similar_k,
            similarity_edge_threshold=similarity_edge_threshold,
            similar_max_degree=similar_max_degree,
            quiet=quiet,
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

    def build_index(
        self,
        *,
        wipe: bool = False,
        discover_similar: bool = True,
        similar_k: int = 5,
        similarity_edge_threshold: float = 0.85,
        similar_max_degree: int = 0,
    ) -> BuildStats:
        """SQLite → LanceDB only (graph must already exist).

        :param wipe: Delete existing vectors before indexing.
        :param discover_similar: Run SIMILAR_TO edge discovery after indexing.
        :param similar_k: Max SIMILAR_TO out-edges per chunk (top-k by score).
                          Set to 0 to disable the cap.
        :param similarity_edge_threshold: Minimum cosine similarity for a SIMILAR_TO edge.
        :param similar_max_degree: Hard per-node degree cap for SIMILAR_TO edges (0 = no cap).
        :return: :class:`BuildStats` with ``indexed_rows``, ``index_dim``, and
                 ``similar_edges_added`` set.
        """
        from rich.console import Console  # pylint: disable=import-outside-toplevel

        with Console().status("  Loading embedding model\u2026"):
            _ = self.embedder  # warm up: loads SentenceTransformer weights
        idx_stats = self.index.build(
            self.store,
            wipe=wipe,
            discover_similar=discover_similar,
            similar_k=similar_k,
            similarity_edge_threshold=similarity_edge_threshold,
            similar_max_degree=similar_max_degree,
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

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def _fused_seeds(
        self,
        q: str,
        k: int,
        *,
        file_prefixes: tuple[str, ...] | None = None,
        node_kinds: tuple[str, ...] | None = None,
    ) -> dict[str, dict]:
        """Produce ranked query seeds by fusing dense + lexical retrieval.

        Runs the dense vector search and the FTS5/BM25 lexical search, drops
        front-matter / reference chunks from both, then blends the two rank
        lists with reciprocal rank fusion (RRF).  This lets exact-phrase matches
        (which dense embeddings frequently bury) seed the graph expansion while
        preserving dense recall.  Degrades to pure dense ranking when the corpus
        has no lexical index (``nodes_fts`` absent on older builds).

        When ``file_prefixes``/``node_kinds`` are supplied, both retrieval
        channels are constrained at source (LanceDB prefilter + FTS5 SQL), so
        the seed budget is spent entirely on in-scope nodes.

        :param q: Natural-language query.
        :param k: Number of fused seeds to keep.
        :param file_prefixes: Restrict seeds to these ``file_path`` prefixes.
        :param node_kinds: Restrict seeds to these node kinds.
        :return: ``{node_id: {"rank": int, "dist": float}}`` ordered best-first.
        """
        where = _lance_where(file_prefixes, node_kinds)
        # Oversample the dense channel to survive front-matter / reference filtering.
        raw_hits = self.index.search(q, k=k * 3, where=where)
        dense = [h for h in raw_hits if not (h.file_path or "").endswith("reference.md")]
        lex_ids = self.store.search_lexical(
            q, limit=k * 3, file_prefixes=file_prefixes, node_kinds=node_kinds
        )

        # Single batch fetch to filter both channels by content_type.
        need = {h.id for h in dense} | set(lex_ids)
        nmap = self.store.nodes_batch(need) if need else {}

        def _ok(nid: str) -> bool:
            n = nmap.get(nid)
            if n is None:
                return False
            if (n.get("file_path") or "").endswith("reference.md"):
                return False
            return n.get("content_type") not in ("front_matter", "reference")

        dense = [h for h in dense if _ok(h.id)]
        lex_ids = [i for i in lex_ids if _ok(i)]

        dense_dist = {h.id: h.distance for h in dense}
        lex_rank = {i: r for r, i in enumerate(lex_ids)}

        scores: dict[str, float] = {}
        for r, h in enumerate(dense):
            scores[h.id] = scores.get(h.id, 0.0) + 1.0 / (_RRF_K + r)
        for i, r in lex_rank.items():
            scores[i] = scores.get(i, 0.0) + 1.0 / (_RRF_K + r)

        order = sorted(scores, key=lambda i: -scores[i])[:k]
        # A lexical match is strong evidence for the matching chunk *itself*
        # but weak evidence for its structural neighbourhood, so lexical-only
        # seeds carry two distances: ``self_dist`` slots the seed just behind
        # the best dense hit, while ``dist`` (used by expanded neighbours via
        # provenance) stays conservative so one BM25 hit cannot flood the
        # top-k with its neighbours.  Dense seeds use their real distance for
        # both.
        best_dense = min(dense_dist.values(), default=_LEXICAL_SEED_BASE_DIST)
        seed_rank: dict[str, dict] = {}
        for rank, nid in enumerate(order):
            if nid in dense_dist:
                dist = self_dist = dense_dist[nid]
            else:
                lex_pos = lex_rank.get(nid, 0)
                dist = _LEXICAL_SEED_BASE_DIST + _LEXICAL_SEED_STEP * lex_pos
                self_dist = min(best_dense + _LEXICAL_SEED_STEP * (lex_pos + 1), dist)
            seed_rank[nid] = {"rank": rank, "dist": dist, "self_dist": self_dist}
        return seed_rank

    def query(
        self,
        q: str,
        *,
        k: int = 8,
        hop: int = 1,
        rels: tuple[str, ...] = DEFAULT_RELS,
        max_nodes: int = 25,
        source_path_prefixes: tuple[str, ...] | None = None,
        node_kinds: tuple[str, ...] | None = None,
    ) -> QueryResult:
        """Hybrid query: semantic seeding + structural expansion.

        :param q: Natural-language query.
        :param k: Top-K semantic hits.
        :param hop: Graph expansion hops.
        :param rels: Edge types to expand.
        :param max_nodes: Maximum nodes to return.
        :param source_path_prefixes: When given, restrict retrieval to nodes
            whose ``file_path`` starts with one of these prefixes.  Pushed down
            to both the vector (LanceDB prefilter) and lexical (FTS5) seed
            channels, and enforced as a final guard so graph expansion cannot
            leak out-of-scope nodes.
        :param node_kinds: When given, restrict results to these node kinds
            (e.g. ``("chunk", "section")`` to drop structural/topic nodes).
        :return: :class:`QueryResult`.
        """
        # Fuse dense (vector) and lexical (BM25) seed channels via RRF.
        seed_rank = self._fused_seeds(
            q, k, file_prefixes=source_path_prefixes, node_kinds=node_kinds
        )
        seed_ids: set[str] = set(seed_rank.keys())

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
            base_dist = _seed_base_dist(nid, prov.via_seed, seed_rank)
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

        _excluded_types = {"front_matter", "reference"}
        nodes: list[dict] = []
        kept_ids: set[str] = set()
        for n in ranked_nodes:
            if len(nodes) >= max_nodes:
                break
            # Keep front_matter/reference in the graph for traversal but exclude
            # them from returned results — they are preamble/metadata, not content.
            if n.get("content_type") in _excluded_types:
                continue
            # Final scope guard: graph expansion can cross out of the requested
            # subtree/kinds via edges; drop any node that escaped the seed filter.
            if not _node_in_scope(n, source_path_prefixes, node_kinds):
                continue
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
        source_path_prefixes: tuple[str, ...] | None = None,
        node_kinds: tuple[str, ...] | None = None,
        traced: bool = False,
    ) -> TextPack:
        """Hybrid query + text excerpt extraction.

        :param q: Natural-language query.
        :param k: Top-K semantic hits.
        :param hop: Graph expansion hops.
        :param rels: Edge types to expand.
        :param max_chars: Maximum characters per text excerpt.
        :param max_nodes: Maximum nodes to return (``None`` for no limit).
        :param source_path_prefixes: When given, restrict retrieval to nodes
            whose ``file_path`` starts with one of these prefixes (pushed down
            to both seed channels and enforced after expansion).
        :param node_kinds: When given, restrict results to these node kinds.
        :param traced: When ``True``, attach a provenance path (seed → … → node,
            with a quoted source line per hop) to each returned node.  The paths
            ride on the edges already fetched for expansion — no extra queries.
        :return: :class:`TextPack`.
        """
        seed_rank = self._fused_seeds(
            q, k, file_prefixes=source_path_prefixes, node_kinds=node_kinds
        )
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
            base_dist = _seed_base_dist(nid, prov.via_seed, seed_rank)
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
            # Final scope guard: drop nodes that expansion pulled out of scope.
            if not _node_in_scope(n, source_path_prefixes, node_kinds):
                continue
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

        # Provenance paths (before stripping internal keys, using the full
        # expanded subgraph so paths can traverse un-returned intermediate nodes).
        paths: dict[str, list[dict]] | None = None
        if traced:
            paths = _trace_paths(seed_ids, node_map, all_edges, kept_ids)

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
            paths=paths,
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
            # Count vectors without loading the embedder/model: a read-only
            # count doesn't need the true dim, so use a throwaway backend.
            # count() opens existing stores lazily and never creates one.
            vector_count = 0
            with contextlib.suppress(Exception):
                vector_count = make_backend(
                    self.vector_backend,
                    lancedb_dir=self.lancedb_dir,
                    dim=384,
                    table=self.table_name,
                ).count()
            return {
                "node_count": s.get("total_nodes", 0),
                "edge_count": s.get("total_edges", 0),
                "document_count": nc.get("document", 0),
                "chunk_count": nc.get("chunk", 0),
                "section_count": nc.get("section", 0),
                "topic_count": nc.get("topic", 0),
                "entity_count": nc.get("entity", 0),
                "keyword_count": nc.get("keyword", 0),
                "vector_backend": self.vector_backend,
                "vector_count": vector_count,
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
