# Release Notes -- v0.24.0

> Released: 2026-09-05

This release changes what a DocKG snapshot is keyed on. Snapshots used to be named by a git
tree hash read before the snapshot itself was staged, so the recorded hash named a tree that
was never committed. Across the fleet only 63 of 605 snapshot keys resolved. Snapshots are now
keyed on the release tag you pass, or on a UTC timestamp when you pass none. The key scheme
comes from kgmodule-utils 0.19.0, and the floor moves with it.

## What changed

**Snapshot keys are release tags or timestamps.** `dockg snapshot save VERSION` uses VERSION
as the key. When VERSION is omitted the key is a UTC timestamp, which is the right identity
for a corpus that has no release of its own. The installed doc-kg version is still recorded,
but as the tool that took the measurement, never as the key.

**`--subject` names what was measured.** A new `--subject` flag on `snapshot save`, and a
matching `subject=` on `SnapshotManager.capture()`, records the thing being measured
(`repo:doc-kg`, `corpus:pepys`) separately from the tool doing the measuring. Both `key` and
`subject` are named parameters on `capture()`, so they can no longer be swallowed by the
`**extra_metrics` catch-all and silently stored as metrics.

**Less code in the `Snapshot` subclass.** The `to_dict` override is gone: kgmodule-utils
0.19.0 serializes the typed metric views itself, and the override was the last place a tree
hash was hardcoded as the key. `from_dict` no longer copies a non-hash key into `tree_hash`;
a stored 40-character hash is kept as provenance, a release tag is not.

## Upgrading

Update to `kgmodule-utils>=0.19.0`; the dependency floor in this release requires it. No
rebuild of an existing graph or index is needed. Existing snapshots keyed on tree hashes
still load. At release time, pass the version explicitly:

```bash
dockg snapshot save 0.24.0 --subject repo:doc-kg
```

---

_Full changelog: [CHANGELOG.md](CHANGELOG.md)_
