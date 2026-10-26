# DocKG Release Workflow

Release doc-kg the same way as the generic `/release`, **plus** one thing it does not do:
doc_kg indexes itself with **both** DocKG and PyCodeKG, so its release commit carries two
version-keyed snapshots, not one.

**What the commit hook does.** The native `.git/hooks/pre-commit` (from `dockg install-hooks`)
runs the quality checks from `.pre-commit-config.yaml` and, by default, nothing else. Since
2026-08-18 the index rebuild and snapshot below them are opt-in:

```bash
[ "${DOCKG_SNAPSHOT:-0}" = "1" ] || exit 0
```

Leave it off for a release. The release snapshots are taken explicitly in Step 5b below, keyed
on the version; a per-commit snapshot would only add an unkeyed one beside them. Background:
`kgrag_priv/docs/SNAPSHOT_STRATEGY.md`.

**Follow the generic `~/.claude/commands/release.md` workflow for all the version machinery**
(detect project -> bump -> promote CHANGELOG -> sync the version string across every file ->
write prose `release-notes.md` -> Step 5b snapshot), with the doc-kg amendments below.

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

## Step 5b, amended: Snapshot DocKG and PyCodeKG (both in the release commit)

After the version bump and reinstall, before the commit. Rebuild both indices, then save one
snapshot per tool, keyed on the new version:

```bash
dockg build --repo .
pycodekg build --repo .
dockg snapshot save <new_version> --repo . --subject repo:doc-kg
pycodekg snapshot save <new_version> --repo . --subject repo:doc-kg
ls .dockg/snapshots/<new_version>.json .pycodekg/snapshots/<new_version>.json
```

**Both builds and both saves are required.** `build` refreshes the graph and vectors but writes
no snapshot, and `save` refuses an empty graph. `pycodekg` is the global `uv tool`, not a venv
dependency (the `kg` Poetry groups were retired fleet-wide in 2026-09). Releases 0.28.0 and
0.28.1 carried only the DocKG snapshot; the PyCodeKG one was missed, which is why this step
names both.

Stage both `<new_version>.json` files and both `manifest.json` files with the release in Step 6.


---

## Then: Hand Off the Commit (generic Step 6, amended)

**Do not run `git commit` yourself.** Stop after staging and write a *detailed* commit message
to `commit.txt` in the repo root (gitignored) for the user to run with `git commit -F
commit.txt`. Title plus a full body: version sync, release notes, header refreshes, release
artifacts with measured numbers, and the post-commit push/tag/publish commands. A bare
`chore(release): vX.Y.Z release notes` is too brief.

The release commit carries the version machinery plus the two snapshots from Step 5b. Any
other `.dockg/snapshots/` or `.pycodekg/snapshots/` churn in `git status` means something
re-enabled a per-commit snapshot -- find it rather than committing it.

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

Completion summary should additionally note:
```
OK commit.txt written for the user to commit
OK DocKG and PyCodeKG snapshots saved, keyed on <new_version>, in the release commit
OK Published to PyPI (verify against pypi.org/pypi/doc-kg/json after the tag-push run finishes)
OK Zenodo record licence set to Elastic-2.0
```
