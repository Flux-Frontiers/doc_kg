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
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console

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
  text          TEXT,
  content_type  TEXT,
  book          TEXT,
  chapter       INTEGER,
  verse_start   INTEGER,
  verse_end     INTEGER
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
CREATE INDEX IF NOT EXISTS idx_edges_src_rel ON edges(src, rel);
CREATE INDEX IF NOT EXISTS idx_edges_dst_rel ON edges(dst, rel);
"""

# Default edge types used for graph expansion (document layer only)
DEFAULT_RELS: tuple[str, ...] = (
    "CONTAINS",
    "NEXT",
    "REFERENCES",
    "SIMILAR_TO",
    "HAS_TOPIC",
    "MENTIONS_ENTITY",
    "HAS_KEYWORD",
)

# Memory layer edge types (semantic assertions + events)
MEMORY_RELS: tuple[str, ...] = (
    "SUPPORTS",  # chunk → assertion
    "ABOUT",  # assertion → entity (subject)
    "REFERS_TO",  # assertion → entity (object)
    "INVOLVES",  # event → entity
    "DESCRIBES",  # chunk → event
    "SUPERSEDES",  # assertion → assertion
    "DERIVED_FROM",  # assertion → event
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
            # Migrate existing DBs: add verse columns if they don't exist yet
            for col, typ in [
                ("content_type", "TEXT"),
                ("book", "TEXT"),
                ("chapter", "INTEGER"),
                ("verse_start", "INTEGER"),
                ("verse_end", "INTEGER"),
            ]:
                try:
                    self._con.execute(f"ALTER TABLE nodes ADD COLUMN {col} {typ}")
                    self._con.commit()
                except Exception:  # pylint: disable=broad-exception-caught  # column already exists — sqlite3.OperationalError
                    pass
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

    def stamp_meta(self, builder_name: str, builder_version: str) -> None:
        """Write KGRAG builder-version metadata into the ``_kgrag_meta`` table.

        :param builder_name: Builder package name (e.g. ``"doc_kg"``).
        :param builder_version: Builder package ``__version__``.
        """
        self.con.execute(
            "CREATE TABLE IF NOT EXISTS _kgrag_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        self.con.executemany(
            "INSERT OR REPLACE INTO _kgrag_meta (key, value) VALUES (?, ?)",
            [
                ("builder_name", builder_name),
                ("builder_version", builder_version),
                ("built_at", datetime.now(UTC).isoformat()),
            ],
        )
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
                prog.add_task("  Writing nodes", total=len(node_list)) if prog is not None else None
            )
            for i in range(0, len(node_list), batch_size):
                batch = node_list[i : i + batch_size]
                self.con.executemany(
                    """
                    INSERT INTO nodes
                      (id, kind, name, title, file_path, char_start, char_end, heading_level,
                       text, content_type, book, chapter, verse_start, verse_end)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                      kind=excluded.kind,
                      name=excluded.name,
                      title=excluded.title,
                      file_path=excluded.file_path,
                      char_start=excluded.char_start,
                      char_end=excluded.char_end,
                      heading_level=excluded.heading_level,
                      text=excluded.text,
                      content_type=excluded.content_type,
                      book=excluded.book,
                      chapter=excluded.chapter,
                      verse_start=excluded.verse_start,
                      verse_end=excluded.verse_end
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
                            n.content_type,
                            n.book,
                            n.chapter,
                            n.verse_start,
                            n.verse_end,
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
                prog.add_task("  Writing edges", total=len(edge_list)) if prog is not None else None
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
            SELECT id, kind, name, title, file_path, char_start, char_end, heading_level, text,
                   content_type, book, chapter, verse_start, verse_end
            FROM nodes WHERE id = ?
            """,
            (node_id,),
        ).fetchone()
        return _row_to_node(row) if row else None

    def nodes_batch(self, node_ids: set[str]) -> dict[str, dict]:
        """Fetch multiple nodes in a single query.

        :param node_ids: Node IDs to fetch.
        :return: ``{node_id: node_dict}`` for all found nodes.
        """
        if not node_ids:
            return {}
        self.con.execute("DROP TABLE IF EXISTS _tmp_nids;")
        self.con.execute("CREATE TEMP TABLE _tmp_nids (id TEXT PRIMARY KEY);")
        self.con.executemany("INSERT INTO _tmp_nids (id) VALUES (?)", [(i,) for i in node_ids])
        rows = self.con.execute("""
            SELECT n.id, n.kind, n.name, n.title, n.file_path,
                   n.char_start, n.char_end, n.heading_level, n.text,
                   n.content_type, n.book, n.chapter, n.verse_start, n.verse_end
            FROM nodes n
            JOIN _tmp_nids t ON t.id = n.id
            """).fetchall()
        return {r[0]: _row_to_node(r) for r in rows}

    # ------------------------------------------------------------------
    # Read — filtered node lists
    # ------------------------------------------------------------------

    def count_nodes(self, *, kinds: Sequence[str] | None = None) -> int:
        """Return total count of nodes matching optional kind filter.

        :param kinds: Restrict to these node kinds.
        :return: Row count.
        """
        if kinds:
            placeholders = ",".join("?" for _ in kinds)
            row = self.con.execute(
                f"SELECT COUNT(*) FROM nodes WHERE kind IN ({placeholders})",
                list(kinds),
            ).fetchone()
        else:
            row = self.con.execute("SELECT COUNT(*) FROM nodes").fetchone()
        return int(row[0]) if row else 0

    def query_nodes(
        self,
        *,
        kinds: Sequence[str] | None = None,
        file_path: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict]:
        """Return nodes matching optional filters.

        :param kinds: Restrict to these node kinds (e.g. ``["chunk", "section"]``).
        :param file_path: Restrict to nodes in this file path (exact match).
        :param limit: Maximum rows to return (``None`` = all).
        :param offset: Row offset for pagination.
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
        page = ""
        if limit is not None:
            page = f"LIMIT {int(limit)} OFFSET {int(offset)}"

        rows = self.con.execute(
            f"""
            SELECT id, kind, name, title, file_path, char_start, char_end, heading_level, text,
                   content_type, book, chapter, verse_start, verse_end
            FROM nodes {where}
            ORDER BY file_path, char_start
            {page}
            """,
            params,
        ).fetchall()
        return [_row_to_node(r) for r in rows]

    def iter_nodes(
        self,
        *,
        kinds: Sequence[str] | None = None,
        batch_size: int = 512,
    ):
        """Yield node dicts in batches without loading all rows into RAM.

        :param kinds: Restrict to these node kinds.
        :param batch_size: Rows per batch.
        :return: Generator of ``list[dict]`` batches.
        """
        clauses: list[str] = []
        params: list[object] = []

        if kinds:
            placeholders = ",".join("?" for _ in kinds)
            clauses.append(f"kind IN ({placeholders})")
            params.extend(kinds)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        cursor = self.con.execute(
            f"""
            SELECT id, kind, name, title, file_path, char_start, char_end, heading_level, text,
                   content_type, book, chapter, verse_start, verse_end
            FROM nodes {where}
            ORDER BY file_path, char_start
            """,
            params,
        )

        while True:
            rows = cursor.fetchmany(batch_size)
            if not rows:
                break
            yield [_row_to_node(r) for r in rows]

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
        rows = self.con.execute("""
            SELECT e.src, e.rel, e.dst, e.evidence
            FROM edges e
            JOIN _tmp_ids s ON s.id = e.src
            JOIN _tmp_ids d ON d.id = e.dst
            """).fetchall()
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
        max_frontier: int = 5_000,
    ) -> dict[str, ProvMeta]:
        """Expand the graph from *seed_ids* up to *hop* hops.

        Returns a mapping from every reachable node ID to its
        :class:`ProvMeta` (minimum hop distance and originating seed).

        Uses a single batched SQL query per hop (via a temp table + UNION)
        rather than one query per frontier node, which is orders of magnitude
        faster over large graphs.  The frontier is capped at *max_frontier*
        nodes before each hop to prevent explosive expansion through
        high-degree hub nodes (e.g. CO_OCCURS_WITH, CONTAINS).

        :param seed_ids: Starting node IDs (hop 0).
        :param hop: Maximum number of hops to traverse.
        :param rels: Edge relation types to follow.
        :param max_frontier: Maximum frontier size per hop.  Excess nodes are
            dropped before the next hop (seeds are always kept at hop 0).
        :return: ``{node_id: ProvMeta}`` for all reachable nodes.
        """
        rels = tuple(rels)
        rel_ph = ",".join("?" for _ in rels)

        meta: dict[str, ProvMeta] = {sid: ProvMeta(best_hop=0, via_seed=sid) for sid in seed_ids}
        frontier: set[str] = set(seed_ids)

        for h in range(1, hop + 1):
            if not frontier:
                break

            # Cap frontier to prevent explosive fan-out through hub nodes.
            if len(frontier) > max_frontier:
                frontier = set(list(frontier)[:max_frontier])

            # Load frontier + provenance into a temp table for batch lookup.
            self.con.execute("DROP TABLE IF EXISTS _tmp_frontier;")
            self.con.execute(
                "CREATE TEMP TABLE _tmp_frontier (id TEXT PRIMARY KEY, via_seed TEXT);"
            )
            self.con.executemany(
                "INSERT INTO _tmp_frontier (id, via_seed) VALUES (?, ?)",
                [(nid, meta[nid].via_seed) for nid in frontier],
            )

            # Two index-friendly JOIN scans (no OR) unified with UNION ALL.
            # Uses composite indexes idx_edges_src_rel and idx_edges_dst_rel.
            rows = self.con.execute(
                f"""
                SELECT f.via_seed, e.src, e.dst
                FROM _tmp_frontier f
                JOIN edges e ON e.src = f.id
                WHERE e.rel IN ({rel_ph})
                UNION ALL
                SELECT f.via_seed, e.src, e.dst
                FROM _tmp_frontier f
                JOIN edges e ON e.dst = f.id
                WHERE e.rel IN ({rel_ph})
                """,
                (*rels, *rels),
            ).fetchall()

            nxt: set[str] = set()
            for via_seed, src, dst in rows:
                for cand in (src, dst):
                    if cand not in meta:
                        meta[cand] = ProvMeta(best_hop=h, via_seed=via_seed)
                        nxt.add(cand)
                    elif h < meta[cand].best_hop:
                        meta[cand] = ProvMeta(best_hop=h, via_seed=via_seed)
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
    d = {
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
    # Verse metadata columns (present in schema v2+; None for older rows)
    if len(row) > 9:
        d["content_type"] = row[9]
        d["book"] = row[10]
        d["chapter"] = row[11]
        d["verse_start"] = row[12]
        d["verse_end"] = row[13]
    return d
