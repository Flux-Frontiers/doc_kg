# Release Notes — v0.25.0

> Released: 2026-09-06

DocKG's snapshot support is rebuilt on the fleet's shared model, closing the
class of bug that shipped in the 0.24.0/0.24.1 pair.

## What changed

**The `Snapshot` subclass is gone.** DocKG used to subclass the shared
`kg_utils.snapshots.Snapshot` to expose `metrics`, `vs_previous`, and
`vs_baseline` as typed properties instead of plain dicts. That forced a
hand-written copy of nine manager methods — `capture`, `save_snapshot`,
`load_snapshot`, `get_previous`, `get_baseline`, `diff_snapshots`,
`_compute_delta`, `to_dict`, and `from_dict` — and one of those copies is
what dropped the snapshot key and provenance fields in 0.24.0, patched
same-day in 0.24.1. Removing the subclass removes the whole class of bug
instead of the one instance of it.

A snapshot's `metrics`, `vs_previous`, and `vs_baseline` are now plain
dicts. `SnapshotMetrics` and `SnapshotDelta` remain available as converters
for code that wants attribute access. Snapshot files, manifests, CLI
output, and the MCP tools are unchanged.

**The `kgmodule-utils` 0.19.1 delta-backfill fix now reaches DocKG.**
Loading a saved snapshot previously reported `coverage_delta` and
`issues_delta` as absent, even though listing and diffing snapshots
computed them correctly for the same pair — the exact read path
`snapshot show` uses was the one giving the wrong answer. With the floor
resolving to 0.19.1, `snapshot show` now reports the same numbers as every
other view of a snapshot.

## Upgrading

No action required for normal use — snapshot files, the CLI, and the MCP
tools are unchanged. If your code accessed `Snapshot.metrics` as an object
with attributes (`snap.metrics.total_nodes`), switch to dict access
(`snap.metrics["total_nodes"]`) or call `metrics_from_dict(snap.metrics)`
for the old style with attribute access.

---

_Full changelog: [CHANGELOG.md](CHANGELOG.md)_
