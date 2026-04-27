# Release Notes — v0.12.2

> Released: 2026-04-27

### Changed
- `snapshots.py`: Migrated snapshot base imports from `kg-snapshot` to
  `kgmodule-utils` (`kg_utils.snapshots`); removed `kg-snapshot` from
  `pyproject.toml` dependencies.
- `snapshots.py`: `SnapshotManager.capture()` signature aligned with
  `kg_utils.snapshots.SnapshotManager` — legacy `coverage_score`,
  `issues_count`, `complexity_median` kwargs now accepted via `**extra_metrics`
  (fixes mypy `[override]` error).

---

_Full changelog: [CHANGELOG.md](CHANGELOG.md)_
