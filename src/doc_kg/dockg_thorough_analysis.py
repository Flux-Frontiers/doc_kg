#!/usr/bin/env python3
"""
DocKG thorough corpus analysis.

Adapted from CodeKG's thorough analysis flow, but with document-graph metrics.
Produces a report focused on corpus structure, semantic coverage, and hotspots.
"""

from __future__ import annotations

import datetime
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.table import Table

from doc_kg.kg import DocKG
from doc_kg.store import GraphStore


@dataclass
class DocumentMetrics:
    """Per-document aggregate metrics.

    :param file_path: Corpus-relative path.
    :param chunks: Number of chunk nodes.
    :param sections: Number of section nodes.
    :param refs_out: Outgoing REFERENCES edges from document chunks.
    :param semantic_links: Outgoing semantic links from chunks.
    """

    file_path: str
    chunks: int
    sections: int
    refs_out: int
    semantic_links: int


class DocKGAnalyzer:
    """Thorough analyzer for document knowledge graphs."""

    def __init__(self, kg: DocKG, console: Console | None = None):
        self.kg = kg
        self.console = console or Console()
        self.store: GraphStore = kg.store
        self.stats: dict = {}
        self.document_metrics: list[DocumentMetrics] = []
        self.orphan_semantic_nodes: dict[str, int] = {}
        self.semantic_coverage: dict[str, float] = {}
        self.hot_chunks: list[dict] = []
        self.issues: list[str] = []
        self.strengths: list[str] = []

    def run_analysis(self, report_path: str | None = None) -> dict:
        """Run all analysis phases and optionally write Markdown report."""
        start = datetime.datetime.now(datetime.UTC)

        self._analyze_baseline()
        self._analyze_document_metrics()
        self._analyze_semantic_coverage()
        self._analyze_orphans()
        self._analyze_hot_chunks()
        self._generate_insights()

        elapsed = (datetime.datetime.now(datetime.UTC) - start).total_seconds()
        result = self._compile_results(elapsed_seconds=elapsed)

        if report_path:
            self._write_report(report_path, result)

        return result

    def _analyze_baseline(self) -> None:
        self.console.print("[dim]Analyzing baseline graph stats...[/dim]")
        self.stats = self.kg.stats()

    def _analyze_document_metrics(self) -> None:
        self.console.print("[dim]Computing per-document structure metrics...[/dim]")
        rows = self.store.con.execute(
            """
            SELECT
              n.file_path,
              SUM(CASE WHEN n.kind = 'chunk' THEN 1 ELSE 0 END) AS chunks,
              SUM(CASE WHEN n.kind = 'section' THEN 1 ELSE 0 END) AS sections
            FROM nodes n
            WHERE n.file_path IS NOT NULL
            GROUP BY n.file_path
            ORDER BY chunks DESC
            """
        ).fetchall()

        refs_by_doc = defaultdict(int)
        semantic_by_doc = defaultdict(int)

        edge_rows = self.store.con.execute(
            """
            SELECT s.file_path, e.rel, COUNT(*)
            FROM edges e
            JOIN nodes s ON s.id = e.src
            WHERE s.kind = 'chunk' AND s.file_path IS NOT NULL
            GROUP BY s.file_path, e.rel
            """
        ).fetchall()

        for file_path, rel, cnt in edge_rows:
            if rel == "REFERENCES":
                refs_by_doc[file_path] += int(cnt)
            if rel in {
                "HAS_TOPIC",
                "MENTIONS_ENTITY",
                "HAS_KEYWORD",
                "SIMILAR_TO",
                "CO_OCCURS_WITH",
            }:
                semantic_by_doc[file_path] += int(cnt)

        metrics: list[DocumentMetrics] = []
        for file_path, chunks, sections in rows:
            metrics.append(
                DocumentMetrics(
                    file_path=file_path,
                    chunks=int(chunks or 0),
                    sections=int(sections or 0),
                    refs_out=refs_by_doc[file_path],
                    semantic_links=semantic_by_doc[file_path],
                )
            )
        self.document_metrics = metrics

    def _analyze_semantic_coverage(self) -> None:
        self.console.print("[dim]Measuring semantic extraction coverage...[/dim]")
        chunk_count = self.store.con.execute(
            "SELECT COUNT(*) FROM nodes WHERE kind = 'chunk'"
        ).fetchone()[0]

        if chunk_count == 0:
            self.semantic_coverage = {
                "topic_coverage": 0.0,
                "entity_coverage": 0.0,
                "keyword_coverage": 0.0,
            }
            return

        def _covered(rel: str) -> int:
            return int(
                self.store.con.execute(
                    """
                    SELECT COUNT(DISTINCT src)
                    FROM edges
                    WHERE rel = ?
                    """,
                    (rel,),
                ).fetchone()[0]
            )

        self.semantic_coverage = {
            "topic_coverage": _covered("HAS_TOPIC") / chunk_count,
            "entity_coverage": _covered("MENTIONS_ENTITY") / chunk_count,
            "keyword_coverage": _covered("HAS_KEYWORD") / chunk_count,
        }

    def _analyze_orphans(self) -> None:
        self.console.print("[dim]Finding orphaned semantic nodes...[/dim]")
        counts: dict[str, int] = {}
        for kind, rel in [
            ("topic", "HAS_TOPIC"),
            ("entity", "MENTIONS_ENTITY"),
            ("keyword", "HAS_KEYWORD"),
        ]:
            counts[kind] = int(
                self.store.con.execute(
                    """
                    SELECT COUNT(*)
                    FROM nodes n
                    WHERE n.kind = ?
                      AND NOT EXISTS (
                        SELECT 1 FROM edges e
                        WHERE e.rel = ? AND e.dst = n.id
                      )
                    """,
                    (kind, rel),
                ).fetchone()[0]
            )
        self.orphan_semantic_nodes = counts

    def _analyze_hot_chunks(self) -> None:
        self.console.print("[dim]Ranking high-connectivity chunks...[/dim]")
        rows = self.store.con.execute(
            """
            SELECT
              n.id,
              n.file_path,
              COALESCE(n.title, n.name, n.id) AS label,
                            SUM(CASE WHEN e.rel = 'REFERENCES' THEN 1 ELSE 0 END) AS refs_count,
              SUM(CASE WHEN e.rel IN ('HAS_TOPIC', 'MENTIONS_ENTITY', 'HAS_KEYWORD', 'SIMILAR_TO', 'CO_OCCURS_WITH')
                THEN 1 ELSE 0 END) AS semantic_links,
              COUNT(*) AS total_links
            FROM edges e
            JOIN nodes n ON n.id = e.src
            WHERE n.kind = 'chunk'
            GROUP BY n.id
                        ORDER BY semantic_links DESC, refs_count DESC, total_links DESC
            LIMIT 15
            """
        ).fetchall()

        self.hot_chunks = [
            {
                "id": row[0],
                "file_path": row[1],
                "label": row[2],
                "references": int(row[3] or 0),
                "semantic_links": int(row[4] or 0),
                "total_links": int(row[5] or 0),
            }
            for row in rows
        ]

    def _generate_insights(self) -> None:
        node_counts = self.stats.get("node_counts", {})
        chunk_count = int(node_counts.get("chunk", 0))
        doc_count = int(node_counts.get("document", 0))

        if doc_count > 0 and chunk_count / max(doc_count, 1) >= 4:
            self.strengths.append(
                "Good chunk granularity: documents are being segmented into useful semantic units."
            )
        else:
            self.issues.append(
                "Chunk density appears low; consider reducing --chunk-size or reviewing corpus content."
            )

        for key, label in [
            ("topic_coverage", "topic"),
            ("entity_coverage", "entity"),
            ("keyword_coverage", "keyword"),
        ]:
            cov = self.semantic_coverage.get(key, 0.0)
            if cov < 0.25:
                self.issues.append(
                    f"Low {label} coverage ({cov:.1%}); consider enabling extraction and tuning thresholds."
                )
            elif cov >= 0.6:
                self.strengths.append(
                    f"Strong {label} coverage ({cov:.1%}) across chunks."
                )

        if self.orphan_semantic_nodes.get("topic", 0) == 0:
            self.strengths.append("No orphaned topic nodes detected.")
        if any(v > 0 for v in self.orphan_semantic_nodes.values()):
            self.issues.append(
                "Orphan semantic nodes detected; graph may contain stale topic/entity/keyword nodes."
            )

    def _compile_results(self, *, elapsed_seconds: float) -> dict:
        return {
            "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
            "elapsed_seconds": round(elapsed_seconds, 2),
            "stats": self.stats,
            "semantic_coverage": self.semantic_coverage,
            "orphan_semantic_nodes": self.orphan_semantic_nodes,
            "document_metrics": [m.__dict__ for m in self.document_metrics],
            "hot_chunks": self.hot_chunks,
            "issues": self.issues,
            "strengths": self.strengths,
        }

    def _write_report(self, report_path: str, result: dict) -> None:
        p = Path(report_path)
        p.parent.mkdir(parents=True, exist_ok=True)

        lines: list[str] = []
        lines.append("# DocKG Thorough Analysis")
        lines.append("")
        lines.append(f"Generated: `{result['timestamp']}`")
        lines.append(f"Elapsed: `{result['elapsed_seconds']}s`")
        lines.append("")

        stats = result["stats"]
        lines.append("## Baseline")
        lines.append("")
        lines.append(f"- Nodes: **{stats.get('total_nodes', 0)}**")
        lines.append(f"- Edges: **{stats.get('total_edges', 0)}**")
        lines.append("")

        lines.append("## Semantic Coverage")
        lines.append("")
        cov = result["semantic_coverage"]
        lines.append(f"- Topic coverage: **{cov.get('topic_coverage', 0.0):.1%}**")
        lines.append(f"- Entity coverage: **{cov.get('entity_coverage', 0.0):.1%}**")
        lines.append(f"- Keyword coverage: **{cov.get('keyword_coverage', 0.0):.1%}**")
        lines.append("")

        lines.append("## Top Documents By Chunk Count")
        lines.append("")
        lines.append("| File | Chunks | Sections | References | Semantic Links |")
        lines.append("|---|---:|---:|---:|---:|")
        for m in result["document_metrics"][:15]:
            lines.append(
                f"| `{m['file_path']}` | {m['chunks']} | {m['sections']} | {m['refs_out']} | {m['semantic_links']} |"
            )
        lines.append("")

        lines.append("## Hot Chunks")
        lines.append("")
        lines.append("| Chunk ID | File | Semantic Links | References |")
        lines.append("|---|---|---:|---:|")
        for c in result["hot_chunks"]:
            lines.append(
                f"| `{c['id']}` | `{c['file_path']}` | {c['semantic_links']} | {c['references']} |"
            )
        lines.append("")

        if result["issues"]:
            lines.append("## Issues")
            lines.append("")
            for item in result["issues"]:
                lines.append(f"- {item}")
            lines.append("")

        if result["strengths"]:
            lines.append("## Strengths")
            lines.append("")
            for item in result["strengths"]:
                lines.append(f"- {item}")
            lines.append("")

        p.write_text("\n".join(lines), encoding="utf-8")


def _default_report_path(corpus_root: Path) -> str:
    stamp = datetime.datetime.now().strftime("%Y%m%d")
    return str(corpus_root / "analysis" / f"doc_kg_analysis_{stamp}.md")


def _default_json_path() -> str:
    return str(Path.home() / ".claude" / "dockg_analysis_latest.json")


def _print_summary(console: Console, result: dict) -> None:
    stats = result.get("stats", {})
    cov = result.get("semantic_coverage", {})

    table = Table(title="DocKG Analysis Summary")
    table.add_column("Metric")
    table.add_column("Value", justify="right")

    table.add_row("Total nodes", str(stats.get("total_nodes", 0)))
    table.add_row("Total edges", str(stats.get("total_edges", 0)))
    table.add_row("Topic coverage", f"{cov.get('topic_coverage', 0.0):.1%}")
    table.add_row("Entity coverage", f"{cov.get('entity_coverage', 0.0):.1%}")
    table.add_row("Keyword coverage", f"{cov.get('keyword_coverage', 0.0):.1%}")

    console.print(table)


def main(
    corpus_root: str = ".",
    db_path: str | None = None,
    lancedb_path: str | None = None,
    report_path: str | None = None,
    json_path: str | None = None,
    quiet: bool = False,
) -> dict:
    """Run thorough DocKG analysis and write Markdown + JSON outputs.

    :param corpus_root: Corpus root path.
    :param db_path: SQLite database path.
    :param lancedb_path: LanceDB directory path.
    :param report_path: Markdown report output path.
    :param json_path: JSON output path.
    :param quiet: Suppress Rich summary output.
    :return: Analysis result dictionary.
    """
    console = Console()
    root = Path(corpus_root).resolve()
    db = Path(db_path) if db_path else (root / ".dockg" / "graph.sqlite")
    lancedb = Path(lancedb_path) if lancedb_path else (root / ".dockg" / "lancedb")

    kg = DocKG(corpus_root=root, db_path=db, lancedb_dir=lancedb)
    analyzer = DocKGAnalyzer(kg, console=console)

    report_out = report_path or _default_report_path(root)
    json_out = json_path or _default_json_path()

    result = analyzer.run_analysis(report_path=report_out)

    json_target = Path(json_out)
    json_target.parent.mkdir(parents=True, exist_ok=True)
    json_target.write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    if not quiet:
        _print_summary(console, result)

    console.print(f"[green]Report:[/green] {report_out}")
    console.print(f"[green]JSON:[/green] {json_out}")

    kg.close()
    return result
