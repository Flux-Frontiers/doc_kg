# Release Notes — v0.20.0

> Released: 2026-07-31

**`lancedb` is no longer a dependency of DocKG.** Installing `doc-kg` no longer
drags LanceDB and its transitive weight into your environment; the vector
backend is sqlite-vec, now a core dependency and the default. LanceDB survives
as an optional `[lancedb]` extra whose only job is to *read* a pre-0.20.0 store
long enough to convert it. This is the last repo-level step of the fleet-wide
sqlite-vec migration, and the one that actually removes the package from
downstream installs — every sibling that depends on doc-kg was still getting
`lancedb` transitively no matter what it declared for itself.

## What changed

**The default backend is now a declaration, not an inference.** `vector_backend`
previously defaulted to `"auto"`, which resolved per-store from whatever
happened to be on disk — so a corpus stayed on LanceDB purely because a
`lancedb/` directory existed next to it. That is the trap that let a repo look
migrated in its source while still running the retired backend in practice. The
default is now `"sqlite-vec"` outright. `auto` and `lancedb` still resolve when
asked for explicitly, both now require the extra, and `$DOCKG_VECTOR_BACKEND`
still overrides everything. Correspondingly, a bare `SemanticIndex` builds a
`SqliteVecBackend` at the sidecar derived from `lancedb_dir` rather than
reaching for a package that may not be installed.

**Asking for LanceDB without the extra fails with instructions.** Instead of a
bare `ImportError` on a missing module, the error names the extra, the install
command, and the one-time `convert-index` migration.

**Packaging.** `sqlite-vec` moved from an extra to a core dependency, pinned
exactly at `==0.1.9` — it is pre-1.0 and a breaking minor is a real
possibility. The `[sqlite-vec]` extra is deliberately retained as an empty
no-op alias so `pip install 'doc-kg[sqlite-vec]'` still resolves; sister
packages pin it that way and removing it would break their installs. `lancedb`
is *not* folded into `[all]` — that would put the weight straight back into the
common "install everything" path.

**Documentation.** The LanceDB assumption ran through most of the docs and has
been corrected across README, CLI, MCP, SCHEMA, SNAPSHOTS, INSTALLATION,
ingestion, workflow, deployment, and the cheatsheet. `INSTALLATION.md` was the
worst of it — it told readers DocKG *requires* `lancedb>=0.29.0` and to upgrade
it when the API errored. The ANN design doc is left as written with a scope
note: ANN is a LanceDB-only concern, since sqlite-vec is always an exact flat
scan, so it now documents an opt-in path rather than the default one.

## Upgrading

If you have never had a LanceDB store, upgrade and carry on — `pip install
--upgrade doc-kg`, and your next build writes sqlite-vec.

If you do have one, nothing is stranded. `dockg convert-index` is unchanged and
reads vectors straight out of the LanceDB store with no re-embedding:

```bash
pip install 'doc-kg[lancedb]'
dockg convert-index --repo . --delete-lancedb
```

The one behavioural change to watch for is the default: code that relied on
`auto` silently selecting LanceDB from an on-disk directory must now name
`lancedb` explicitly, and install the extra, to keep that behaviour.

---

_Full changelog: [CHANGELOG.md](CHANGELOG.md)_
