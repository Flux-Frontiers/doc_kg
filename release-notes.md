# Release Notes — v0.21.2

> Released: 2026-08-14

A dependency-floor release from the fleet-wide sweep. No code changed — the
wheel's contents are identical to 0.21.1 — but the requirements it declares
moved to match what the fleet actually runs against today.

## What changed

**The shared SDK floor caught up with the fleet.** doc-kg now requires
`kgmodule-utils[semantic]>=0.12.1`, up from `>=0.10.0`. The old floor was
honest when it was written, but every sibling in the fleet has since moved to
the 0.12.x line, and letting resolvers pick a two-minor-old SDK invited
combinations nobody tests. Nothing in doc-kg's own code needed updating —
the floor now simply states the environment the test suite actually exercises.

**pytest moved past a security advisory.** The dev group's floor rose from
`>=8.0.0` to `>=9.0.3`, clearing GHSA-6w46-j5rx-g56g. This is test tooling
only; it does not affect what `pip install doc-kg` brings in.

**ruff is capped below 0.16.** Ruff minors routinely enable new default rules,
and an uncapped floor meant a fresh `poetry install` could start failing lint
on code that was green yesterday. The cap makes ruff upgrades a deliberate,
reviewed change rather than something CI discovers on its own.

**Maintainer tooling floors moved too.** The optional `kg` Poetry group now
asks for `pycode-kg>=0.22.0`. As before, groups never reach the wheel's
metadata, so consumers see none of this.

## Upgrading

Nothing to do. No API, CLI, or index-format change; existing `.dockg/` stores
keep working as-is. A `poetry update kgmodule-utils` (or a plain
`pip install -U doc-kg`) picks up the new SDK line.

---

_Full changelog: [CHANGELOG.md](CHANGELOG.md)_
