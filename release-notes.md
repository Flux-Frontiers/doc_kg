# Release Notes -- v0.24.1

> Released: 2026-09-05

A one-defect patch to 0.24.0, released the same day. 0.24.0 said snapshots are keyed on
the release tag you pass. They were, in memory. The file written to disk still carried a
tree-hash key and empty subject and tool fields, so the change never reached the
snapshots directory. This release makes the stored snapshot match what the CLI reports.

## What changed

**Snapshot files now keep their key and provenance.** `SnapshotManager.save_snapshot`
rebuilds a plain base snapshot before writing, because the shared manager expects the
metrics as a dict where doc-kg exposes a typed view. That rebuild copied everything except
`snapshot_key`, `subject`, `tool` and `tool_version`. With no key present, the shared base
falls back to the tree hash, which is exactly the scheme 0.24.0 set out to retire. All four
fields are now copied, and a test saves a snapshot through the manager and reads the JSON
file and the manifest entry back to prove it.

Nothing else moved. Graph build, query, pack, and the MCP server are untouched.

## Upgrading

Install 0.24.1 and re-take any snapshot you saved with 0.24.0. Those files carry a
tree-hash key and blank provenance, so a snapshot taken on the tagged tree with

```bash
dockg snapshot save 0.24.1 --subject repo:doc-kg
```

replaces them rather than sitting alongside. Snapshots keyed on a tree hash by earlier
releases still load.

---

_Full changelog: [CHANGELOG.md](CHANGELOG.md)_
