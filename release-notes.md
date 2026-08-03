# Release Notes — v0.21.1

> Released: 2026-08-03

A truth-in-output release. Nothing about how DocKG works changed; what it
*tells you* about how it works did.

## The CLI was describing a backend it no longer writes

The sqlite-vec migration landed in 0.20.0 and the store moved to
`.dockg/vectors.sqlite`. The help strings did not follow. `dockg build` printed

```
  vector index : /your/corpus/.dockg/lancedb
```

on every run — naming a directory the default backend never creates — while the
vectors went somewhere else entirely. `build-index`, `build-index-from-cache`,
`build-two-phase` and the MCP server banner all had the same bug. The banner was
worse: it reported `vectors : (derived)`, a placeholder standing exactly where
the resolved path belonged.

None of this affected retrieval. All of it affected anyone trying to find, back
up, or reason about their vector store.

Every build header now reports the store that will actually be opened, and the
LanceDB-only `table` line appears only when the resolved backend is LanceDB.
The docstrings and `--help` text were swept to match. LanceDB is still named
where it is genuinely the subject — `convert-index`, the `[lancedb]` extra, the
legacy `--lancedb` anchor — but every mention is now qualified as such.

## `pycode-kg` is tooling, not a dependency

`pycode-kg` had been added to doc-kg's **core runtime dependencies**, where it
would have made every consumer of this package install something doc-kg imports
nowhere — along with the `pandas` and `networkx` it carries, which 0.21.0 had
just finished removing from this project's dependency set. It was caught in the
working tree and never shipped.

It *is* genuinely needed: the release workflow rebuilds the PyCodeKG index and
`.mcp.json` serves it. But it is needed by the maintainer, not by the library.
So rather than deleting it outright, it moved to a Poetry group:

```
poetry install --with kg      # gets the pycodekg CLI into .venv/bin
poetry install                # default — group is optional, skipped
```

Groups are locked and installable but are not written into the wheel's metadata,
so no published extra picks it up. `pip install doc-kg[dev]` is unaffected, and
the wheel's core dependency list is unchanged at seven packages.

The old policy note in `pyproject.toml` said siblings must never be declared
because doc-kg and pycode-kg depend on each other. That is no longer true —
pycode-kg dropped its doc-kg dependency as of 0.21.4 — so the note was updated
to say what actually holds now, and why the group is the safe place for it.

## CI now checks the wheel three ways instead of one

0.21.0 added a job that installs the built wheel into a clean venv and loads
every console-script entry point. That gate is real, but it has blind spots: a
module no entry point reaches is invisible to it, and loading an entry point
proves the code imports, not that it runs.

The job now runs three gates against the artifact users actually receive:

1. **Every console script loads on a core-only install.** Unchanged, and
   core-only is the point — it also guards the lazy-import discipline that keeps
   `dockg viz` working without streamlit installed.
2. **A real corpus builds and answers a query**, still core-only, so this is the
   default `pip install doc-kg` doing actual work. Model weights are cached.
3. **Every packaged submodule imports** with the extras installed. `doc_kg.app`
   is exactly the module gates 1 and 2 cannot see: no entry point reaches it and
   it needs `[viz]`.

Two regression guards went into the test suite alongside: one asserts that no
command's `--help` presents LanceDB as the default store, the other asserts that
the new reporting properties agree with the backend that actually gets
constructed.

The deprecated Node 20 actions (`checkout`, `setup-python`, `cache`) were bumped
to current majors, clearing the warnings on every run.
