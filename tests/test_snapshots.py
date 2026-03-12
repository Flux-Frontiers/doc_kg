"""Tests for snapshots.py — temporal snapshot management."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import pytest

from doc_kg.snapshots import (
    Snapshot,
    SnapshotDelta,
    SnapshotManifest,
    SnapshotManager,
    SnapshotMetrics,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def snapshot_dir(tmp_path: Path) -> Path:
    return tmp_path / "snapshots"


@pytest.fixture
def sample_metrics() -> SnapshotMetrics:
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
    return Snapshot(
        commit="abc123def456",
        branch="main",
        timestamp="2026-03-12T12:00:00+00:00",
        version="0.1.0",
        metrics=sample_metrics,
        hotspots=[{"name": "doc_a", "callers": 5}],
    )


# ---------------------------------------------------------------------------
# SnapshotMetrics
# ---------------------------------------------------------------------------


def test_snapshot_metrics_creation(sample_metrics: SnapshotMetrics):
    assert sample_metrics.total_nodes == 100
    assert sample_metrics.total_edges == 150
    assert sample_metrics.meaningful_nodes == 80
    assert sample_metrics.coverage_score == 0.85
    assert sample_metrics.issues_count == 2
    assert sample_metrics.complexity_median == 3.5


def test_snapshot_metrics_node_counts(sample_metrics: SnapshotMetrics):
    assert sample_metrics.node_counts["document"] == 20
    assert sample_metrics.node_counts["chunk"] == 60


def test_snapshot_metrics_edge_counts(sample_metrics: SnapshotMetrics):
    assert sample_metrics.edge_counts["CONTAINS"] == 80
    assert sample_metrics.edge_counts["SIMILAR_TO"] == 50
    assert sample_metrics.edge_counts["HAS_TOPIC"] == 20


# ---------------------------------------------------------------------------
# SnapshotDelta
# ---------------------------------------------------------------------------


def test_snapshot_delta_defaults():
    delta = SnapshotDelta()
    assert delta.nodes == 0
    assert delta.edges == 0
    assert delta.coverage_delta == 0.0
    assert delta.issues_delta == 0


def test_snapshot_delta_with_values():
    delta = SnapshotDelta(nodes=10, edges=-5, coverage_delta=0.05, issues_delta=-1)
    assert delta.nodes == 10
    assert delta.edges == -5
    assert delta.coverage_delta == pytest.approx(0.05)
    assert delta.issues_delta == -1


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


def test_snapshot_creation(sample_snapshot: Snapshot, sample_metrics: SnapshotMetrics):
    assert sample_snapshot.commit == "abc123def456"
    assert sample_snapshot.branch == "main"
    assert sample_snapshot.version == "0.1.0"
    assert sample_snapshot.metrics is sample_metrics
    assert sample_snapshot.vs_previous is None
    assert sample_snapshot.vs_baseline is None


def test_snapshot_to_dict_has_commit_key(sample_snapshot: Snapshot):
    d = sample_snapshot.to_dict()
    assert "commit" in d
    assert d["commit"] == "abc123def456"
    assert d["branch"] == "main"
    assert d["version"] == "0.1.0"
    assert d["timestamp"] == "2026-03-12T12:00:00+00:00"


def test_snapshot_to_dict_contains_metrics(sample_snapshot: Snapshot):
    d = sample_snapshot.to_dict()
    assert "metrics" in d
    metrics = d["metrics"]
    assert metrics["total_nodes"] == 100
    assert metrics["total_edges"] == 150
    assert metrics["coverage_score"] == pytest.approx(0.85)


def test_snapshot_to_dict_hotspots(sample_snapshot: Snapshot):
    d = sample_snapshot.to_dict()
    assert d["hotspots"] == [{"name": "doc_a", "callers": 5}]


def test_snapshot_to_dict_null_deltas(sample_snapshot: Snapshot):
    d = sample_snapshot.to_dict()
    assert d["vs_previous"] is None
    assert d["vs_baseline"] is None


def test_snapshot_from_dict_roundtrip(sample_snapshot: Snapshot):
    d = sample_snapshot.to_dict()
    restored = Snapshot.from_dict(d)
    assert restored.commit == sample_snapshot.commit
    assert restored.branch == sample_snapshot.branch
    assert restored.version == sample_snapshot.version
    assert restored.metrics.total_nodes == sample_snapshot.metrics.total_nodes
    assert restored.metrics.coverage_score == pytest.approx(sample_snapshot.metrics.coverage_score)
    assert restored.hotspots == sample_snapshot.hotspots
    assert restored.vs_previous is None
    assert restored.vs_baseline is None


def test_snapshot_from_dict_with_deltas(sample_snapshot: Snapshot):
    sample_snapshot.vs_previous = SnapshotDelta(nodes=5, edges=10, coverage_delta=0.02)
    sample_snapshot.vs_baseline = SnapshotDelta(nodes=20, edges=30, issues_delta=-3)
    d = sample_snapshot.to_dict()
    restored = Snapshot.from_dict(d)
    assert restored.vs_previous is not None
    assert restored.vs_previous.nodes == 5
    assert restored.vs_baseline is not None
    assert restored.vs_baseline.issues_delta == -3


# ---------------------------------------------------------------------------
# SnapshotManager — creation and directory
# ---------------------------------------------------------------------------


def test_manager_creates_dir(snapshot_dir: Path):
    assert not snapshot_dir.exists()
    SnapshotManager(snapshot_dir)
    assert snapshot_dir.exists()


def test_manager_accepts_existing_dir(snapshot_dir: Path):
    snapshot_dir.mkdir(parents=True)
    mgr = SnapshotManager(snapshot_dir)
    assert mgr.snapshots_dir == snapshot_dir


# ---------------------------------------------------------------------------
# SnapshotManager — save and load
# ---------------------------------------------------------------------------


def test_save_and_load_snapshot(snapshot_dir: Path, sample_snapshot: Snapshot):
    mgr = SnapshotManager(snapshot_dir)
    mgr.save_snapshot(sample_snapshot)
    loaded = mgr.load_snapshot(sample_snapshot.commit)
    assert loaded is not None
    assert loaded.commit == sample_snapshot.commit
    assert loaded.metrics.total_nodes == sample_snapshot.metrics.total_nodes


def test_load_snapshot_missing_returns_none(snapshot_dir: Path):
    mgr = SnapshotManager(snapshot_dir)
    assert mgr.load_snapshot("nonexistent000") is None


def test_save_snapshot_creates_json_file(snapshot_dir: Path, sample_snapshot: Snapshot):
    mgr = SnapshotManager(snapshot_dir)
    path = mgr.save_snapshot(sample_snapshot)
    assert path.exists()
    assert path.name == f"{sample_snapshot.commit}.json"


# ---------------------------------------------------------------------------
# SnapshotManager — manifest structure
# ---------------------------------------------------------------------------


def test_manifest_created_after_save(snapshot_dir: Path, sample_snapshot: Snapshot):
    mgr = SnapshotManager(snapshot_dir)
    mgr.save_snapshot(sample_snapshot)
    manifest = mgr.load_manifest()
    assert len(manifest.snapshots) == 1


def test_manifest_entry_has_commit_key(snapshot_dir: Path, sample_snapshot: Snapshot):
    mgr = SnapshotManager(snapshot_dir)
    mgr.save_snapshot(sample_snapshot)
    manifest = mgr.load_manifest()
    entry = manifest.snapshots[0]
    assert "commit" in entry
    assert entry["commit"] == sample_snapshot.commit
    # must NOT have a "key" field
    assert "key" not in entry


def test_manifest_entry_has_summary_metrics(snapshot_dir: Path, sample_snapshot: Snapshot):
    mgr = SnapshotManager(snapshot_dir)
    mgr.save_snapshot(sample_snapshot)
    manifest = mgr.load_manifest()
    metrics = manifest.snapshots[0]["metrics"]
    assert "nodes" in metrics
    assert "edges" in metrics
    assert "coverage" in metrics
    assert "issues" in metrics
    assert metrics["nodes"] == sample_snapshot.metrics.total_nodes
    assert metrics["edges"] == sample_snapshot.metrics.total_edges
    assert metrics["coverage"] == pytest.approx(sample_snapshot.metrics.coverage_score)
    assert metrics["issues"] == sample_snapshot.metrics.issues_count


def test_manifest_format_key(snapshot_dir: Path, sample_snapshot: Snapshot):
    mgr = SnapshotManager(snapshot_dir)
    mgr.save_snapshot(sample_snapshot)
    import json

    raw = json.loads(mgr.manifest_path.read_text(encoding="utf-8"))
    assert "format" in raw
    assert "format_version" not in raw


def test_save_same_commit_no_duplicate_entries(snapshot_dir: Path, sample_snapshot: Snapshot):
    mgr = SnapshotManager(snapshot_dir)
    mgr.save_snapshot(sample_snapshot)
    # Save same commit again — should update, not append
    mgr.save_snapshot(sample_snapshot)
    manifest = mgr.load_manifest()
    assert len(manifest.snapshots) == 1


def test_save_same_commit_updates_manifest(snapshot_dir: Path, sample_snapshot: Snapshot):
    mgr = SnapshotManager(snapshot_dir)
    mgr.save_snapshot(sample_snapshot)

    # Modify coverage, save again with same commit
    from dataclasses import replace

    updated_metrics = replace(sample_snapshot.metrics, coverage_score=0.99)
    updated = replace(sample_snapshot, metrics=updated_metrics)
    mgr.save_snapshot(updated)

    manifest = mgr.load_manifest()
    assert len(manifest.snapshots) == 1
    assert manifest.snapshots[0]["metrics"]["coverage"] == pytest.approx(0.99)


# ---------------------------------------------------------------------------
# SnapshotManager — list_snapshots
# ---------------------------------------------------------------------------


def _make_snapshot(commit: str, timestamp: str, nodes: int = 10) -> Snapshot:
    metrics = SnapshotMetrics(
        total_nodes=nodes,
        total_edges=nodes * 2,
        meaningful_nodes=nodes,
        coverage_score=0.5,
        node_counts={},
        edge_counts={},
        issues_count=0,
        complexity_median=1.0,
    )
    return Snapshot(commit=commit, branch="main", timestamp=timestamp, version="0.1.0", metrics=metrics)


def test_list_snapshots_reverse_chronological(snapshot_dir: Path):
    mgr = SnapshotManager(snapshot_dir)
    s1 = _make_snapshot("commit001", "2026-01-01T00:00:00+00:00")
    s2 = _make_snapshot("commit002", "2026-02-01T00:00:00+00:00")
    s3 = _make_snapshot("commit003", "2026-03-01T00:00:00+00:00")
    for s in (s1, s2, s3):
        mgr.save_snapshot(s)

    listed = mgr.list_snapshots()
    commits = [e["commit"] for e in listed]
    assert commits == ["commit003", "commit002", "commit001"]


def test_list_snapshots_with_limit(snapshot_dir: Path):
    mgr = SnapshotManager(snapshot_dir)
    for i in range(5):
        s = _make_snapshot(f"commit{i:03d}", f"2026-0{i + 1}-01T00:00:00+00:00")
        mgr.save_snapshot(s)

    listed = mgr.list_snapshots(limit=3)
    assert len(listed) == 3


def test_list_snapshots_empty(snapshot_dir: Path):
    mgr = SnapshotManager(snapshot_dir)
    assert mgr.list_snapshots() == []


# ---------------------------------------------------------------------------
# SnapshotManager — diff_snapshots
# ---------------------------------------------------------------------------


def test_diff_snapshots_delta_fields(snapshot_dir: Path):
    mgr = SnapshotManager(snapshot_dir)
    s1 = _make_snapshot("commitA", "2026-01-01T00:00:00+00:00", nodes=50)
    s2 = _make_snapshot("commitB", "2026-02-01T00:00:00+00:00", nodes=70)
    mgr.save_snapshot(s1)
    mgr.save_snapshot(s2)

    result = mgr.diff_snapshots("commitA", "commitB")
    assert "a" in result
    assert "b" in result
    assert "delta" in result
    delta = result["delta"]
    assert "nodes" in delta
    assert "edges" in delta
    assert "coverage_delta" in delta
    assert "issues_delta" in delta


def test_diff_snapshots_correct_values(snapshot_dir: Path):
    mgr = SnapshotManager(snapshot_dir)
    s1 = _make_snapshot("commitA", "2026-01-01T00:00:00+00:00", nodes=50)
    s2 = _make_snapshot("commitB", "2026-02-01T00:00:00+00:00", nodes=70)
    mgr.save_snapshot(s1)
    mgr.save_snapshot(s2)

    result = mgr.diff_snapshots("commitA", "commitB")
    # delta is (b - a) = (70 - 50) = 20 nodes, 40 - 100 = -60 edges
    assert result["delta"]["nodes"] == 20
    assert result["delta"]["edges"] == 40


def test_diff_snapshots_missing_returns_error(snapshot_dir: Path):
    mgr = SnapshotManager(snapshot_dir)
    result = mgr.diff_snapshots("missing_a", "missing_b")
    assert "error" in result


def test_diff_snapshots_one_missing_returns_error(snapshot_dir: Path):
    mgr = SnapshotManager(snapshot_dir)
    s1 = _make_snapshot("commitA", "2026-01-01T00:00:00+00:00")
    mgr.save_snapshot(s1)
    result = mgr.diff_snapshots("commitA", "nonexistent")
    assert "error" in result


# ---------------------------------------------------------------------------
# SnapshotManager — get_previous
# ---------------------------------------------------------------------------


def test_get_previous_returns_none_when_empty(snapshot_dir: Path):
    mgr = SnapshotManager(snapshot_dir)
    assert mgr.get_previous("anycommit") is None


def test_get_previous_returns_none_for_oldest(snapshot_dir: Path):
    mgr = SnapshotManager(snapshot_dir)
    s = _make_snapshot("only_commit", "2026-01-01T00:00:00+00:00")
    mgr.save_snapshot(s)
    assert mgr.get_previous("only_commit") is None


def test_get_previous_returns_snapshot_before(snapshot_dir: Path):
    mgr = SnapshotManager(snapshot_dir)
    s1 = _make_snapshot("commit_old", "2026-01-01T00:00:00+00:00")
    s2 = _make_snapshot("commit_new", "2026-03-01T00:00:00+00:00")
    mgr.save_snapshot(s1)
    mgr.save_snapshot(s2)

    prev = mgr.get_previous("commit_new")
    assert prev is not None
    assert prev.commit == "commit_old"


# ---------------------------------------------------------------------------
# SnapshotManager — get_baseline
# ---------------------------------------------------------------------------


def test_get_baseline_empty_returns_none(snapshot_dir: Path):
    mgr = SnapshotManager(snapshot_dir)
    assert mgr.get_baseline() is None


def test_get_baseline_single_snapshot(snapshot_dir: Path):
    mgr = SnapshotManager(snapshot_dir)
    s = _make_snapshot("only_commit", "2026-01-01T00:00:00+00:00")
    mgr.save_snapshot(s)
    baseline = mgr.get_baseline()
    assert baseline is not None
    assert baseline.commit == "only_commit"


def test_get_baseline_returns_oldest(snapshot_dir: Path):
    mgr = SnapshotManager(snapshot_dir)
    s1 = _make_snapshot("commit_oldest", "2025-01-01T00:00:00+00:00")
    s2 = _make_snapshot("commit_middle", "2026-01-01T00:00:00+00:00")
    s3 = _make_snapshot("commit_newest", "2026-03-01T00:00:00+00:00")
    for s in (s2, s3, s1):  # save out of order
        mgr.save_snapshot(s)

    baseline = mgr.get_baseline()
    assert baseline is not None
    assert baseline.commit == "commit_oldest"


# ---------------------------------------------------------------------------
# SnapshotManager — capture with mocked git
# ---------------------------------------------------------------------------


def test_capture_uses_provided_commit_and_branch(snapshot_dir: Path):
    mgr = SnapshotManager(snapshot_dir)
    snap = mgr.capture(version="0.1.0", commit="abc123", branch="feature/x")
    assert snap.commit == "abc123"
    assert snap.branch == "feature/x"


def test_capture_auto_detects_commit_via_git(snapshot_dir: Path):
    mgr = SnapshotManager(snapshot_dir)
    with patch.object(mgr, "_get_current_commit", return_value="deadbeef"), \
         patch.object(mgr, "_get_current_branch", return_value="main"):
        snap = mgr.capture(version="0.1.0")
    assert snap.commit == "deadbeef"
    assert snap.branch == "main"


def test_capture_git_failure_returns_unknown(snapshot_dir: Path):
    mgr = SnapshotManager(snapshot_dir)
    with patch(
        "doc_kg.snapshots.SnapshotManager._get_current_commit", return_value="unknown"
    ), patch("doc_kg.snapshots.SnapshotManager._get_current_branch", return_value="unknown"):
        snap = mgr.capture(version="0.1.0")
    assert snap.commit == "unknown"
    assert snap.branch == "unknown"


def test_capture_builds_metrics_from_graph_stats(snapshot_dir: Path):
    mgr = SnapshotManager(snapshot_dir)
    stats = {
        "total_nodes": 120,
        "total_edges": 200,
        "node_counts": {"document": 10, "chunk": 80},
        "edge_counts": {"CONTAINS": 100, "HAS_TOPIC": 50},
    }
    snap = mgr.capture(
        version="0.1.0",
        commit="abc",
        branch="main",
        graph_stats_dict=stats,
        coverage_score=0.9,
        issues_count=3,
        complexity_median=2.5,
    )
    assert snap.metrics.total_nodes == 120
    assert snap.metrics.total_edges == 200
    # meaningful_nodes = total_nodes - document count = 120 - 10 = 110
    assert snap.metrics.meaningful_nodes == 110
    assert snap.metrics.coverage_score == pytest.approx(0.9)
    assert snap.metrics.issues_count == 3
    assert snap.metrics.complexity_median == pytest.approx(2.5)


def test_capture_with_hotspots(snapshot_dir: Path):
    mgr = SnapshotManager(snapshot_dir)
    hotspots = [{"name": "big_doc", "callers": 12}]
    snap = mgr.capture(version="0.1.0", commit="abc", branch="main", hotspots=hotspots)
    assert snap.hotspots == hotspots


def test_capture_auto_computes_vs_baseline(snapshot_dir: Path):
    mgr = SnapshotManager(snapshot_dir)

    # Save a baseline first
    baseline = _make_snapshot("base001", "2026-01-01T00:00:00+00:00", nodes=50)
    mgr.save_snapshot(baseline)

    # Small delay so timestamps differ
    time.sleep(0.01)

    stats = {"total_nodes": 70, "total_edges": 100, "node_counts": {}, "edge_counts": {}}
    snap = mgr.capture(
        version="0.1.0",
        commit="new001",
        branch="main",
        graph_stats_dict=stats,
    )
    assert snap.vs_baseline is not None
    assert snap.vs_baseline.nodes == 20  # 70 - 50


def test_capture_vs_previous_none_when_no_prior_snapshot(snapshot_dir: Path):
    mgr = SnapshotManager(snapshot_dir)
    snap = mgr.capture(version="0.1.0", commit="first", branch="main")
    assert snap.vs_previous is None
    assert snap.vs_baseline is None


def test_capture_vs_previous_none_for_new_commit(snapshot_dir: Path):
    """vs_previous is None when the new commit is not yet saved to the manifest.

    get_previous(commit) requires the commit to already exist in the manifest so it
    can find that commit's timestamp and look for entries before it.  On first capture
    the new commit is not saved yet, so vs_previous is always None.
    """
    mgr = SnapshotManager(snapshot_dir)
    s1 = _make_snapshot("commit_prev", "2026-01-01T00:00:00+00:00", nodes=40)
    mgr.save_snapshot(s1)

    stats = {"total_nodes": 60, "total_edges": 80, "node_counts": {}, "edge_counts": {}}
    snap = mgr.capture(
        version="0.1.0",
        commit="commit_next",
        branch="main",
        graph_stats_dict=stats,
    )
    # vs_baseline IS set (get_baseline doesn't need the new commit in the manifest)
    assert snap.vs_baseline is not None
    assert snap.vs_baseline.nodes == 20  # 60 - 40
    # vs_previous is None because "commit_next" is not yet in the manifest
    assert snap.vs_previous is None


def test_capture_vs_baseline_points_to_oldest_of_multiple(snapshot_dir: Path):
    """vs_baseline always reflects the oldest saved snapshot, not the most recent prior."""
    mgr = SnapshotManager(snapshot_dir)
    s1 = _make_snapshot("commit_base", "2026-01-01T00:00:00+00:00", nodes=10)
    s2 = _make_snapshot("commit_mid", "2026-02-01T00:00:00+00:00", nodes=30)
    mgr.save_snapshot(s1)
    mgr.save_snapshot(s2)

    stats = {"total_nodes": 50, "total_edges": 60, "node_counts": {}, "edge_counts": {}}
    snap = mgr.capture(
        version="0.1.0",
        commit="commit_new",
        branch="main",
        graph_stats_dict=stats,
    )
    # vs_baseline should reflect delta from oldest (10 nodes), not the middle (30 nodes)
    assert snap.vs_baseline is not None
    assert snap.vs_baseline.nodes == 40  # 50 - 10 (vs oldest, not 50 - 30)


def test_capture_does_not_auto_save(snapshot_dir: Path):
    mgr = SnapshotManager(snapshot_dir)
    mgr.capture(version="0.1.0", commit="unsaved", branch="main")
    assert mgr.load_snapshot("unsaved") is None
    assert mgr.list_snapshots() == []


# ---------------------------------------------------------------------------
# SnapshotManager — manifest deltas and file fields
# ---------------------------------------------------------------------------


def test_manifest_entry_has_file_key(snapshot_dir: Path, sample_snapshot: Snapshot):
    mgr = SnapshotManager(snapshot_dir)
    mgr.save_snapshot(sample_snapshot)
    manifest = mgr.load_manifest()
    entry = manifest.snapshots[0]
    assert "file" in entry
    assert entry["file"] == f"{sample_snapshot.commit}.json"


def test_manifest_entry_has_deltas_key(snapshot_dir: Path, sample_snapshot: Snapshot):
    mgr = SnapshotManager(snapshot_dir)
    mgr.save_snapshot(sample_snapshot)
    manifest = mgr.load_manifest()
    entry = manifest.snapshots[0]
    assert "deltas" in entry
    assert entry["deltas"]["vs_previous"] is None
    assert entry["deltas"]["vs_baseline"] is None


def test_manifest_entry_deltas_populated_when_set(snapshot_dir: Path):
    mgr = SnapshotManager(snapshot_dir)
    s = _make_snapshot("commit_a", "2026-01-01T00:00:00+00:00", nodes=20)
    s.vs_previous = SnapshotDelta(nodes=5, edges=8)
    s.vs_baseline = SnapshotDelta(nodes=5, edges=8, issues_delta=-1)
    mgr.save_snapshot(s)
    manifest = mgr.load_manifest()
    deltas = manifest.snapshots[0]["deltas"]
    assert deltas["vs_previous"]["nodes"] == 5
    assert deltas["vs_baseline"]["issues_delta"] == -1


def test_manifest_last_update_set_after_save(snapshot_dir: Path, sample_snapshot: Snapshot):
    mgr = SnapshotManager(snapshot_dir)
    mgr.save_snapshot(sample_snapshot)
    manifest = mgr.load_manifest()
    assert manifest.last_update != ""


# ---------------------------------------------------------------------------
# SnapshotManifest — direct to_dict / from_dict
# ---------------------------------------------------------------------------


def test_snapshot_manifest_to_dict_shape():
    m = SnapshotManifest(format_version="1.0", last_update="2026-01-01T00:00:00+00:00")
    d = m.to_dict()
    assert d["format"] == "1.0"
    assert d["last_update"] == "2026-01-01T00:00:00+00:00"
    assert d["snapshots"] == []
    assert "format_version" not in d


def test_snapshot_manifest_from_dict_roundtrip():
    original = SnapshotManifest(
        format_version="2.0",
        last_update="2026-03-01T00:00:00+00:00",
        snapshots=[{"commit": "abc"}],
    )
    restored = SnapshotManifest.from_dict(original.to_dict())
    assert restored.format_version == "2.0"
    assert restored.last_update == "2026-03-01T00:00:00+00:00"
    assert restored.snapshots == [{"commit": "abc"}]


def test_snapshot_manifest_from_dict_missing_keys():
    restored = SnapshotManifest.from_dict({})
    assert restored.format_version == "1.0"
    assert restored.last_update == ""
    assert restored.snapshots == []


# ---------------------------------------------------------------------------
# SnapshotManager — get_previous edge cases
# ---------------------------------------------------------------------------


def test_get_previous_returns_none_when_commit_not_in_manifest(snapshot_dir: Path):
    mgr = SnapshotManager(snapshot_dir)
    s = _make_snapshot("known_commit", "2026-01-01T00:00:00+00:00")
    mgr.save_snapshot(s)
    assert mgr.get_previous("totally_unknown") is None


# ---------------------------------------------------------------------------
# SnapshotManager — list_snapshots limit=0 edge case
# ---------------------------------------------------------------------------


def test_list_snapshots_limit_zero_returns_all(snapshot_dir: Path):
    """limit=0 is falsy so the manager returns all snapshots, not an empty list."""
    mgr = SnapshotManager(snapshot_dir)
    for i in range(3):
        s = _make_snapshot(f"commit{i:03d}", f"2026-0{i + 1}-01T00:00:00+00:00")
        mgr.save_snapshot(s)
    listed = mgr.list_snapshots(limit=0)
    assert len(listed) == 3


# ---------------------------------------------------------------------------
# SnapshotManager — diff coverage and issues deltas
# ---------------------------------------------------------------------------


def test_diff_snapshots_coverage_and_issues_delta(snapshot_dir: Path):
    mgr = SnapshotManager(snapshot_dir)

    metrics_a = SnapshotMetrics(
        total_nodes=50, total_edges=80, meaningful_nodes=50,
        coverage_score=0.60, node_counts={}, edge_counts={},
        issues_count=5, complexity_median=2.0,
    )
    metrics_b = SnapshotMetrics(
        total_nodes=50, total_edges=80, meaningful_nodes=50,
        coverage_score=0.80, node_counts={}, edge_counts={},
        issues_count=2, complexity_median=2.0,
    )
    s1 = Snapshot(commit="commitA", branch="main", timestamp="2026-01-01T00:00:00+00:00",
                  version="0.1.0", metrics=metrics_a)
    s2 = Snapshot(commit="commitB", branch="main", timestamp="2026-02-01T00:00:00+00:00",
                  version="0.2.0", metrics=metrics_b)
    mgr.save_snapshot(s1)
    mgr.save_snapshot(s2)

    result = mgr.diff_snapshots("commitA", "commitB")
    assert result["delta"]["coverage_delta"] == pytest.approx(0.20)
    assert result["delta"]["issues_delta"] == -3


# ---------------------------------------------------------------------------
# SnapshotManager._compute_delta — negative regression
# ---------------------------------------------------------------------------


def test_compute_delta_negative_regression(snapshot_dir: Path):
    """Delta should be negative when new snapshot has fewer nodes/edges."""
    mgr = SnapshotManager(snapshot_dir)
    s_big = _make_snapshot("big", "2026-01-01T00:00:00+00:00", nodes=100)
    s_small = _make_snapshot("small", "2026-02-01T00:00:00+00:00", nodes=60)
    mgr.save_snapshot(s_big)
    mgr.save_snapshot(s_small)

    result = mgr.diff_snapshots("big", "small")
    assert result["delta"]["nodes"] == -40
    assert result["delta"]["edges"] < 0


# ---------------------------------------------------------------------------
# SnapshotManager._get_current_commit / _get_current_branch — real subprocess
# ---------------------------------------------------------------------------


def test_get_current_commit_returns_hex_string():
    commit = SnapshotManager._get_current_commit()
    # Either a valid hex commit hash or "unknown" if not in a git repo
    is_hex = len(commit) >= 7 and all(c in "0123456789abcdef" for c in commit)
    assert commit == "unknown" or is_hex


def test_get_current_branch_returns_nonempty_string():
    branch = SnapshotManager._get_current_branch()
    assert isinstance(branch, str)
    assert len(branch) > 0
