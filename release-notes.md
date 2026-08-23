# Release Notes — v0.22.0

> Released: 2026-08-22

DocKG nodes can now carry domain-specific metadata, and the node-read paths
that expose it got a consistency fix. Alongside that feature, the docs and
repo tooling caught up with changes that had already landed in prior
releases but were never swept through.

## What changed

**Nodes gained a `metadata` field.** `DocNode` now carries an optional
`metadata` mapping, backed by a new `metadata TEXT` column that stores it as
JSON. This is what lets time-scoped corpora in the fleet — DiaryKG,
MemoryKG, GutenbergKG — attach the `kg_utils.temporal` keys a federated
`QueryScope(time_range=...)` query needs; without a column here, those keys
had nowhere to live. Existing `.dockg/` databases pick up the column
automatically the next time they're opened, and a metadata blob that fails
to parse reads back as `{}` rather than raising.

**Every node-read path now agrees on its columns.** `node()`,
`nodes_batch()`, `query_nodes()`, and `iter_nodes()` used to name the node
columns independently, which is how `metadata` reached three of the four
read paths and was missed on the fourth until a test caught it. A single
`_NODE_COLUMNS` list now drives every SELECT, so the columns can't drift
apart again.

**Docs now describe sqlite-vec, not LanceDB.** The vector-store migration
landed in 0.20.0, but seven documents — including both benchmark writeups
and the dockg-action README — still described the old LanceDB backend, down
to the embedded image-generation prompts. They're corrected, along with a
stale embedding-model dimension in `docs/pipeline_visual.md` and a couple of
self-contradicting installation instructions.

**Repo tooling caught up too.** `pyproject.toml`'s header now lists the
extras that actually exist, the `pycodekg-rebuild` command matches the
current PyCodeKG CLI flags, and `kgmodule-utils` is floored at `>=0.18.0` to
match where the rest of the fleet already sits — consequently `poetry.lock`
still resolves the older line until that version is on PyPI.

**Stored snapshots no longer leak a local path.** Ninety historical
`.pycodekg` snapshots had `metrics.db_path` recorded as an absolute
`/Users/...` path; it's now relative, matching what the snapshot writer
emits going forward.

## Upgrading

No API or CLI changes. Existing `.dockg/` databases migrate the new
`metadata` column automatically on next open — no manual step required.
Producers that want to populate it with `kg_utils.temporal.temporal_metadata()`
need `kgmodule-utils>=0.18.0`.

---

_Full changelog: [CHANGELOG.md](CHANGELOG.md)_
