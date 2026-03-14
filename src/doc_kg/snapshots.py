"""
snapshots.py - Temporal snapshots of DocKG metrics.

Adapted from CodeKG snapshots for document-graph evolution tracking.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass
class SnapshotMetrics:
    """Core metrics captured in a snapshot."""

    total_nodes: int
    total_edges: int
    meaningful_nodes: int
    coverage_score: float
    node_counts: dict[str, int]
    edge_counts: dict[str, int]
    issues_count: int
    complexity_median: float


@dataclass
class SnapshotDelta:
    """Deltas comparing this snapshot to another snapshot."""

    nodes: int = 0
    edges: int = 0
    coverage_delta: float = 0.0
    issues_delta: int = 0


@dataclass
class Snapshot:
    """A temporal snapshot of DocKG metrics and analysis results."""

    commit: str
    branch: str
    timestamp: str
    version: str
    metrics: SnapshotMetrics
    hotspots: list[dict[str, Any]] = field(default_factory=list)
    vs_previous: SnapshotDelta | None = None
    vs_baseline: SnapshotDelta | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert snapshot to a JSON-serializable dictionary."""
        return {
            "commit": self.commit,
            "branch": self.branch,
            "timestamp": self.timestamp,
            "version": self.version,
            "metrics": asdict(self.metrics),
            "hotspots": self.hotspots,
            "vs_previous": asdict(self.vs_previous) if self.vs_previous else None,
            "vs_baseline": asdict(self.vs_baseline) if self.vs_baseline else None,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> Snapshot:
        """Reconstruct snapshot from dictionary data."""
        metrics_data = data.pop("metrics")
        metrics = SnapshotMetrics(**metrics_data)

        vs_prev_data = data.pop("vs_previous")
        vs_prev = SnapshotDelta(**vs_prev_data) if vs_prev_data else None

        vs_base_data = data.pop("vs_baseline")
        vs_base = SnapshotDelta(**vs_base_data) if vs_base_data else None

        return Snapshot(metrics=metrics, vs_previous=vs_prev, vs_baseline=vs_base, **data)


@dataclass
class SnapshotManifest:
    """Index of snapshots for fast listing and lookup."""

    format_version: str = "1.0"
    last_update: str = ""
    snapshots: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialise the manifest to a JSON-compatible dictionary."""
        return {
            "format": self.format_version,
            "last_update": self.last_update,
            "snapshots": self.snapshots,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> SnapshotManifest:
        """Deserialise a manifest from a JSON-compatible dictionary."""
        return SnapshotManifest(
            format_version=data.get("format", "1.0"),
            last_update=data.get("last_update", ""),
            snapshots=data.get("snapshots", []),
        )


class SnapshotManager:
    """Manage snapshot capture, persistence, and comparison."""

    def __init__(self, snapshots_dir: Path | str):
        self.snapshots_dir = Path(snapshots_dir)
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.snapshots_dir / "manifest.json"

    def capture(
        self,
        version: str,
        commit: str | None = None,
        branch: str | None = None,
        graph_stats_dict: dict[str, Any] | None = None,
        coverage_score: float = 0.0,
        issues_count: int = 0,
        complexity_median: float = 0.0,
        hotspots: list[dict[str, Any]] | None = None,
    ) -> Snapshot:
        """Capture a snapshot from current metrics and analysis output."""
        if commit is None:
            commit = self._get_current_commit()
        if branch is None:
            branch = self._get_current_branch()

        stats = graph_stats_dict or {}
        node_counts = stats.get("node_counts", {})
        meaningful_nodes = int(stats.get("total_nodes", 0)) - int(node_counts.get("document", 0))

        metrics = SnapshotMetrics(
            total_nodes=int(stats.get("total_nodes", 0)),
            total_edges=int(stats.get("total_edges", 0)),
            meaningful_nodes=max(0, meaningful_nodes),
            coverage_score=float(coverage_score),
            node_counts=node_counts,
            edge_counts=stats.get("edge_counts", {}),
            issues_count=int(issues_count),
            complexity_median=float(complexity_median),
        )

        snapshot = Snapshot(
            commit=commit,
            branch=branch,
            timestamp=datetime.now(UTC).isoformat(),
            version=version,
            metrics=metrics,
            hotspots=hotspots or [],
        )

        prev = self.get_previous(commit)
        if prev:
            snapshot.vs_previous = self._compute_delta(snapshot, prev)

        baseline = self.get_baseline()
        if baseline:
            snapshot.vs_baseline = self._compute_delta(snapshot, baseline)

        return snapshot

    def save_snapshot(self, snapshot: Snapshot) -> Path:
        """Save snapshot JSON and update manifest."""
        snapshot_file = self.snapshots_dir / f"{snapshot.commit}.json"
        snapshot_file.write_text(json.dumps(snapshot.to_dict(), indent=2), encoding="utf-8")

        manifest = self.load_manifest()
        existing_idx = next(
            (i for i, s in enumerate(manifest.snapshots) if s["commit"] == snapshot.commit),
            None,
        )

        manifest_entry = {
            "commit": snapshot.commit,
            "branch": snapshot.branch,
            "timestamp": snapshot.timestamp,
            "version": snapshot.version,
            "file": snapshot_file.name,
            "metrics": {
                "nodes": snapshot.metrics.total_nodes,
                "edges": snapshot.metrics.total_edges,
                "coverage": snapshot.metrics.coverage_score,
                "issues": snapshot.metrics.issues_count,
            },
            "deltas": {
                "vs_previous": (asdict(snapshot.vs_previous) if snapshot.vs_previous else None),
                "vs_baseline": (asdict(snapshot.vs_baseline) if snapshot.vs_baseline else None),
            },
        }

        if existing_idx is not None:
            manifest.snapshots[existing_idx] = manifest_entry
        else:
            manifest.snapshots.append(manifest_entry)

        manifest.last_update = datetime.now(UTC).isoformat()
        self._save_manifest(manifest)
        return snapshot_file

    def load_manifest(self) -> SnapshotManifest:
        """Load snapshot manifest from disk."""
        if not self.manifest_path.exists():
            return SnapshotManifest()
        return SnapshotManifest.from_dict(
            json.loads(self.manifest_path.read_text(encoding="utf-8"))
        )

    def _save_manifest(self, manifest: SnapshotManifest) -> None:
        self.manifest_path.write_text(json.dumps(manifest.to_dict(), indent=2), encoding="utf-8")

    def load_snapshot(self, commit: str) -> Snapshot | None:
        """Load a snapshot by commit hash."""
        snapshot_file = self.snapshots_dir / f"{commit}.json"
        if not snapshot_file.exists():
            return None
        return Snapshot.from_dict(json.loads(snapshot_file.read_text(encoding="utf-8")))

    def get_previous(self, commit: str) -> Snapshot | None:
        """Get the snapshot immediately before this commit by timestamp."""
        manifest = self.load_manifest()
        current_ts = next(
            (s["timestamp"] for s in manifest.snapshots if s["commit"] == commit), None
        )
        if not current_ts:
            return None

        prev_entry = None
        for snap in sorted(manifest.snapshots, key=lambda x: x["timestamp"], reverse=True):
            if snap["timestamp"] < current_ts:
                prev_entry = snap
                break

        if prev_entry:
            return self.load_snapshot(prev_entry["commit"])
        return None

    def get_baseline(self) -> Snapshot | None:
        """Get the oldest snapshot in the manifest."""
        manifest = self.load_manifest()
        if not manifest.snapshots:
            return None
        baseline_entry = min(manifest.snapshots, key=lambda x: x["timestamp"])
        return self.load_snapshot(baseline_entry["commit"])

    def list_snapshots(self, limit: int | None = None) -> list[dict[str, Any]]:
        """List snapshots in reverse chronological order."""
        manifest = self.load_manifest()
        snapshots = sorted(manifest.snapshots, key=lambda x: x["timestamp"], reverse=True)
        return snapshots[:limit] if limit else snapshots

    def diff_snapshots(self, commit_a: str, commit_b: str) -> dict[str, Any]:
        """Compare two snapshots and return side-by-side metrics and delta."""
        snap_a = self.load_snapshot(commit_a)
        snap_b = self.load_snapshot(commit_b)

        if not snap_a or not snap_b:
            return {"error": "One or both snapshots not found"}

        return {
            "a": {"commit": commit_a, "metrics": asdict(snap_a.metrics)},
            "b": {"commit": commit_b, "metrics": asdict(snap_b.metrics)},
            "delta": asdict(self._compute_delta(snap_b, snap_a)),
        }

    @staticmethod
    def _compute_delta(snap_new: Snapshot, snap_old: Snapshot) -> SnapshotDelta:
        """Compute (new - old) delta."""
        return SnapshotDelta(
            nodes=snap_new.metrics.total_nodes - snap_old.metrics.total_nodes,
            edges=snap_new.metrics.total_edges - snap_old.metrics.total_edges,
            coverage_delta=snap_new.metrics.coverage_score - snap_old.metrics.coverage_score,
            issues_delta=snap_new.metrics.issues_count - snap_old.metrics.issues_count,
        )

    @staticmethod
    def _get_current_commit() -> str:
        try:
            return subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
            ).strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            return "unknown"

    @staticmethod
    def _get_current_branch() -> str:
        try:
            return subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            return "unknown"
