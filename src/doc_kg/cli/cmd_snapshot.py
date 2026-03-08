"""
cmd_snapshot.py

Click subcommands for managing temporal snapshots of DocKG metrics:

  snapshot save   - capture current metrics and save snapshot
  snapshot list   - show all snapshots with key metrics
  snapshot show   - display full snapshot details
  snapshot diff   - compare two snapshots
"""

from __future__ import annotations

import json
from pathlib import Path

import click

from doc_kg.cli.main import cli
from doc_kg.cli.options import sqlite_option
from doc_kg.dockg_thorough_analysis import DocKGAnalyzer
from doc_kg.kg import DocKG
from doc_kg.snapshots import SnapshotManager
from doc_kg.store import GraphStore


@cli.group("snapshot")
def snapshot() -> None:
    """Manage temporal snapshots of DocKG metrics."""


@snapshot.command("save")
@click.argument("version", metavar="VERSION")
@click.option(
    "--repo",
    default=".",
    type=click.Path(exists=True),
    show_default=True,
    help="Repository/corpus root path.",
)
@sqlite_option
@click.option(
    "--snapshots-dir",
    default=None,
    type=click.Path(),
    help="Snapshots directory (default: .dockg/snapshots).",
)
@click.option(
    "--commit",
    default=None,
    type=str,
    help="Commit hash; auto-detected if not provided.",
)
@click.option(
    "--branch",
    default=None,
    type=str,
    help="Branch name; auto-detected if not provided.",
)
def save_snapshot(
    version: str,
    repo: str,
    sqlite: str,
    snapshots_dir: str | None,
    commit: str | None,
    branch: str | None,
) -> None:
    """Capture current DocKG metrics and save as a temporal snapshot."""
    repo_root = Path(repo).resolve()
    db_path = Path(sqlite)
    snapshots_path = (
        Path(snapshots_dir).resolve() if snapshots_dir else (repo_root / ".dockg" / "snapshots")
    )

    store = GraphStore(db_path)
    try:
        stats = store.stats()
    finally:
        store.close()

    kg = DocKG(
        corpus_root=repo_root,
        db_path=db_path,
        lancedb_dir=repo_root / ".dockg" / "lancedb",
    )
    try:
        analyzer = DocKGAnalyzer(kg)
        analysis = analyzer.run_analysis()

        coverage_map = analysis.get("semantic_coverage", {})
        coverage_values = [
            float(coverage_map.get("topic_coverage", 0.0)),
            float(coverage_map.get("entity_coverage", 0.0)),
            float(coverage_map.get("keyword_coverage", 0.0)),
        ]
        coverage_score = sum(coverage_values) / len(coverage_values)

        issues_count = len(analysis.get("issues", []))
        hotspots = analysis.get("hot_chunks", [])[:10]

        complexity_values = [int(h.get("semantic_links", 0)) for h in hotspots]
        complexity_median = (
            float(sorted(complexity_values)[len(complexity_values) // 2])
            if complexity_values
            else 0.0
        )
    finally:
        kg.close()

    mgr = SnapshotManager(snapshots_path)
    snapshot_obj = mgr.capture(
        version=version,
        commit=commit,
        branch=branch,
        graph_stats_dict=stats,
        coverage_score=coverage_score,
        issues_count=issues_count,
        complexity_median=complexity_median,
        hotspots=hotspots,
    )

    snapshot_file = mgr.save_snapshot(snapshot_obj)
    click.echo(f"Snapshot saved: {snapshot_file}")
    click.echo(f"  Commit:  {snapshot_obj.commit}")
    click.echo(f"  Version: {snapshot_obj.version}")
    click.echo(f"  Nodes:   {snapshot_obj.metrics.total_nodes}")
    click.echo(f"  Edges:   {snapshot_obj.metrics.total_edges}")
    click.echo(f"  Coverage: {snapshot_obj.metrics.coverage_score:.1%}")


@snapshot.command("list")
@click.option(
    "--snapshots-dir",
    default=None,
    type=click.Path(exists=True),
    help="Snapshots directory (default: .dockg/snapshots).",
)
@click.option(
    "--limit",
    type=int,
    default=None,
    help="Max snapshots to show.",
)
@click.option(
    "--json",
    "output_json",
    is_flag=True,
    help="Output as JSON.",
)
def list_snapshots(snapshots_dir: str | None, limit: int | None, output_json: bool) -> None:
    """List all temporal snapshots in reverse chronological order."""
    snapshots_path = (
        Path(snapshots_dir).resolve() if snapshots_dir else (Path.cwd() / ".dockg" / "snapshots")
    )
    mgr = SnapshotManager(snapshots_path)
    snapshots = mgr.list_snapshots(limit=limit)

    if not snapshots:
        click.echo("No snapshots found.")
        return

    if output_json:
        click.echo(json.dumps(snapshots, indent=2))
    else:
        click.echo(
            f"{'Commit':<10} {'Branch':<12} {'Version':<10} {'Nodes':<6} {'Edges':<6} {'Coverage':<9}"
        )
        click.echo("-" * 65)
        for snap in snapshots:
            commit = snap["commit"][:10]
            branch = snap["branch"][:12]
            version = snap["version"][:10]
            nodes = snap["metrics"]["nodes"]
            edges = snap["metrics"]["edges"]
            coverage = snap["metrics"]["coverage"]
            click.echo(
                f"{commit:<10} {branch:<12} {version:<10} {nodes:<6} {edges:<6} {coverage:>6.1%}"
            )


@snapshot.command("show")
@click.argument("commit", metavar="COMMIT")
@click.option(
    "--snapshots-dir",
    default=None,
    type=click.Path(exists=True),
    help="Snapshots directory (default: .dockg/snapshots).",
)
def show_snapshot(commit: str, snapshots_dir: str | None) -> None:
    """Display full details for a single snapshot by commit hash."""
    snapshots_path = (
        Path(snapshots_dir).resolve() if snapshots_dir else (Path.cwd() / ".dockg" / "snapshots")
    )
    mgr = SnapshotManager(snapshots_path)
    snapshot_obj = mgr.load_snapshot(commit)

    if not snapshot_obj:
        click.echo(f"Snapshot not found: {commit}", err=True)
        raise click.Abort()

    click.echo(f"Commit:    {snapshot_obj.commit}")
    click.echo(f"Branch:    {snapshot_obj.branch}")
    click.echo(f"Timestamp: {snapshot_obj.timestamp}")
    click.echo(f"Version:   {snapshot_obj.version}")
    click.echo()

    click.echo("Metrics:")
    click.echo(f"  Total Nodes:       {snapshot_obj.metrics.total_nodes}")
    click.echo(f"  Total Edges:       {snapshot_obj.metrics.total_edges}")
    click.echo(f"  Meaningful Nodes:  {snapshot_obj.metrics.meaningful_nodes}")
    click.echo(f"  Coverage Score:    {snapshot_obj.metrics.coverage_score:.1%}")
    click.echo(f"  Issues Count:      {snapshot_obj.metrics.issues_count}")
    click.echo(f"  Complexity Median: {snapshot_obj.metrics.complexity_median:.2f}")
    click.echo()

    click.echo("Node/Edge Breakdown:")
    for kind, count in sorted(snapshot_obj.metrics.node_counts.items()):
        click.echo(f"  {kind}: {count}")
    click.echo()
    for rel, count in sorted(snapshot_obj.metrics.edge_counts.items()):
        click.echo(f"  {rel}: {count}")
    click.echo()

    if snapshot_obj.hotspots:
        click.echo("Top Hot Chunks:")
        for i, hotspot in enumerate(snapshot_obj.hotspots[:5], 1):
            hid = hotspot.get("id", "unknown")
            score = hotspot.get("semantic_links", 0)
            click.echo(f"  {i}. {hid} (semantic_links={score})")
        click.echo()

    if snapshot_obj.vs_previous:
        delta = snapshot_obj.vs_previous
        click.echo("Delta vs. Previous:")
        click.echo(f"  Nodes:       {delta.nodes:+d}")
        click.echo(f"  Edges:       {delta.edges:+d}")
        click.echo(f"  Coverage:    {delta.coverage_delta:+.1%}")
        click.echo(f"  Issues:      {delta.issues_delta:+d}")
        click.echo()

    if snapshot_obj.vs_baseline:
        delta = snapshot_obj.vs_baseline
        click.echo("Delta vs. Baseline:")
        click.echo(f"  Nodes:       {delta.nodes:+d}")
        click.echo(f"  Edges:       {delta.edges:+d}")
        click.echo(f"  Coverage:    {delta.coverage_delta:+.1%}")
        click.echo(f"  Issues:      {delta.issues_delta:+d}")


@snapshot.command("diff")
@click.argument("commit_a", metavar="COMMIT_A")
@click.argument("commit_b", metavar="COMMIT_B")
@click.option(
    "--snapshots-dir",
    default=None,
    type=click.Path(exists=True),
    help="Snapshots directory (default: .dockg/snapshots).",
)
@click.option(
    "--json",
    "output_json",
    is_flag=True,
    help="Output as JSON.",
)
def diff_snapshots(
    commit_a: str, commit_b: str, snapshots_dir: str | None, output_json: bool
) -> None:
    """Compare two snapshots side-by-side."""
    snapshots_path = (
        Path(snapshots_dir).resolve() if snapshots_dir else (Path.cwd() / ".dockg" / "snapshots")
    )
    mgr = SnapshotManager(snapshots_path)
    diff_result = mgr.diff_snapshots(commit_a, commit_b)

    if "error" in diff_result:
        click.echo(f"Error: {diff_result['error']}", err=True)
        raise click.Abort()

    if output_json:
        click.echo(json.dumps(diff_result, indent=2))
        return

    a = diff_result["a"]
    b = diff_result["b"]
    click.echo(f"Comparing {a['commit'][:10]} vs {b['commit'][:10]}")
    click.echo()
    click.echo(f"{'Metric':<20} {'A':<12} {'B':<12} {'Delta':<12}")
    click.echo("-" * 56)

    metrics_a = a["metrics"]
    metrics_b = b["metrics"]

    for key in ["total_nodes", "total_edges", "meaningful_nodes"]:
        val_a = metrics_a[key]
        val_b = metrics_b[key]
        delta_val = val_b - val_a
        click.echo(f"{key:<20} {val_a:<12} {val_b:<12} {delta_val:+d}")

    cov_a = metrics_a["coverage_score"]
    cov_b = metrics_b["coverage_score"]
    cov_delta = cov_b - cov_a
    click.echo(f"{'coverage_score':<20} {cov_a:<12.1%} {cov_b:<12.1%} {cov_delta:+.1%}")

    issues_a = metrics_a["issues_count"]
    issues_b = metrics_b["issues_count"]
    issues_delta = issues_b - issues_a
    click.echo(f"{'issues_count':<20} {issues_a:<12} {issues_b:<12} {issues_delta:+d}")
