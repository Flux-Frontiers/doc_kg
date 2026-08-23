# DocKG Release Workflow

Release doc-kg the same way as the generic `/release`, **plus** one thing the generic flow and
the commit hook both miss: the **PyCodeKG** rebuild + snapshot.

**What the commit hook already handles (don't repeat it):** the native `.git/hooks/pre-commit`
(from `dockg install-hooks`) runs `dockg build` → `dockg snapshot save` → stages
`.dockg/snapshots/` on every commit. So the DocKG index and its snapshot refresh
automatically when you commit — you do **not** build/snapshot DocKG by hand. It never touches
PyCodeKG, and `.pycodekg/snapshots/` moves only in release commits — that gap is why this
command exists.

**Follow the generic `~/.claude/commands/release.md` workflow for all the version machinery**
(detect project → bump → promote CHANGELOG → sync the version string across every file →
write prose `release-notes.md`). Insert the step below **after the version bump** and **before
the commit** (so the snapshot lands in the release commit). Then hand off the commit and
tag/push per the generic Steps 6–8, with the two doc-kg amendments at the bottom of this file.

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

## Insert: Rebuild PyCodeKG

Do this once the new version is written into `pyproject.toml` and `src/doc_kg/__init__.py`.

```bash
.venv/bin/pycodekg build --repo .
.venv/bin/pycodekg snapshot save --repo .
```

**Both commands are required.** `build` refreshes the graph store and vector index but does
**not** write a snapshot — snapshots are keyed by commit SHA and only `snapshot save` creates
one. Running `build` alone leaves `.pycodekg/snapshots/` untouched and the release commit
carries no snapshot at all, silently.

`snapshot save` runs the 15-phase analysis and writes `<sha>.json` plus a manifest entry.
Stage it — the vector/sqlite payloads are gitignored, only the snapshot is tracked:
```bash
git add .pycodekg/snapshots/
```
Note the snapshot is keyed to the *current* HEAD, i.e. the release commit's parent. That is
the same behaviour as the DocKG pre-commit hook and is expected, not a bug.

---

## Then: Hand Off the Commit (generic Step 6, amended)

**Do not run `git commit` yourself.** Stop after staging and write a *detailed* commit message
to `commit.txt` in the repo root (gitignored) for the user to run with `git commit -F
commit.txt`. Title plus a full body: version sync, release notes, header refreshes, release
artifacts with measured numbers, and the post-commit push/tag/publish commands. A bare
`chore(release): vX.Y.Z release notes` is too brief.

When the user does commit, do **not** suggest `git commit -o <paths>` — it bypasses the hook's
`git add` and leaves the fresh `.dockg/snapshots/` churn uncommitted; let the commit stage the
tree normally.

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

Completion summary should additionally note:
```
✓ PyCodeKG rebuilt + snapshot saved and staged (.pycodekg/snapshots/)
✓ DocKG index + snapshot refreshed by commit hook
✓ commit.txt written for the user to commit
✓ Published to PyPI (verify against pypi.org/pypi/doc-kg/json after the tag-push run finishes)
```
