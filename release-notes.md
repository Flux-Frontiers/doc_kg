# Release Notes - v0.26.0

> Released: 2026-09-08

DocKG's snapshot manager now configures the fleet's shared implementation
instead of overriding it. This finishes the work 0.25.0 started: 0.25.0
removed the `Snapshot` subclass and its nine copied methods, and 0.26.0
removes the four manager overrides that were left.

## What changed

**The remaining `SnapshotManager` overrides are gone.** The module used to
override `__init__`, `capture`, `diff_snapshots` and `_metrics_changed` to
set the package name, derive DocKG's metric fields, add a timestamp to each
side of a diff, and ignore `db_path` when deciding whether metrics changed.
Each of those is now a declaration against a kgmodule-utils 0.20.0 extension
point: a `package_name` class attribute, a `_domain_metrics()` hook, a
`metrics_ignore` set, and a base diff that already carries the timestamp.
The module shrinks from 497 lines to 236, and only the DocKG-specific delta
computation for `coverage_delta` and `issues_delta` remains as real code.
Eight new tests pin the behaviour the deleted overrides provided. Snapshot
files, manifests, CLI output and the MCP tools are unchanged.

**Why the overrides mattered.** A `capture()` override has to restate the
base signature, and restating it is how an unnamed `key=` fell into
`**extra_metrics` and shipped 0.24.0 with every snapshot keyed on a tree
hash. A hook that receives only the stats it needs cannot repeat that
mistake.

**Dependency floors.** `kgmodule-utils` now requires `>=0.20.0`, and this is a
hard floor rather than a preference: against 0.19.x the manager reports
itself as `kg-utils`, loses `meaningful_nodes`, and treats a `db_path` change
as a real change. The optional `kg` tooling group pins `pycode-kg>=0.27.0`,
the release that made the same move in pycode_kg and floors on the same SDK.

## Upgrading

No action required for normal use. `pip install -U doc-kg` pulls
kgmodule-utils 0.20.0 with it. If you subclass `SnapshotManager` and override
`capture()`, move that logic into `_domain_metrics()`; if you relied on the
`_METRICS_IGNORE` private attribute, it is now the public `metrics_ignore`
class attribute.

---

_Full changelog: [CHANGELOG.md](CHANGELOG.md)_
