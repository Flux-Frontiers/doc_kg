"""
snapshots.py — Temporal Snapshots of DocKG Metrics

Provides infrastructure for capturing, storing, and comparing metrics snapshots.
Each snapshot is keyed by git tree hash and contains:
  - Timestamp and branch metadata
  - Full graph_stats() output
  - Semantic coverage metrics
  - Complexity hotspots (top semantically-linked chunks)
  - Issues list
  - Deltas vs. previous and baseline snapshots

Snapshots are stored in .dockg/snapshots/ as JSON blobs, with a manifest
index (manifest.json) tracking all snapshots and their metadata.

Usage
-----
>>> from doc_kg.snapshots import SnapshotManager
>>> mgr = SnapshotManager(".dockg/snapshots")
>>> snapshot = mgr.capture("v0.3.0", "main", graph_stats_dict)
>>> mgr.save_snapshot(snapshot)
>>> manifest = mgr.load_manifest()
>>> prev = mgr.get_previous(tree_hash)
"""

from __future__ import annotations

import importlib.metadata
import json
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _package_version() -> str:
    """Return the installed doc-kg package version, or 'unknown'."""
    try:
        return importlib.metadata.version("doc-kg")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


@dataclass
class SnapshotMetrics:
    """Core metrics captured in a snapshot."""

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


@dataclass
class Snapshot:
    """A temporal snapshot of DocKG metrics and analysis results."""

    branch: str  # git branch name
    timestamp: str  # ISO 8601 UTC
    metrics: SnapshotMetrics
    version: str = ""  # e.g., "0.3.0"; auto-detected from package if not supplied
    hotspots: list[dict[str, Any]] = field(default_factory=list)  # top hot chunks
    issues: list[str] = field(default_factory=list)  # issue description strings
    vs_previous: SnapshotDelta | None = None
    vs_baseline: SnapshotDelta | None = None
    tree_hash: str = ""  # git tree hash; stable file key

    @property
    def key(self) -> str:
        """Stable file key: git tree hash."""
        return self.tree_hash

    def to_dict(self) -> dict[str, Any]:
        """Convert snapshot to a JSON-serializable dictionary."""
        return {
            "key": self.tree_hash,
            "branch": self.branch,
            "timestamp": self.timestamp,
            "version": self.version,
            "metrics": asdict(self.metrics),
            "hotspots": self.hotspots,
            "issues": self.issues,
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

        key = data.pop("key", "")
        data.pop("commit", None)  # drop legacy commit field
        data.setdefault("version", "")

        return Snapshot(
            tree_hash=key,
            metrics=metrics,
            vs_previous=vs_prev,
            vs_baseline=vs_base,
            **data,
        )


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
        version: str | None = None,
        branch: str | None = None,
        graph_stats_dict: dict[str, Any] | None = None,
        coverage_score: float = 0.0,
        issues_count: int = 0,
        complexity_median: float = 0.0,
        hotspots: list[dict[str, Any]] | None = None,
        issues: list[str] | None = None,
        tree_hash: str = "",
    ) -> Snapshot:
        """Capture a snapshot from current metrics and analysis output.

        :param version: Version string (e.g., "0.3.0").
        :param branch: Git branch name; auto-detected if None.
        :param graph_stats_dict: Output from graph_stats() tool or store.stats().
        :param coverage_score: Semantic coverage score (0.0 to 1.0).
        :param issues_count: Number of issues found.
        :param complexity_median: Median semantic_links across hot chunks.
        :param hotspots: Top hot chunks with metadata.
        :param issues: List of issue description strings.
        :param tree_hash: Git tree hash; auto-detected if not provided.
        :return: New Snapshot instance.
        """
        if not version:
            version = _package_version()
        if branch is None:
            branch = self._get_current_branch()
        if not tree_hash:
            tree_hash = self._get_current_tree_hash()

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
            branch=branch,
            timestamp=datetime.now(UTC).isoformat(),
            version=version,
            metrics=metrics,
            hotspots=hotspots or [],
            issues=issues or [],
            tree_hash=tree_hash,
        )

        prev = self.get_previous(tree_hash)
        if prev:
            snapshot.vs_previous = self._compute_delta(snapshot, prev)

        baseline = self.get_baseline()
        if baseline:
            snapshot.vs_baseline = self._compute_delta(snapshot, baseline)

        return snapshot

    def save_snapshot(self, snapshot: Snapshot) -> Path:
        """Save snapshot to .dockg/snapshots/{key}.json and update manifest.

        Snapshots with zero nodes are rejected — they represent a build that
        hadn't run yet and would skew delta comparisons.

        :param snapshot: Snapshot to save.
        :return: Path to saved snapshot file.
        :raises ValueError: If the snapshot has zero nodes (degenerate state).
        """
        if snapshot.metrics.total_nodes == 0:
            raise ValueError(
                "Refusing to save degenerate snapshot with 0 nodes. "
                "Run 'dockg build' before capturing a snapshot."
            )

        snapshot_file = self.snapshots_dir / f"{snapshot.key}.json"
        snapshot_file.write_text(json.dumps(snapshot.to_dict(), indent=2), encoding="utf-8")

        manifest = self.load_manifest()
        existing_idx = next(
            (i for i, s in enumerate(manifest.snapshots) if s.get("key") == snapshot.key),
            None,
        )

        manifest_entry = {
            "key": snapshot.key,
            "branch": snapshot.branch,
            "timestamp": snapshot.timestamp,
            "version": snapshot.version,
            "file": snapshot_file.name,
            "metrics": asdict(snapshot.metrics),
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

    def load_snapshot(self, key: str) -> Snapshot | None:
        """Load a snapshot by key (tree hash)."""
        snapshot_file = self.snapshots_dir / f"{key}.json"
        if not snapshot_file.exists():
            return None
        snap = Snapshot.from_dict(json.loads(snapshot_file.read_text(encoding="utf-8")))

        # Backfill deltas for snapshots that predate persisted deltas
        if snap.vs_previous is None or snap.vs_baseline is None:
            manifest = self.load_manifest()
            entries = sorted(
                manifest.snapshots,
                key=lambda x: x.get("timestamp", ""),
                reverse=True,
            )
            idx = next((i for i, s in enumerate(entries) if s.get("key") == key), None)

            if idx is not None:
                if snap.vs_previous is None and idx + 1 < len(entries):
                    prev_m = entries[idx + 1].get("metrics", {})
                    snap.vs_previous = SnapshotDelta(
                        nodes=snap.metrics.total_nodes - prev_m.get("total_nodes", 0),
                        edges=snap.metrics.total_edges - prev_m.get("total_edges", 0),
                        coverage_delta=(
                            snap.metrics.coverage_score - prev_m.get("coverage_score", 0.0)
                        ),
                        issues_delta=snap.metrics.issues_count - prev_m.get("issues_count", 0),
                    )

                if snap.vs_baseline is None and entries:
                    base_m = entries[-1].get("metrics", {})
                    snap.vs_baseline = SnapshotDelta(
                        nodes=snap.metrics.total_nodes - base_m.get("total_nodes", 0),
                        edges=snap.metrics.total_edges - base_m.get("total_edges", 0),
                        coverage_delta=(
                            snap.metrics.coverage_score - base_m.get("coverage_score", 0.0)
                        ),
                        issues_delta=snap.metrics.issues_count - base_m.get("issues_count", 0),
                    )

        return snap

    def get_previous(self, key: str) -> Snapshot | None:
        """Get the snapshot immediately before this one (by timestamp)."""
        manifest = self.load_manifest()
        current_ts = next((s["timestamp"] for s in manifest.snapshots if s.get("key") == key), None)
        if not current_ts:
            return None

        prev_entry = None
        for s in sorted(manifest.snapshots, key=lambda x: x["timestamp"], reverse=True):
            if s["timestamp"] < current_ts:
                prev_entry = s
                break

        if prev_entry:
            return self.load_snapshot(prev_entry["key"])
        return None

    def get_baseline(self) -> Snapshot | None:
        """Get the oldest snapshot in the manifest."""
        manifest = self.load_manifest()
        if not manifest.snapshots:
            return None
        baseline_entry = min(manifest.snapshots, key=lambda x: x["timestamp"])
        return self.load_snapshot(baseline_entry["key"])

    def list_snapshots(
        self,
        limit: int | None = None,
        branch: str | None = None,
    ) -> list[dict[str, Any]]:
        """List snapshots in reverse chronological order.

        Missing ``vs_previous`` deltas are computed on-the-fly from adjacent
        manifest entries so that every entry (except the oldest) carries a delta.

        :param limit: Max number to return; ``None`` = all.
        :param branch: If provided, only return snapshots from this branch.
        :return: List of snapshot metadata dicts.
        """
        manifest = self.load_manifest()
        all_snaps = sorted(manifest.snapshots, key=lambda x: x["timestamp"], reverse=True)

        if branch is not None:
            all_snaps = [s for s in all_snaps if s.get("branch") == branch]

        # Fill in missing vs_previous deltas from adjacent entries
        for i, snap in enumerate(all_snaps):
            if snap.get("deltas", {}).get("vs_previous") is None and i + 1 < len(all_snaps):
                prev = all_snaps[i + 1]
                snap.setdefault("deltas", {})["vs_previous"] = {
                    "nodes": snap["metrics"]["total_nodes"] - prev["metrics"]["total_nodes"],
                    "edges": snap["metrics"]["total_edges"] - prev["metrics"]["total_edges"],
                    "coverage_delta": (
                        snap["metrics"]["coverage_score"] - prev["metrics"]["coverage_score"]
                    ),
                    "issues_delta": (
                        snap["metrics"]["issues_count"] - prev["metrics"]["issues_count"]
                    ),
                }

        return all_snaps[:limit] if limit else all_snaps

    def diff_snapshots(self, key_a: str, key_b: str) -> dict[str, Any]:
        """Compare two snapshots and return side-by-side metrics and delta.

        :param key_a: First snapshot key (tree hash).
        :param key_b: Second snapshot key (tree hash).
        :return: Dict with metrics from both and computed delta.
        """
        snap_a = self.load_snapshot(key_a)
        snap_b = self.load_snapshot(key_b)

        if not snap_a or not snap_b:
            return {"error": "One or both snapshots not found"}

        return {
            "a": {
                "key": key_a,
                "branch": snap_a.branch,
                "timestamp": snap_a.timestamp,
                "version": snap_a.version,
                "metrics": asdict(snap_a.metrics),
            },
            "b": {
                "key": key_b,
                "branch": snap_b.branch,
                "timestamp": snap_b.timestamp,
                "version": snap_b.version,
                "metrics": asdict(snap_b.metrics),
            },
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
    def _get_current_tree_hash() -> str:
        """Get current git tree hash (HEAD^{tree})."""
        try:
            return subprocess.check_output(
                ["git", "rev-parse", "HEAD^{tree}"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            return ""

    @staticmethod
    def _get_current_branch() -> str:
        """Get current git branch name."""
        try:
            return subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            return "unknown"
