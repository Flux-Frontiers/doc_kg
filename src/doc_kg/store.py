#!/usr/bin/env python3
"""
store.py

GraphStore — SQLite persistence layer for DocKG.

Mirrors CodeKG's GraphStore almost exactly.  SQLite is the authoritative,
canonical store.  No embeddings, no LanceDB, no text parsing.

Schema differences from CodeKG:
  - ``nodes.text``   replaces  ``nodes.docstring``
  - ``nodes.title``  replaces  ``nodes.qualname``
  - ``nodes.char_start`` / ``nodes.char_end``  replace  ``nodes.lineno`` / ``nodes.end_lineno``
  - ``nodes.heading_level`` is new (int, nullable)
  - DEFAULT_RELS includes SIMILAR_TO and NEXT in addition to CONTAINS/REFERENCES

Author: Eric G. Suchanek, PhD
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
from collections.abc import Iterable, Sequence
from pathlib import Path

from doc_kg.dockg import DocEdge, DocNode

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS nodes (
  id            TEXT PRIMARY KEY,
  kind          TEXT NOT NULL,
  name          TEXT NOT NULL,
  title         TEXT,
  file_path     TEXT,
  char_start    INTEGER,
  char_end      INTEGER,
  heading_level INTEGER,
  text          TEXT
);

CREATE TABLE IF NOT EXISTS edges (
  src      TEXT NOT NULL,
  rel      TEXT NOT NULL,
  dst      TEXT NOT NULL,
  evidence TEXT,
  PRIMARY KEY (src, rel, dst)
);

CREATE INDEX IF NOT EXISTS idx_nodes_kind      ON nodes(kind);
CREATE INDEX IF NOT EXISTS idx_nodes_name      ON nodes(name);
CREATE INDEX IF NOT EXISTS idx_nodes_file_path ON nodes(file_path);

CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst);
CREATE INDEX IF NOT EXISTS idx_edges_rel ON edges(rel);
"""

# Default edge types used for graph expansion
DEFAULT_RELS: tuple[str, ...] = (
    "CONTAINS",
    "NEXT",
    "REFERENCES",
    "SIMILAR_TO",
    "HAS_TOPIC",
    "MENTIONS_ENTITY",
    "HAS_KEYWORD",
    "CO_OCCURS_WITH",
)


# ---------------------------------------------------------------------------
# Provenance metadata returned by expand()
# ---------------------------------------------------------------------------


class ProvMeta:
    """
    Provenance metadata for a node returned by :meth:`GraphStore.expand`.

    :param best_hop: Minimum hop distance from any seed node.
    :param via_seed: ID of the seed node that yielded the shortest path.
    """

    __slots__ = ("best_hop", "via_seed")

    def __init__(self, best_hop: int, via_seed: str) -> None:
        self.best_hop = best_hop
        self.via_seed = via_seed

    def __repr__(self) -> str:
        return f"ProvMeta(best_hop={self.best_hop}, via_seed={self.via_seed!r})"


# ---------------------------------------------------------------------------
# GraphStore
# ---------------------------------------------------------------------------


class GraphStore:
    """
    SQLite-backed authoritative store for the DocKG.

    Manages the ``nodes`` and ``edges`` tables and provides graph
    traversal primitives used by the query layer.

    Example::

        store = GraphStore("dockg.sqlite")
        store.write(nodes, edges, wipe=True)
        print(store.stats())

    :param db_path: Path to the SQLite database file (created if absent).
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self._con: sqlite3.Connection | None = None

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    @property
    def con(self) -> sqlite3.Connection:
        """Lazy SQLite connection (created on first access)."""
        if self._con is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._con = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
            )
            self._con.executescript(_SCHEMA_SQL)
        return self._con

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        if self._con is not None:
            self._con.close()
            self._con = None

    def __enter__(self) -> GraphStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Delete all nodes and edges."""
        self.con.execute("DELETE FROM edges;")
        self.con.execute("DELETE FROM nodes;")
        self.con.commit()

    def write(
        self,
        nodes: Sequence[DocNode],
        edges: Sequence[DocEdge],
        *,
        wipe: bool = False,
        quiet: bool = False,
        batch_size: int = 10_000,
    ) -> None:
        """Persist a complete graph to SQLite.

        :param nodes: Node list from :class:`~doc_kg.graph.DocGraph`.
        :param edges: Edge list from :class:`~doc_kg.graph.DocGraph`.
        :param wipe: If ``True``, clear existing data before writing.
        :param quiet: Suppress progress output (default: ``False``).
        :param batch_size: Rows per commit batch.
        """
        if wipe:
            if not quiet:
                from rich.console import Console  # pylint: disable=import-outside-toplevel

                Console().print("  Clearing existing graph\u2026")
            self.clear()
        self._upsert_nodes(nodes, quiet=quiet, batch_size=batch_size)
        self._upsert_edges(edges, quiet=quiet, batch_size=batch_size)

    def _upsert_nodes(
        self,
        nodes: Iterable[DocNode],
        *,
        quiet: bool = False,
        batch_size: int = 10_000,
    ) -> None:
        node_list = list(nodes)
        if not node_list:
            return

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

            _ctx: contextlib.AbstractContextManager = Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                TimeElapsedColumn(),
                TimeRemainingColumn(),
            )
        else:
            _ctx = contextlib.nullcontext()

        with _ctx as prog:
            task = (
                prog.add_task("  Writing nodes", total=len(node_list))
                if prog is not None
                else None
            )
            for i in range(0, len(node_list), batch_size):
                batch = node_list[i : i + batch_size]
                self.con.executemany(
                    """
                    INSERT INTO nodes
                      (id, kind, name, title, file_path, char_start, char_end, heading_level, text)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                      kind=excluded.kind,
                      name=excluded.name,
                      title=excluded.title,
                      file_path=excluded.file_path,
                      char_start=excluded.char_start,
                      char_end=excluded.char_end,
                      heading_level=excluded.heading_level,
                      text=excluded.text
                    """,
                    [
                        (
                            n.id,
                            n.kind,
                            n.name,
                            n.title,
                            n.file_path,
                            n.char_start,
                            n.char_end,
                            n.heading_level,
                            n.text,
                        )
                        for n in batch
                    ],
                )
                self.con.commit()
                if prog is not None and task is not None:
                    prog.advance(task, len(batch))

    def _upsert_edges(
        self,
        edges: Iterable[DocEdge],
        *,
        quiet: bool = False,
        batch_size: int = 10_000,
    ) -> None:
        edge_list = list(edges)
        if not edge_list:
            return

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

            _ctx: contextlib.AbstractContextManager = Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                TimeElapsedColumn(),
                TimeRemainingColumn(),
            )
        else:
            _ctx = contextlib.nullcontext()

        with _ctx as prog:
            task = (
                prog.add_task("  Writing edges", total=len(edge_list))
                if prog is not None
                else None
            )
            for i in range(0, len(edge_list), batch_size):
                batch = edge_list[i : i + batch_size]
                self.con.executemany(
                    """
                    INSERT INTO edges (src, rel, dst, evidence)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(src, rel, dst) DO UPDATE SET
                      evidence=excluded.evidence
                    """,
                    [
                        (
                            e.src,
                            e.rel,
                            e.dst,
                            (
                                json.dumps(e.evidence, ensure_ascii=False)
                                if e.evidence is not None
                                else None
                            ),
                        )
                        for e in batch
                    ],
                )
                self.con.commit()
                if prog is not None and task is not None:
                    prog.advance(task, len(batch))

    # ------------------------------------------------------------------
    # Read — single node
    # ------------------------------------------------------------------

    def node(self, node_id: str) -> dict | None:
        """Fetch a single node by id.

        :param node_id: Stable node identifier.
        :return: Node dict or ``None`` if not found.
        """
        row = self.con.execute(
            """
            SELECT id, kind, name, title, file_path, char_start, char_end, heading_level, text
            FROM nodes WHERE id = ?
            """,
            (node_id,),
        ).fetchone()
        return _row_to_node(row) if row else None

    # ------------------------------------------------------------------
    # Read — filtered node lists
    # ------------------------------------------------------------------

    def query_nodes(
        self,
        *,
        kinds: Sequence[str] | None = None,
        file_path: str | None = None,
    ) -> list[dict]:
        """Return nodes matching optional filters.

        :param kinds: Restrict to these node kinds (e.g. ``["chunk", "section"]``).
        :param file_path: Restrict to nodes in this file path (exact match).
        :return: List of node dicts.
        """
        clauses: list[str] = []
        params: list[object] = []

        if kinds:
            placeholders = ",".join("?" for _ in kinds)
            clauses.append(f"kind IN ({placeholders})")
            params.extend(kinds)

        if file_path is not None:
            clauses.append("file_path = ?")
            params.append(file_path)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.con.execute(
            f"""
            SELECT id, kind, name, title, file_path, char_start, char_end, heading_level, text
            FROM nodes {where}
            ORDER BY file_path, char_start
            """,
            params,
        ).fetchall()
        return [_row_to_node(r) for r in rows]

    # ------------------------------------------------------------------
    # Read — edges
    # ------------------------------------------------------------------

    def edges_within(self, node_ids: set[str]) -> list[dict]:
        """Return all edges where both src and dst are in *node_ids*.

        :param node_ids: Set of node IDs to restrict to.
        :return: List of edge dicts.
        """
        if not node_ids:
            return []

        self.con.execute("DROP TABLE IF EXISTS _tmp_ids;")
        self.con.execute("CREATE TEMP TABLE _tmp_ids (id TEXT PRIMARY KEY);")
        self.con.executemany("INSERT INTO _tmp_ids (id) VALUES (?)", [(i,) for i in node_ids])
        rows = self.con.execute(
            """
            SELECT e.src, e.rel, e.dst, e.evidence
            FROM edges e
            JOIN _tmp_ids s ON s.id = e.src
            JOIN _tmp_ids d ON d.id = e.dst
            """
        ).fetchall()
        return [{"src": r[0], "rel": r[1], "dst": r[2], "evidence": r[3]} for r in rows]

    def edges_from(
        self, node_id: str, *, rel: str | None = None, limit: int | None = None
    ) -> list[dict]:
        """Return all edges originating from *node_id*.

        :param node_id: Source node identifier.
        :param rel: Relation type filter (``None`` returns all relations).
        :param limit: Maximum number of edges to return.
        :return: List of edge dicts.
        """
        if rel is not None:
            query = "SELECT src, rel, dst, evidence FROM edges WHERE src = ? AND rel = ?"
            params: list[object] = [node_id, rel]
        else:
            query = "SELECT src, rel, dst, evidence FROM edges WHERE src = ?"
            params = [node_id]
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        rows = self.con.execute(query, params).fetchall()
        return [{"src": r[0], "rel": r[1], "dst": r[2], "evidence": r[3]} for r in rows]

    # ------------------------------------------------------------------
    # Graph traversal
    # ------------------------------------------------------------------

    def expand(
        self,
        seed_ids: set[str],
        *,
        hop: int = 1,
        rels: tuple[str, ...] = DEFAULT_RELS,
    ) -> dict[str, ProvMeta]:
        """Expand the graph from *seed_ids* up to *hop* hops.

        Returns a mapping from every reachable node ID to its
        :class:`ProvMeta` (minimum hop distance and originating seed).

        :param seed_ids: Starting node IDs (hop 0).
        :param hop: Maximum number of hops to traverse.
        :param rels: Edge relation types to follow.
        :return: ``{node_id: ProvMeta}`` for all reachable nodes.
        """
        rels = tuple(rels)
        meta: dict[str, ProvMeta] = {sid: ProvMeta(best_hop=0, via_seed=sid) for sid in seed_ids}
        frontier: set[str] = set(seed_ids)

        for h in range(1, hop + 1):
            nxt: set[str] = set()
            for nid in frontier:
                rows = self.con.execute(
                    f"""
                    SELECT src, dst FROM edges
                    WHERE (src = ? OR dst = ?)
                      AND rel IN ({",".join("?" for _ in rels)})
                    """,
                    (nid, nid, *rels),
                ).fetchall()
                for src, dst in rows:
                    for cand in (src, dst):
                        if cand not in meta:
                            meta[cand] = ProvMeta(
                                best_hop=h,
                                via_seed=meta[nid].via_seed,
                            )
                            nxt.add(cand)
                        elif h < meta[cand].best_hop:
                            meta[cand] = ProvMeta(
                                best_hop=h,
                                via_seed=meta[nid].via_seed,
                            )
                            nxt.add(cand)
            frontier = nxt

        return meta

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        """Return node and edge counts by kind/relation.

        :return: dict with ``total_nodes``, ``total_edges``, ``node_counts``,
                 ``edge_counts``.
        """
        node_rows = self.con.execute("SELECT kind, COUNT(*) FROM nodes GROUP BY kind").fetchall()
        edge_rows = self.con.execute("SELECT rel, COUNT(*) FROM edges GROUP BY rel").fetchall()
        total_nodes = self.con.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        total_edges = self.con.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        return {
            "db_path": str(self.db_path),
            "total_nodes": total_nodes,
            "total_edges": total_edges,
            "node_counts": {r[0]: r[1] for r in node_rows},
            "edge_counts": {r[0]: r[1] for r in edge_rows},
        }

    def __repr__(self) -> str:
        return f"GraphStore(db_path={self.db_path!r})"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _row_to_node(row: tuple) -> dict:
    """Convert a raw SQLite row into a node dict."""
    return {
        "id": row[0],
        "kind": row[1],
        "name": row[2],
        "title": row[3],
        "file_path": row[4],
        "char_start": row[5],
        "char_end": row[6],
        "heading_level": row[7],
        "text": row[8],
    }
