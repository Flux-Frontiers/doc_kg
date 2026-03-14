"""
test_snapshots.py

Tests for temporal snapshot capture, storage, and comparison:
  SnapshotMetrics, SnapshotDelta, Snapshot, SnapshotManifest, SnapshotManager
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from doc_kg.snapshots import (
    Snapshot,
    SnapshotDelta,
    SnapshotManager,
    SnapshotManifest,
    SnapshotMetrics,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def snapshot_dir(tmp_path: Path) -> Path:
    """Create temporary snapshots directory."""
    snapshots_path = tmp_path / "snapshots"
    snapshots_path.mkdir(parents=True, exist_ok=True)
    return snapshots_path


@pytest.fixture
def sample_metrics() -> SnapshotMetrics:
    """Create sample metrics for testing."""
    return SnapshotMetrics(
        total_nodes=100,
        total_edges=150,
        meaningful_nodes=80,
        coverage_score=0.85,
        node_counts={"document": 20, "chunk": 60},
        edge_counts={"CONTAINS": 80, "SIMILAR_TO": 50, "HAS_TOPIC": 20},
        issues_count=2,
        complexity_median=3.5,
    )


@pytest.fixture
def sample_snapshot(sample_metrics: SnapshotMetrics) -> Snapshot:
    """Create sample snapshot for testing."""
    return Snapshot(
        branch="main",
        timestamp="2026-03-12T12:00:00+00:00",
        version="0.3.0",
        metrics=sample_metrics,
        hotspots=[{"id": "chunk_a", "semantic_links": 5}, {"id": "chunk_b", "semantic_links": 3}],
        tree_hash="abc123def456",  # pragma: allowlist secret
    )


# ---------------------------------------------------------------------------
# SnapshotMetrics Tests
# ---------------------------------------------------------------------------


def test_snapshot_metrics_creation(sample_metrics: SnapshotMetrics) -> None:
    """Test SnapshotMetrics creation and properties."""
    assert sample_metrics.total_nodes == 100
    assert sample_metrics.total_edges == 150
    assert sample_metrics.meaningful_nodes == 80
    assert sample_metrics.coverage_score == 0.85
    assert sample_metrics.issues_count == 2
    assert sample_metrics.complexity_median == 3.5


def test_snapshot_metrics_node_counts(sample_metrics: SnapshotMetrics) -> None:
    """Test node count breakdown."""
    assert sample_metrics.node_counts["document"] == 20
    assert sample_metrics.node_counts["chunk"] == 60


def test_snapshot_metrics_edge_counts(sample_metrics: SnapshotMetrics) -> None:
    """Test edge count breakdown."""
    assert sample_metrics.edge_counts["CONTAINS"] == 80
    assert sample_metrics.edge_counts["SIMILAR_TO"] == 50
    assert sample_metrics.edge_counts["HAS_TOPIC"] == 20


# ---------------------------------------------------------------------------
# SnapshotDelta Tests
# ---------------------------------------------------------------------------


def test_snapshot_delta_creation() -> None:
    """Test SnapshotDelta creation."""
    delta = SnapshotDelta(nodes=10, edges=15, coverage_delta=0.02, issues_delta=-1)
    assert delta.nodes == 10
    assert delta.edges == 15
    assert delta.coverage_delta == pytest.approx(0.02)
    assert delta.issues_delta == -1


def test_snapshot_delta_defaults() -> None:
    """Test SnapshotDelta defaults."""
    delta = SnapshotDelta()
    assert delta.nodes == 0
    assert delta.edges == 0
    assert delta.coverage_delta == 0.0
    assert delta.issues_delta == 0


# ---------------------------------------------------------------------------
# Snapshot Tests
# ---------------------------------------------------------------------------


def test_snapshot_creation(sample_snapshot: Snapshot) -> None:
    """Test Snapshot creation and properties."""
    assert sample_snapshot.tree_hash == "abc123def456"  # pragma: allowlist secret
    assert sample_snapshot.key == "abc123def456"  # pragma: allowlist secret
    assert sample_snapshot.branch == "main"
    assert sample_snapshot.version == "0.3.0"
    assert sample_snapshot.metrics.total_nodes == 100
    assert len(sample_snapshot.hotspots) == 2


def test_snapshot_to_dict(sample_snapshot: Snapshot) -> None:
    """Test Snapshot serialization — key field present, commit absent."""
    snap_dict = sample_snapshot.to_dict()
    assert snap_dict["key"] == "abc123def456"  # pragma: allowlist secret
    assert "commit" not in snap_dict
    assert snap_dict["branch"] == "main"
    assert snap_dict["version"] == "0.3.0"
    assert snap_dict["metrics"]["total_nodes"] == 100
    assert len(snap_dict["hotspots"]) == 2


def test_snapshot_to_dict_contains_issues(sample_snapshot: Snapshot) -> None:
    """to_dict includes the issues list."""
    snap_dict = sample_snapshot.to_dict()
    assert "issues" in snap_dict
    assert isinstance(snap_dict["issues"], list)


def test_snapshot_to_dict_null_deltas(sample_snapshot: Snapshot) -> None:
    """to_dict serialises None deltas as null."""
    snap_dict = sample_snapshot.to_dict()
    assert snap_dict["vs_previous"] is None
    assert snap_dict["vs_baseline"] is None


def test_snapshot_from_dict(sample_snapshot: Snapshot) -> None:
    """Test Snapshot deserialization from dict."""
    snap_dict = sample_snapshot.to_dict()
    restored = Snapshot.from_dict(snap_dict)
    assert restored.tree_hash == sample_snapshot.tree_hash
    assert restored.branch == sample_snapshot.branch
    assert restored.version == sample_snapshot.version
    assert restored.metrics.total_nodes == sample_snapshot.metrics.total_nodes


def test_snapshot_roundtrip(sample_snapshot: Snapshot) -> None:
    """Test Snapshot serialize/deserialize roundtrip."""
    original_dict = sample_snapshot.to_dict()
    dict_copy = json.loads(json.dumps(original_dict))
    restored = Snapshot.from_dict(dict_copy)
    restored_dict = restored.to_dict()
    assert original_dict == restored_dict


def test_snapshot_with_deltas() -> None:
    """Test Snapshot with delta information."""
    metrics = SnapshotMetrics(
        total_nodes=100,
        total_edges=150,
        meaningful_nodes=80,
        coverage_score=0.85,
        node_counts={},
        edge_counts={},
        issues_count=2,
        complexity_median=3.5,
    )
    vs_prev = SnapshotDelta(nodes=10, edges=5, coverage_delta=0.01)
    vs_base = SnapshotDelta(nodes=20, edges=30, coverage_delta=0.05)

    snap = Snapshot(
        branch="main",
        timestamp="2026-03-12T12:00:00+00:00",
        version="0.3.0",
        metrics=metrics,
        vs_previous=vs_prev,
        vs_baseline=vs_base,
        tree_hash="abc123",
    )

    snap_dict = snap.to_dict()
    assert snap_dict["vs_previous"] is not None
    assert snap_dict["vs_baseline"] is not None

    restored = Snapshot.from_dict(snap_dict)
    assert restored.vs_previous is not None
    assert restored.vs_baseline is not None
    assert restored.vs_previous.nodes == 10


def test_snapshot_from_dict_drops_legacy_commit_field(
    sample_metrics: SnapshotMetrics,
) -> None:
    """from_dict silently discards the legacy 'commit' field."""
    snap_dict = {
        "key": "newhash123",
        "commit": "oldhash456",  # legacy — must be dropped
        "branch": "main",
        "timestamp": "2026-03-12T12:00:00+00:00",
        "version": "0.3.0",
        "metrics": {
            "total_nodes": 100,
            "total_edges": 150,
            "meaningful_nodes": 80,
            "coverage_score": 0.85,
            "node_counts": {},
            "edge_counts": {},
            "issues_count": 2,
            "complexity_median": 3.5,
        },
        "hotspots": [],
        "issues": [],
        "vs_previous": None,
        "vs_baseline": None,
    }
    snap = Snapshot.from_dict(snap_dict)
    assert snap.tree_hash == "newhash123"
    assert snap.key == "newhash123"


# ---------------------------------------------------------------------------
# SnapshotManager Tests
# ---------------------------------------------------------------------------


def test_snapshot_manager_creation(snapshot_dir: Path) -> None:
    """Test SnapshotManager initialization."""
    mgr = SnapshotManager(snapshot_dir)
    assert mgr.snapshots_dir == snapshot_dir
    assert mgr.manifest_path == snapshot_dir / "manifest.json"


def test_snapshot_manager_creates_directory(tmp_path: Path) -> None:
    """Test SnapshotManager creates directory if missing."""
    snapshots_path = tmp_path / "new_snapshots"
    assert not snapshots_path.exists()
    SnapshotManager(snapshots_path)
    assert snapshots_path.exists()
    assert snapshots_path.is_dir()


def test_snapshot_manager_capture(snapshot_dir: Path) -> None:
    """Test snapshot capture builds correct Snapshot."""
    mgr = SnapshotManager(snapshot_dir)

    with patch(
        "doc_kg.snapshots.SnapshotManager._get_current_tree_hash",
        return_value="abc123tree",  # pragma: allowlist secret
    ):
        with patch(
            "doc_kg.snapshots.SnapshotManager._get_current_branch",
            return_value="main",
        ):
            snap = mgr.capture(
                version="0.3.0",
                graph_stats_dict={
                    "total_nodes": 100,
                    "total_edges": 150,
                    "node_counts": {"document": 20, "chunk": 60},
                    "edge_counts": {"CONTAINS": 80},
                },
                coverage_score=0.85,
                issues_count=2,
                complexity_median=3.5,
            )

    assert snap.tree_hash == "abc123tree"  # pragma: allowlist secret
    assert snap.branch == "main"
    assert snap.version == "0.3.0"
    assert snap.metrics.total_nodes == 100


def test_snapshot_manager_capture_meaningful_nodes(snapshot_dir: Path) -> None:
    """meaningful_nodes = total_nodes - document count."""
    mgr = SnapshotManager(snapshot_dir)
    snap = mgr.capture(
        version="0.3.0",
        tree_hash="t1",
        branch="main",
        graph_stats_dict={
            "total_nodes": 120,
            "total_edges": 200,
            "node_counts": {"document": 10, "chunk": 80},
            "edge_counts": {},
        },
    )
    assert snap.metrics.meaningful_nodes == 110  # 120 - 10


def test_snapshot_manager_capture_with_hotspots_and_issues(snapshot_dir: Path) -> None:
    """capture passes through hotspots and issues lists."""
    mgr = SnapshotManager(snapshot_dir)
    hotspots = [{"id": "big_doc", "semantic_links": 12}]
    issues = ["Missing metadata on 3 documents"]
    snap = mgr.capture(
        version="0.3.0",
        tree_hash="t1",
        branch="main",
        hotspots=hotspots,
        issues=issues,
    )
    assert snap.hotspots == hotspots
    assert snap.issues == issues


def test_snapshot_manager_save_and_load(snapshot_dir: Path, sample_snapshot: Snapshot) -> None:
    """Test saving and loading snapshots."""
    mgr = SnapshotManager(snapshot_dir)

    saved_path = mgr.save_snapshot(sample_snapshot)
    assert saved_path.exists()
    assert saved_path.name == f"{sample_snapshot.key}.json"

    loaded = mgr.load_snapshot(sample_snapshot.key)
    assert loaded is not None
    assert loaded.tree_hash == sample_snapshot.tree_hash
    assert loaded.version == sample_snapshot.version


def test_snapshot_manager_manifest_created(snapshot_dir: Path, sample_snapshot: Snapshot) -> None:
    """manifest.json is created with key field (not commit)."""
    mgr = SnapshotManager(snapshot_dir)
    mgr.save_snapshot(sample_snapshot)

    assert mgr.manifest_path.exists()
    with open(mgr.manifest_path) as f:
        manifest_data = json.load(f)

    assert manifest_data["format"] == "1.0"
    assert len(manifest_data["snapshots"]) == 1
    assert manifest_data["snapshots"][0]["key"] == sample_snapshot.key
    assert "commit" not in manifest_data["snapshots"][0]


def test_save_snapshot_manifest_has_full_metrics(
    snapshot_dir: Path, sample_snapshot: Snapshot
) -> None:
    """Manifest entry stores the full SnapshotMetrics dict, not a summary."""
    mgr = SnapshotManager(snapshot_dir)
    mgr.save_snapshot(sample_snapshot)

    with open(mgr.manifest_path) as f:
        manifest_data = json.load(f)

    metrics = manifest_data["snapshots"][0]["metrics"]
    assert "total_nodes" in metrics
    assert "total_edges" in metrics
    assert "coverage_score" in metrics
    assert "node_counts" in metrics
    assert "edge_counts" in metrics
    assert "issues_count" in metrics
    # Old summary-only keys must not appear
    assert "nodes" not in metrics
    assert "edges" not in metrics
    assert "coverage" not in metrics
    assert "issues" not in metrics


def test_save_snapshot_zero_nodes_raises(snapshot_dir: Path) -> None:
    """save_snapshot raises ValueError for a degenerate (0-node) snapshot."""
    mgr = SnapshotManager(snapshot_dir)
    empty_metrics = SnapshotMetrics(
        total_nodes=0,
        total_edges=0,
        meaningful_nodes=0,
        coverage_score=0.0,
        node_counts={},
        edge_counts={},
        issues_count=0,
        complexity_median=0.0,
    )
    snap = Snapshot(
        branch="main",
        timestamp="2026-03-12T12:00:00+00:00",
        version="0.3.0",
        metrics=empty_metrics,
        tree_hash="emptyhash",
    )
    with pytest.raises(ValueError, match="0 nodes"):
        mgr.save_snapshot(snap)


def test_save_snapshot_same_key_updates_manifest_entry(
    snapshot_dir: Path, sample_metrics: SnapshotMetrics
) -> None:
    """Saving a snapshot with the same tree_hash updates the manifest entry in place."""
    mgr = SnapshotManager(snapshot_dir)

    snap_v1 = Snapshot(
        branch="main",
        timestamp="2026-03-12T12:00:00+00:00",
        version="0.3.0",
        metrics=sample_metrics,
        tree_hash="samehash",
    )
    mgr.save_snapshot(snap_v1)

    snap_v2 = Snapshot(
        branch="main",
        timestamp="2026-03-12T12:00:00+00:00",
        version="0.3.1",  # updated version
        metrics=sample_metrics,
        tree_hash="samehash",  # same key
    )
    mgr.save_snapshot(snap_v2)

    with open(mgr.manifest_path) as f:
        manifest_data = json.load(f)

    assert len(manifest_data["snapshots"]) == 1
    assert manifest_data["snapshots"][0]["version"] == "0.3.1"


def test_snapshot_manager_list_snapshots(snapshot_dir: Path) -> None:
    """List snapshots in reverse chronological order."""
    mgr = SnapshotManager(snapshot_dir)
    metrics = _make_metrics()

    snap1 = Snapshot(
        branch="main",
        timestamp="2026-03-07T10:00:00+00:00",
        version="0.3.0",
        metrics=metrics,
        tree_hash="treehash1",
    )
    snap2 = Snapshot(
        branch="main",
        timestamp="2026-03-07T12:00:00+00:00",
        version="0.3.1",
        metrics=metrics,
        tree_hash="treehash2",
    )

    mgr.save_snapshot(snap1)
    mgr.save_snapshot(snap2)

    snapshots = mgr.list_snapshots()
    assert len(snapshots) == 2
    assert snapshots[0]["timestamp"] > snapshots[1]["timestamp"]


def test_list_snapshots_with_limit(snapshot_dir: Path) -> None:
    """list_snapshots(limit=N) returns at most N entries."""
    mgr = SnapshotManager(snapshot_dir)
    for i in range(5):
        mgr.save_snapshot(
            Snapshot(
                branch="main",
                timestamp=f"2026-03-0{i + 1}T12:00:00+00:00",
                version=f"0.3.{i}",
                metrics=_make_metrics(),
                tree_hash=f"hash{i}",
            )
        )

    assert len(mgr.list_snapshots(limit=3)) == 3
    assert len(mgr.list_snapshots()) == 5


def test_list_snapshots_limit_zero_returns_all(snapshot_dir: Path) -> None:
    """limit=0 is falsy — manager returns all snapshots, not an empty list."""
    mgr = SnapshotManager(snapshot_dir)
    for i in range(3):
        mgr.save_snapshot(_make_dockg_snapshot(f"hash{i}", f"2026-03-0{i + 1}T12:00:00+00:00"))
    assert len(mgr.list_snapshots(limit=0)) == 3


def test_list_snapshots_branch_filter(snapshot_dir: Path) -> None:
    """list_snapshots(branch=...) returns only snapshots for that branch."""
    mgr = SnapshotManager(snapshot_dir)
    mgr.save_snapshot(
        Snapshot(
            branch="main",
            timestamp="2026-03-01T12:00:00+00:00",
            version="0.3.0",
            metrics=_make_metrics(),
            tree_hash="main1",
        )
    )
    mgr.save_snapshot(
        Snapshot(
            branch="develop",
            timestamp="2026-03-02T12:00:00+00:00",
            version="0.3.1",
            metrics=_make_metrics(),
            tree_hash="dev1",
        )
    )
    mgr.save_snapshot(
        Snapshot(
            branch="main",
            timestamp="2026-03-03T12:00:00+00:00",
            version="0.3.2",
            metrics=_make_metrics(),
            tree_hash="main2",
        )
    )

    main_snaps = mgr.list_snapshots(branch="main")
    assert len(main_snaps) == 2
    assert all(s["branch"] == "main" for s in main_snaps)

    dev_snaps = mgr.list_snapshots(branch="develop")
    assert len(dev_snaps) == 1
    assert dev_snaps[0]["key"] == "dev1"


def test_list_snapshots_empty(snapshot_dir: Path) -> None:
    """list_snapshots returns [] when no snapshots have been saved."""
    mgr = SnapshotManager(snapshot_dir)
    assert mgr.list_snapshots() == []


def test_snapshot_manager_diff_snapshots(snapshot_dir: Path) -> None:
    """diff_snapshots returns a, b, delta with correct values."""
    mgr = SnapshotManager(snapshot_dir)

    snap1 = Snapshot(
        branch="main",
        timestamp="2026-03-07T10:00:00+00:00",
        version="0.3.0",
        metrics=SnapshotMetrics(
            total_nodes=100,
            total_edges=150,
            meaningful_nodes=80,
            coverage_score=0.85,
            node_counts={},
            edge_counts={},
            issues_count=2,
            complexity_median=3.5,
        ),
        tree_hash="treehash1",
    )
    snap2 = Snapshot(
        branch="main",
        timestamp="2026-03-07T12:00:00+00:00",
        version="0.3.1",
        metrics=SnapshotMetrics(
            total_nodes=120,
            total_edges=170,
            meaningful_nodes=95,
            coverage_score=0.87,
            node_counts={},
            edge_counts={},
            issues_count=1,
            complexity_median=3.8,
        ),
        tree_hash="treehash2",
    )

    mgr.save_snapshot(snap1)
    mgr.save_snapshot(snap2)

    diff = mgr.diff_snapshots("treehash1", "treehash2")
    assert "a" in diff
    assert "b" in diff
    assert "delta" in diff
    assert diff["delta"]["nodes"] == 20
    assert diff["delta"]["edges"] == 20
    assert diff["delta"]["issues_delta"] == -1


def test_diff_snapshots_missing_key_returns_error(snapshot_dir: Path) -> None:
    """diff_snapshots returns an error dict when a key is not found."""
    mgr = SnapshotManager(snapshot_dir)
    result = mgr.diff_snapshots("nonexistent_a", "nonexistent_b")
    assert "error" in result


def test_diff_snapshots_one_missing_returns_error(snapshot_dir: Path) -> None:
    """diff_snapshots returns error when only one key is missing."""
    mgr = SnapshotManager(snapshot_dir)
    mgr.save_snapshot(_make_dockg_snapshot("hash_a", "2026-01-01T00:00:00+00:00"))
    result = mgr.diff_snapshots("hash_a", "nonexistent")
    assert "error" in result


def test_diff_snapshots_coverage_and_issues_delta(snapshot_dir: Path) -> None:
    """diff_snapshots includes coverage_delta and issues_delta."""
    mgr = SnapshotManager(snapshot_dir)

    s1 = Snapshot(
        branch="main",
        timestamp="2026-01-01T00:00:00+00:00",
        version="0.3.0",
        metrics=SnapshotMetrics(
            total_nodes=50,
            total_edges=80,
            meaningful_nodes=50,
            coverage_score=0.60,
            node_counts={},
            edge_counts={},
            issues_count=5,
            complexity_median=2.0,
        ),
        tree_hash="cov_a",
    )
    s2 = Snapshot(
        branch="main",
        timestamp="2026-02-01T00:00:00+00:00",
        version="0.3.1",
        metrics=SnapshotMetrics(
            total_nodes=50,
            total_edges=80,
            meaningful_nodes=50,
            coverage_score=0.80,
            node_counts={},
            edge_counts={},
            issues_count=2,
            complexity_median=2.0,
        ),
        tree_hash="cov_b",
    )
    mgr.save_snapshot(s1)
    mgr.save_snapshot(s2)

    result = mgr.diff_snapshots("cov_a", "cov_b")
    assert result["delta"]["coverage_delta"] == pytest.approx(0.20)
    assert result["delta"]["issues_delta"] == -3


def test_compute_delta_negative_regression(snapshot_dir: Path) -> None:
    """Delta is negative when the new snapshot has fewer nodes/edges."""
    mgr = SnapshotManager(snapshot_dir)
    s_big = _make_dockg_snapshot("big", "2026-01-01T00:00:00+00:00", nodes=100)
    s_small = _make_dockg_snapshot("small", "2026-02-01T00:00:00+00:00", nodes=60)
    mgr.save_snapshot(s_big)
    mgr.save_snapshot(s_small)

    result = mgr.diff_snapshots("big", "small")
    assert result["delta"]["nodes"] == -40
    assert result["delta"]["edges"] < 0


def test_snapshot_manager_get_previous(snapshot_dir: Path) -> None:
    """get_previous returns the snapshot immediately before by timestamp."""
    mgr = SnapshotManager(snapshot_dir)

    snap1 = _make_dockg_snapshot("treehash1", "2026-03-07T10:00:00+00:00")
    snap2 = _make_dockg_snapshot("treehash2", "2026-03-07T12:00:00+00:00")
    mgr.save_snapshot(snap1)
    mgr.save_snapshot(snap2)

    prev = mgr.get_previous("treehash2")
    assert prev is not None
    assert prev.tree_hash == "treehash1"


def test_get_previous_oldest_returns_none(snapshot_dir: Path) -> None:
    """get_previous on the oldest snapshot returns None (no predecessor)."""
    mgr = SnapshotManager(snapshot_dir)
    mgr.save_snapshot(_make_dockg_snapshot("onlyhash", "2026-03-07T10:00:00+00:00"))
    assert mgr.get_previous("onlyhash") is None


def test_get_previous_returns_none_when_key_not_in_manifest(snapshot_dir: Path) -> None:
    """get_previous returns None when the given key is absent from the manifest."""
    mgr = SnapshotManager(snapshot_dir)
    mgr.save_snapshot(_make_dockg_snapshot("known", "2026-01-01T00:00:00+00:00"))
    assert mgr.get_previous("totally_unknown") is None


def test_snapshot_manager_get_baseline(snapshot_dir: Path) -> None:
    """get_baseline returns the oldest snapshot."""
    mgr = SnapshotManager(snapshot_dir)

    snap1 = _make_dockg_snapshot("treehash1", "2026-03-07T10:00:00+00:00")
    snap2 = _make_dockg_snapshot("treehash2", "2026-03-07T12:00:00+00:00")
    mgr.save_snapshot(snap1)
    mgr.save_snapshot(snap2)

    baseline = mgr.get_baseline()
    assert baseline is not None
    assert baseline.tree_hash == "treehash1"


def test_get_baseline_empty_manifest_returns_none(snapshot_dir: Path) -> None:
    """get_baseline with no snapshots returns None."""
    mgr = SnapshotManager(snapshot_dir)
    assert mgr.get_baseline() is None


def test_get_baseline_returns_oldest_out_of_order(snapshot_dir: Path) -> None:
    """get_baseline returns oldest even when saved out of order."""
    mgr = SnapshotManager(snapshot_dir)
    s1 = _make_dockg_snapshot("oldest", "2025-01-01T00:00:00+00:00")
    s2 = _make_dockg_snapshot("middle", "2026-01-01T00:00:00+00:00")
    s3 = _make_dockg_snapshot("newest", "2026-03-01T00:00:00+00:00")
    for s in (s2, s3, s1):  # out of order
        mgr.save_snapshot(s)

    baseline = mgr.get_baseline()
    assert baseline is not None
    assert baseline.tree_hash == "oldest"


def test_snapshot_manager_delta_computation(snapshot_dir: Path) -> None:
    """capture() computes vs_baseline when a prior snapshot exists."""
    mgr = SnapshotManager(snapshot_dir)

    snap1 = _make_dockg_snapshot("treehash1", "2026-03-07T10:00:00+00:00", nodes=100)
    mgr.save_snapshot(snap1)

    snap2 = mgr.capture(
        version="0.3.1",
        branch="main",
        graph_stats_dict={
            "total_nodes": 110,
            "total_edges": 210,
            "node_counts": {},
            "edge_counts": {},
        },
        coverage_score=0.87,
        issues_count=1,
        complexity_median=3.7,
        tree_hash="treehash2",
    )

    assert snap2.vs_baseline is not None
    assert snap2.vs_baseline.nodes == 10
    assert snap2.vs_baseline.edges == 10


def test_capture_none_graph_stats_defaults_to_empty(snapshot_dir: Path) -> None:
    """capture(graph_stats_dict=None) uses empty dict without crashing."""
    mgr = SnapshotManager(snapshot_dir)
    with patch(
        "doc_kg.snapshots.SnapshotManager._get_current_tree_hash",
        return_value="treehashX",
    ):
        with patch("doc_kg.snapshots.SnapshotManager._get_current_branch", return_value="main"):
            snap = mgr.capture(version="0.3.0", graph_stats_dict=None, coverage_score=0.9)
    assert snap.metrics.total_nodes == 0
    assert snap.tree_hash == "treehashX"


def test_capture_does_not_auto_save(snapshot_dir: Path) -> None:
    """capture() returns a Snapshot but does NOT persist it to disk."""
    mgr = SnapshotManager(snapshot_dir)
    with patch(
        "doc_kg.snapshots.SnapshotManager._get_current_tree_hash", return_value="unsaved_hash"
    ):
        with patch("doc_kg.snapshots.SnapshotManager._get_current_branch", return_value="main"):
            mgr.capture(version="0.3.0")
    assert mgr.load_snapshot("unsaved_hash") is None
    assert mgr.list_snapshots() == []


def test_capture_vs_previous_none_for_new_key(snapshot_dir: Path) -> None:
    """vs_previous is None when the new tree_hash is not yet in the manifest.

    get_previous(key) requires the key to already exist in the manifest so it
    can find that entry's timestamp and look for entries before it. On first
    capture the new key is not saved yet, so vs_previous is always None.
    """
    mgr = SnapshotManager(snapshot_dir)
    mgr.save_snapshot(_make_dockg_snapshot("prev_hash", "2026-01-01T00:00:00+00:00", nodes=40))

    snap = mgr.capture(
        version="0.3.1",
        tree_hash="next_hash",
        branch="main",
        graph_stats_dict={
            "total_nodes": 60,
            "total_edges": 80,
            "node_counts": {},
            "edge_counts": {},
        },
    )
    assert snap.vs_baseline is not None
    assert snap.vs_baseline.nodes == 20  # 60 - 40
    assert snap.vs_previous is None  # next_hash not yet in manifest


def test_capture_vs_baseline_points_to_oldest(snapshot_dir: Path) -> None:
    """vs_baseline always reflects the oldest saved snapshot, not the nearest prior."""
    mgr = SnapshotManager(snapshot_dir)
    mgr.save_snapshot(_make_dockg_snapshot("base_hash", "2026-01-01T00:00:00+00:00", nodes=10))
    mgr.save_snapshot(_make_dockg_snapshot("mid_hash", "2026-02-01T00:00:00+00:00", nodes=30))

    snap = mgr.capture(
        version="0.3.2",
        tree_hash="new_hash",
        branch="main",
        graph_stats_dict={
            "total_nodes": 50,
            "total_edges": 60,
            "node_counts": {},
            "edge_counts": {},
        },
    )
    assert snap.vs_baseline is not None
    assert snap.vs_baseline.nodes == 40  # 50 - 10 (vs oldest, not 50 - 30)


def test_capture_computes_vs_previous_when_prior_snapshot_exists(
    snapshot_dir: Path,
) -> None:
    """capture sets vs_previous delta when a snapshot with matching key exists."""
    mgr = SnapshotManager(snapshot_dir)
    existing = _make_dockg_snapshot("prevhash", "2026-03-07T10:00:00+00:00", nodes=100)
    mgr.save_snapshot(existing)

    with patch(
        "doc_kg.snapshots.SnapshotManager._get_current_tree_hash",
        return_value="nexthash",
    ):
        with patch(
            "doc_kg.snapshots.SnapshotManager._get_current_branch",
            return_value="main",
        ):
            with patch("doc_kg.snapshots.SnapshotManager.get_previous", return_value=existing):
                snap = mgr.capture(
                    version="0.3.1",
                    graph_stats_dict={
                        "total_nodes": 110,
                        "total_edges": 210,
                        "node_counts": {},
                        "edge_counts": {},
                    },
                    coverage_score=0.87,
                    issues_count=1,
                    complexity_median=3.7,
                )

    assert snap.vs_previous is not None
    assert snap.vs_previous.nodes == 10
    assert snap.vs_previous.edges == 10


def test_load_snapshot_backfills_missing_vs_previous(snapshot_dir: Path) -> None:
    """load_snapshot computes vs_previous from manifest ordering when missing in file."""
    mgr = SnapshotManager(snapshot_dir)
    old_snap = _make_dockg_snapshot("older", "2026-03-07T10:00:00+00:00", nodes=100)
    new_snap = _make_dockg_snapshot("newer", "2026-03-07T12:00:00+00:00", nodes=120)

    mgr.save_snapshot(old_snap)
    mgr.save_snapshot(new_snap)

    loaded = mgr.load_snapshot("newer")
    assert loaded is not None
    assert loaded.vs_previous is not None
    assert loaded.vs_previous.nodes == 20
    assert loaded.vs_previous.edges == 40  # 240 - 200


# ---------------------------------------------------------------------------
# SnapshotManifest Tests
# ---------------------------------------------------------------------------


def test_snapshot_manifest_creation() -> None:
    """Test SnapshotManifest creation."""
    manifest = SnapshotManifest(format_version="1.0", last_update="2026-03-12T12:00:00+00:00")
    assert manifest.format_version == "1.0"
    assert len(manifest.snapshots) == 0


def test_snapshot_manifest_to_dict_shape() -> None:
    """to_dict uses 'format' key, not 'format_version'."""
    m = SnapshotManifest(format_version="1.0", last_update="2026-01-01T00:00:00+00:00")
    d = m.to_dict()
    assert d["format"] == "1.0"
    assert d["last_update"] == "2026-01-01T00:00:00+00:00"
    assert d["snapshots"] == []
    assert "format_version" not in d


def test_snapshot_manifest_roundtrip() -> None:
    """Test SnapshotManifest serialize/deserialize."""
    manifest = SnapshotManifest(
        format_version="1.0",
        last_update="2026-03-12T12:00:00+00:00",
        snapshots=[{"key": "abc123tree", "version": "0.3.0"}],
    )

    manifest_dict = manifest.to_dict()
    restored = SnapshotManifest.from_dict(manifest_dict)

    assert restored.format_version == manifest.format_version
    assert len(restored.snapshots) == 1
    assert restored.snapshots[0]["key"] == "abc123tree"


def test_snapshot_manifest_from_dict_missing_keys() -> None:
    """from_dict({}) should fall back to safe defaults without raising."""
    restored = SnapshotManifest.from_dict({})
    assert restored.format_version == "1.0"
    assert restored.last_update == ""
    assert restored.snapshots == []


def test_manifest_last_update_set_after_save(snapshot_dir: Path, sample_snapshot: Snapshot) -> None:
    """last_update is set after saving a snapshot."""
    mgr = SnapshotManager(snapshot_dir)
    mgr.save_snapshot(sample_snapshot)
    manifest = mgr.load_manifest()
    assert manifest.last_update != ""


def test_manifest_entry_has_file_key(snapshot_dir: Path, sample_snapshot: Snapshot) -> None:
    """Manifest entry includes the snapshot filename."""
    mgr = SnapshotManager(snapshot_dir)
    mgr.save_snapshot(sample_snapshot)
    manifest = mgr.load_manifest()
    entry = manifest.snapshots[0]
    assert "file" in entry
    assert entry["file"] == f"{sample_snapshot.key}.json"


def test_manifest_entry_has_deltas_key(snapshot_dir: Path, sample_snapshot: Snapshot) -> None:
    """Manifest entry includes deltas sub-dict."""
    mgr = SnapshotManager(snapshot_dir)
    mgr.save_snapshot(sample_snapshot)
    manifest = mgr.load_manifest()
    entry = manifest.snapshots[0]
    assert "deltas" in entry
    assert entry["deltas"]["vs_previous"] is None
    assert entry["deltas"]["vs_baseline"] is None


def test_manifest_entry_deltas_populated_when_set(snapshot_dir: Path) -> None:
    """Deltas in manifest entry reflect snapshot deltas when present."""
    mgr = SnapshotManager(snapshot_dir)
    s = _make_dockg_snapshot("hash_a", "2026-01-01T00:00:00+00:00")
    s.vs_previous = SnapshotDelta(nodes=5, edges=8)
    s.vs_baseline = SnapshotDelta(nodes=5, edges=8, issues_delta=-1)
    mgr.save_snapshot(s)
    manifest = mgr.load_manifest()
    deltas = manifest.snapshots[0]["deltas"]
    assert deltas["vs_previous"]["nodes"] == 5
    assert deltas["vs_baseline"]["issues_delta"] == -1


# ---------------------------------------------------------------------------
# git helpers
# ---------------------------------------------------------------------------


def test_get_current_tree_hash_git_failure_returns_empty(snapshot_dir: Path) -> None:
    """_get_current_tree_hash returns '' when git is unavailable."""
    mgr = SnapshotManager(snapshot_dir)
    with patch("subprocess.check_output", side_effect=FileNotFoundError):
        result = mgr._get_current_tree_hash()
    assert result == ""


def test_get_current_branch_git_failure_returns_unknown(snapshot_dir: Path) -> None:
    """_get_current_branch returns 'unknown' when git is unavailable."""
    mgr = SnapshotManager(snapshot_dir)
    with patch("subprocess.check_output", side_effect=subprocess.CalledProcessError(1, "git")):
        result = mgr._get_current_branch()
    assert result == "unknown"


def test_get_current_tree_hash_returns_hex_string() -> None:
    """_get_current_tree_hash returns a non-empty hex string in a real git repo."""
    result = SnapshotManager._get_current_tree_hash()
    is_hex = len(result) >= 7 and all(c in "0123456789abcdef" for c in result)
    assert result == "" or is_hex


def test_get_current_branch_returns_nonempty_string() -> None:
    """_get_current_branch returns a non-empty string."""
    branch = SnapshotManager._get_current_branch()
    assert isinstance(branch, str)
    assert len(branch) > 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_metrics(nodes: int = 10, coverage: float = 0.5, issues: int = 0) -> SnapshotMetrics:
    return SnapshotMetrics(
        total_nodes=nodes,
        total_edges=nodes * 2,
        meaningful_nodes=nodes,
        coverage_score=coverage,
        node_counts={},
        edge_counts={},
        issues_count=issues,
        complexity_median=1.0,
    )


def _make_dockg_snapshot(tree_hash: str, timestamp: str, nodes: int = 10) -> Snapshot:
    return Snapshot(
        branch="main",
        timestamp=timestamp,
        version="0.3.0",
        metrics=_make_metrics(nodes=nodes),
        tree_hash=tree_hash,
    )
