# DocKG Release Workflow

Release doc-kg the same way as the generic `/release`, **plus** one thing the generic flow and
the commit hook both miss: the **PyCodeKG** rebuild + snapshot.

**What the commit hook does, and what it deliberately no longer does.** The native
`.git/hooks/pre-commit` (from `dockg install-hooks`) runs the quality checks from
`.pre-commit-config.yaml` and, by default, nothing else. Since 2026-08-18 the index rebuild
and snapshot below them are opt-in:

```bash
[ "${DOCKG_SNAPSHOT:-0}" = "1" ] || exit 0
```

**Do not set `DOCKG_SNAPSHOT=1` to "restore" the old behaviour.** A per-commit snapshot
records `git write-tree` and is then staged into that same commit, so the recorded hash can
never equal the tree it names. An audit of 605 fleet snapshots found only 63 (10.4%) keyed to
a real commit tree. The opt-out exists to stop that; opting back in reintroduces the defect.
See `kgrag_priv/docs/SNAPSHOT_STRATEGY.md`.

The consequence for this workflow: **no snapshot belongs in the release commit** -- not
DocKG's, not PyCodeKG's. The release commit carries version machinery only. PyCodeKG is
snapshotted after the tag, in a follow-up commit (last section); DocKG is not snapshotted at
all until its keying is fixed. Both follow the settled decision in that document.

**Follow the generic `~/.claude/commands/release.md` workflow for all the version machinery**
(detect project → bump → promote CHANGELOG → sync the version string across every file →
write prose `release-notes.md`). Hand off the commit and tag/push per the generic Steps 6-8,
with the doc-kg amendments below, then run the PyCodeKG snapshot step **after the tag is
pushed**.

**Before bumping, check whether the last release actually shipped.** A prepared-but-unshipped
release looks exactly like a finished one from the changelog alone. v0.20.0 sat in this state:
`## [Unreleased]` empty, CHANGELOG promoted and dated, `pyproject.toml`/`README`/`CITATION.cff`
already carrying the new number — but `src/doc_kg/__init__.py` still on the old version, no tag
anywhere, and PyPI a release behind. If the version in `pyproject.toml` has no matching tag,
the job is to *finish that version*, not bump past it:

```bash
git describe --tags --abbrev=0            # newest local tag
git ls-remote --tags origin | grep v0.    # what origin actually has
curl -s https://pypi.org/pypi/doc-kg/json | python3 -c \
  "import sys,json; print(json.load(sys.stdin)['info']['version'])"
```

---

## Then: Hand Off the Commit (generic Step 6, amended)

**Do not run `git commit` yourself.** Stop after staging and write a *detailed* commit message
to `commit.txt` in the repo root (gitignored) for the user to run with `git commit -F
commit.txt`. Title plus a full body: version sync, release notes, header refreshes, release
artifacts with measured numbers, and the post-commit push/tag/publish commands. A bare
`chore(release): vX.Y.Z release notes` is too brief.

The release commit contains version machinery only: no `.dockg/snapshots/` or
`.pycodekg/snapshots/` churn, because nothing generates it at commit time any more. If either
appears in `git status` here, something re-enabled a per-commit snapshot -- find it rather than
committing it.

---

## Then: Tag, Push, and Publish (generic Steps 7–8, amended)

Push the branch, then tag and push per the generic workflow. `.github/workflows/release.yml`
fires on `push: tags: ['v*']` and runs `poetry build` → `gh release create` (notes from
`release-notes.md` in the tagged commit) → a `publish` job that pushes to PyPI via
**OIDC trusted publishing** (`pypa/gh-action-pypi-publish`).

**As of the v0.22.0 release (2026-08-22) this workflow DOES publish to PyPI on its own —
no manual `poetry publish` needed.** This corrects prior guidance here: 0.20.0 shipped a
tag, a green run, and a GitHub Release while PyPI still served 0.19.1, because at that time
the workflow only attached wheel/sdist to the Release and stopped. A `publish` job with
OIDC trusted publishing was added since. Re-check `.github/workflows/release.yml` at release
time rather than trusting this note indefinitely — this is exactly the kind of drift it
already caught the release skill out on once.

Verify it landed rather than assuming:
```bash
gh run watch --exit-status
curl -s https://pypi.org/pypi/doc-kg/json | python3 -c \
  "import sys,json; print(json.load(sys.stdin)['info']['version'])"
```

---

## Then: Fix the Zenodo Record Licence (every release)

Zenodo mints a new record for each GitHub Release and copies the licence from
GitHub's detected licence. GitHub reports Elastic-2.0 as `NOASSERTION`, so Zenodo falls
back to `cc-by-4.0` on every doc-kg archive. Elastic-2.0 has no id in Zenodo's licence
vocabulary, so `.zenodo.json` cannot carry it and the correction cannot be made from
inside the repo. It is a **permanent per-release step**, not a one-time repair.

Wait for the Release run to finish and the archive to appear (`gh release view
vX.Y.Z` first, then the Zenodo API; it can lag a minute or two), then:

```bash
.venv/bin/python scripts/zenodo_license.py --check     # report only
.venv/bin/python scripts/zenodo_license.py             # fix the newest record
```

The script resolves the concept record (`19742773`) to its newest version, opens an
InvenioRDM edit draft, replaces `metadata.rights` with a custom rights object for
Elastic License 2.0, publishes the draft, and reads the record back. Metadata only:
the DOI, version label, and deposited files do not change. It needs `ZENODO_TOKEN`
in the environment with the `deposit:write` and `deposit:actions` scopes. Pass a
record id to target an older version.

Verify through the InvenioRDM representation, not the legacy one. A custom licence
has no legacy id, so the legacy `metadata.license` reads `null` afterwards; that is
expected. The script's final line is the check that matters:

```
record <id>: rights = Elastic License 2.0
```

Do not add `license: Elastic-2.0` to `CITATION.cff` while here: CFF 1.2.0's enum does
not include it and the file would fail validation. `license-url` is the correct encoding.

## Finally: Snapshot PyCodeKG (follow-up commit, after the tag)

Run this **after the tag is pushed**, on the release branch, as its own commit. This is the
one thing the generic `/release` does not do, and the reason this command exists.

```bash
.venv/bin/pycodekg build --repo .
.venv/bin/pycodekg snapshot save --repo .
git add .pycodekg/snapshots/
```

**Both commands are required.** `build` refreshes the graph store and vector index but does
not write a snapshot; only `snapshot save` creates one. Running `build` alone leaves
`.pycodekg/snapshots/` untouched, silently.

**Why after the tag, not before the commit.** The snapshot's key is `git write-tree`. Taken
before the release commit and staged into it, the key names a tree that the commit then
changes -- it can never resolve, which is how 90% of the fleet's snapshots became garbage.
Taken after the tag and committed separately, the key names the tagged commit's tree, which
is real and resolvable. The cost is that `git show vX.Y.Z:.pycodekg/snapshots/` will not find
the snapshot describing that tag: it lives one commit later, on the branch. That is the
accepted trade in `kgrag_priv/docs/SNAPSHOT_STRATEGY.md`, not an oversight.

**Still keyed on the tree, not the tag.** Phase 3 of that plan re-keys snapshots on the
version string, but it has not landed -- `src/doc_kg/snapshots.py` still hardcodes
`"key": self.tree_hash`, as do `pycode_kg`, `memory_kg` and `Metabo_kg`. The follow-up-commit
ordering above is what makes a tree key valid in the meantime. When Phase 3 lands, pass the
version explicitly and revisit this section.

DocKG's own snapshot is **not** taken here. Its keying has the same gap and no release step
is wired for it yet; leaving it out is better than writing another unresolvable key.

Completion summary should additionally note:
```
✓ commit.txt written for the user to commit
✓ Release commit carries version machinery only (no snapshot churn)
✓ PyCodeKG rebuilt + snapshot saved in a follow-up commit AFTER the tag
✓ Published to PyPI (verify against pypi.org/pypi/doc-kg/json after the tag-push run finishes)
```
