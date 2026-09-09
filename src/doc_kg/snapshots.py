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
    the DocKG metrics dict in ``_domain_metrics()``, adds ``coverage_delta`` and
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

    #: Version detection reads this; the base records it as the snapshot's
    #: ``tool``. Replaces an ``__init__`` that only forwarded to ``super()``.
    package_name = "doc-kg"

    #: ``db_path`` is where the graph happened to live when the snapshot was
    #: taken, not something measured, so two snapshots differing only in it are
    #: duplicates. Consumed by the base ``_metrics_changed``.
    metrics_ignore = frozenset({"db_path"})

    # ------------------------------------------------------------------
    # Capture-time metrics derived by this module
    # ------------------------------------------------------------------

    def _domain_metrics(self, stats: dict[str, Any]) -> dict[str, Any]:
        """Derive the DocKG metric fields from the graph stats.

        Called by the inherited ``capture()``. Overriding this rather than
        ``capture()`` is deliberate: a ``capture()`` override has to restate the
        base signature, and restating it is how an unnamed ``key=`` fell into
        ``**extra_metrics`` and shipped 0.24.0 with every snapshot keyed on a
        tree hash.

        The three zero values are defaults, not measurements. Anything the
        caller passes to ``capture()`` overrides them, which is how
        ``cmd_snapshot`` supplies the real numbers; they exist so a snapshot
        taken without them still carries the keys.

        :param stats: Graph stats passed to ``capture()``.
        :return: ``meaningful_nodes`` plus defaults for the DocKG metrics.
        """
        node_counts = stats.get("node_counts", {})
        return {
            "meaningful_nodes": max(
                0,
                int(stats.get("total_nodes", 0)) - int(node_counts.get("document", 0)),
            ),
            "coverage_score": 0.0,
            "issues_count": 0,
            "complexity_median": 0.0,
        }

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
