"""
snapshots.py — Temporal Snapshots of DocKG Metrics

Author: Eric G. Suchanek, PhD
License: Elastic-2.0

Thin layer over the shared ``kg_utils.snapshots`` module.

``Snapshot``, ``SnapshotManifest`` and ``PruneResult`` are re-exported from
``kg_utils.snapshots`` unchanged.  A snapshot's ``metrics``, ``vs_previous``
and ``vs_baseline`` are plain dicts, which is what the shared manager reads
and writes.

This module adds:

  - ``SnapshotMetrics`` / ``SnapshotDelta`` — domain dataclasses, used as
    converters by callers that want attribute access.  Convert with
    ``metrics_from_dict`` / ``metrics_to_dict`` and ``delta_from_dict`` /
    ``delta_to_dict``; a ``Snapshot`` never holds one.
  - a ``SnapshotManager`` subclass that sets ``package_name="doc-kg"``, builds
    the DocKG metrics dict in ``capture()``, adds ``coverage_delta`` and
    ``issues_delta`` to deltas, ignores ``db_path`` when deciding whether
    metrics changed, and adds ``timestamp`` to each side of a diff.

Do not subclass ``Snapshot`` here.  A subclass that exposes ``metrics``,
``vs_previous`` or ``vs_baseline`` as properties breaks every shared manager
method that reads those fields by attribute, and each one then needs a
hand-written copy.  One such copy dropped ``snapshot_key``, ``subject`` and
``tool`` on the way to disk, which shipped in 0.24.0.

Usage
-----
>>> from doc_kg.snapshots import SnapshotManager, metrics_from_dict
>>> mgr = SnapshotManager(".dockg/snapshots")
>>> snapshot = mgr.capture(version="0.3.0", key="v0.3.0", subject="repo:doc-kg")
>>> mgr.save_snapshot(snapshot)
>>> metrics_from_dict(snapshot.metrics).total_nodes
0
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Re-export shared base types (public API)
# ---------------------------------------------------------------------------
from kg_utils.snapshots import (
    PruneResult,  # noqa: F401  re-exported
    Snapshot,  # noqa: F401  re-exported
    SnapshotManifest,  # noqa: F401  re-exported
)
from kg_utils.snapshots import SnapshotManager as _BaseSnapshotManager

__all__ = [
    "SnapshotMetrics",
    "SnapshotDelta",
    "Snapshot",
    "SnapshotManifest",
    "SnapshotManager",
    "PruneResult",
    "metrics_to_dict",
    "metrics_from_dict",
    "delta_to_dict",
    "delta_from_dict",
]


# ---------------------------------------------------------------------------
# Domain dataclasses — converters, not storage
# ---------------------------------------------------------------------------


@dataclass
class SnapshotMetrics:
    """Core metrics captured in a DocKG snapshot."""

    total_nodes: int
    total_edges: int
    meaningful_nodes: int
    coverage_score: float  # 0.0 to 1.0 — semantic coverage
    node_counts: dict[str, int]
    edge_counts: dict[str, int]
    issues_count: int
    complexity_median: float  # median semantic_links across hot chunks


@dataclass
class SnapshotDelta:
    """Deltas comparing this snapshot to a baseline or previous snapshot."""

    nodes: int = 0
    edges: int = 0
    coverage_delta: float = 0.0
    issues_delta: int = 0


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------


def metrics_to_dict(m: SnapshotMetrics) -> dict[str, Any]:
    """Convert a ``SnapshotMetrics`` dataclass to a plain dict."""
    return {
        "total_nodes": m.total_nodes,
        "total_edges": m.total_edges,
        "meaningful_nodes": m.meaningful_nodes,
        "coverage_score": m.coverage_score,
        "node_counts": m.node_counts,
        "edge_counts": m.edge_counts,
        "issues_count": m.issues_count,
        "complexity_median": m.complexity_median,
    }


def metrics_from_dict(d: dict[str, Any]) -> SnapshotMetrics:
    """Reconstruct a ``SnapshotMetrics`` dataclass from a plain dict."""
    return SnapshotMetrics(
        total_nodes=int(d.get("total_nodes", 0)),
        total_edges=int(d.get("total_edges", 0)),
        meaningful_nodes=int(d.get("meaningful_nodes", 0)),
        coverage_score=float(d.get("coverage_score", 0.0)),
        node_counts=d.get("node_counts", {}),
        edge_counts=d.get("edge_counts", {}),
        issues_count=int(d.get("issues_count", 0)),
        complexity_median=float(d.get("complexity_median", 0.0)),
    )


def delta_to_dict(delta: SnapshotDelta | None) -> dict[str, Any] | None:
    """Convert a ``SnapshotDelta`` to a plain dict, or return ``None``."""
    if delta is None:
        return None
    return {
        "nodes": delta.nodes,
        "edges": delta.edges,
        "coverage_delta": delta.coverage_delta,
        "issues_delta": delta.issues_delta,
    }


def delta_from_dict(d: dict[str, Any] | None) -> SnapshotDelta | None:
    """Reconstruct a ``SnapshotDelta`` from a plain dict, or return ``None``."""
    if d is None:
        return None
    return SnapshotDelta(
        nodes=int(d.get("nodes", 0)),
        edges=int(d.get("edges", 0)),
        coverage_delta=float(d.get("coverage_delta", 0.0)),
        issues_delta=int(d.get("issues_delta", 0)),
    )


# ---------------------------------------------------------------------------
# SnapshotManager — doc-kg specialisation of the shared manager
# ---------------------------------------------------------------------------


class SnapshotManager(_BaseSnapshotManager):
    """DocKG snapshot manager.

    Subclasses the shared ``kg_utils.snapshots.SnapshotManager`` and adds:

    * ``package_name="doc-kg"`` default for version detection.
    * A ``capture()`` that derives ``meaningful_nodes`` and coerces the
      DocKG metric fields (``coverage_score``, ``issues_count``,
      ``complexity_median``).
    * ``_compute_delta_from_metrics`` extended with ``coverage_delta`` and
      ``issues_delta``.
    * ``_metrics_changed`` ignoring the volatile ``db_path`` field.
    * ``diff_snapshots`` adding ``timestamp`` to each side.

    Everything else -- saving, loading, listing, pruning, key handling -- is
    inherited unchanged.  Overriding those to convert between dicts and the
    domain dataclasses is what this module used to do, and is what let the
    0.24.0 snapshot key regression through.
    """

    def __init__(
        self,
        snapshots_dir: Path | str,
        *,
        package_name: str = "doc-kg",
        db_path: Path | str | None = None,
    ) -> None:
        """Initialize the manager rooted at ``snapshots_dir``.

        :param snapshots_dir: Directory holding snapshot JSON and the manifest.
        :param package_name: Package name used for version detection.
        :param db_path: Optional DocKG SQLite path, recorded in metrics.
        """
        super().__init__(snapshots_dir, package_name=package_name, db_path=db_path)

    # ------------------------------------------------------------------
    # capture — build the DocKG metrics dict
    # ------------------------------------------------------------------

    def capture(
        self,
        version: str | None = None,
        branch: str | None = None,
        graph_stats_dict: dict[str, Any] | None = None,
        tree_hash: str = "",
        hotspots: list[dict[str, Any]] | None = None,
        issues: list[str] | None = None,
        key: str = "",
        subject: str = "",
        **extra_metrics: Any,
    ) -> Snapshot:
        """Capture a DocKG snapshot.

        Derives ``meaningful_nodes`` from the graph stats and coerces the
        DocKG metric fields, then delegates to the shared implementation.

        :param version: Version string (e.g., "0.3.0").
        :param branch: Git branch name; auto-detected if None.
        :param graph_stats_dict: Output from ``graph_stats()`` / ``store.stats()``.
        :param tree_hash: Git tree hash, recorded as provenance; auto-detected
            if not provided. It is not the snapshot's key.
        :param hotspots: Top hot chunks with metadata.
        :param issues: List of issue description strings.
        :param key: Snapshot identifier. Pass the release tag at release time;
            omit it and the base assigns a UTC timestamp. Named explicitly
            rather than left to ``**extra_metrics``, which would silently
            record it as a metric instead of passing it to the base.
        :param subject: What was measured, e.g. ``repo:doc-kg`` or
            ``corpus:pepys``. Explicit for the same reason.
        :param extra_metrics: Domain-specific fields; recognised keys are
            ``coverage_score`` (float), ``issues_count`` (int), and
            ``complexity_median`` (float).
        :return: New :class:`~kg_utils.snapshots.Snapshot` (not yet persisted).
        """
        stats = graph_stats_dict or {}
        node_counts = stats.get("node_counts", {})
        meaningful_nodes = max(
            0,
            int(stats.get("total_nodes", 0)) - int(node_counts.get("document", 0)),
        )

        extra: dict[str, Any] = {
            "meaningful_nodes": meaningful_nodes,
            "coverage_score": float(extra_metrics.pop("coverage_score", 0.0)),
            "issues_count": int(extra_metrics.pop("issues_count", 0)),
            "complexity_median": float(extra_metrics.pop("complexity_median", 0.0)),
            **extra_metrics,
        }

        return super().capture(
            version=version,
            branch=branch,
            graph_stats_dict=stats,
            tree_hash=tree_hash,
            key=key,
            subject=subject,
            hotspots=hotspots,
            issues=issues,
            **extra,
        )

    # ------------------------------------------------------------------
    # diff_snapshots — add the timestamp the CLI prints
    # ------------------------------------------------------------------

    def diff_snapshots(self, key_a: str, key_b: str) -> dict[str, Any]:
        """Compare two snapshots, adding ``timestamp`` to each side.

        :param key_a: Earlier snapshot key.
        :param key_b: Later snapshot key.
        :return: The shared diff result with ``a['timestamp']`` and
            ``b['timestamp']`` filled in.
        """
        result = super().diff_snapshots(key_a, key_b)
        if "error" in result:
            return result

        for side, key in (("a", key_a), ("b", key_b)):
            snap = self.load_snapshot(key)
            if snap is not None:
                result[side]["timestamp"] = snap.timestamp
        return result

    # ------------------------------------------------------------------
    # Prune — ignore db_path when comparing metrics for duplicate detection
    # ------------------------------------------------------------------

    _METRICS_IGNORE = frozenset({"db_path"})

    def _metrics_changed(self, new_metrics: dict[str, Any], old_metrics: dict[str, Any]) -> bool:
        """Return True if meaningful metrics changed, ignoring volatile fields like db_path."""
        strip = self._METRICS_IGNORE
        a = {k: v for k, v in new_metrics.items() if k not in strip}
        b = {k: v for k, v in old_metrics.items() if k not in strip}
        return a != b

    # ------------------------------------------------------------------
    # Delta computation — adds coverage_delta and issues_delta
    # ------------------------------------------------------------------

    def _compute_delta_from_metrics(
        self, new_m: dict[str, Any], old_m: dict[str, Any]
    ) -> dict[str, Any]:
        """Compute delta dict including doc-kg specific fields."""
        return {
            "nodes": new_m.get("total_nodes", 0) - old_m.get("total_nodes", 0),
            "edges": new_m.get("total_edges", 0) - old_m.get("total_edges", 0),
            "coverage_delta": (new_m.get("coverage_score", 0.0) - old_m.get("coverage_score", 0.0)),
            "issues_delta": new_m.get("issues_count", 0) - old_m.get("issues_count", 0),
        }
