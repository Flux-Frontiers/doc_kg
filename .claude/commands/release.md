# Release Workflow

You will create a new versioned release by promoting the `[Unreleased]` section of `CHANGELOG.md` into a dated version entry, writing `release-notes.md`, committing the changes, tagging the commit, and pushing the tag to the remote. Execute the following steps in sequence.

---

## Step 0: Gather Release Context

1. Read `CHANGELOG.md` in full.
2. Read `pyproject.toml` and `src/doc_kg/__init__.py` to find the current version string.
3. Run `git status` and `git log --oneline -10` to understand the state of the working tree.
4. Confirm there is content under `## [Unreleased]`; if the section is empty, stop and tell the user there is nothing to release.

---

## Step 1: Determine the New Version

1. Parse the current version from `pyproject.toml` (e.g. `0.2.1`).
2. Ask the user which semver component to bump — **patch**, **minor**, or **major** — unless they already specified it in their message (e.g. `/release minor`).
3. Compute the new version string (e.g. `0.2.1` → `0.3.0` for minor).
4. Confirm the new tag will be `v<new_version>` (e.g. `v0.3.0`).

---

## Step 2: Update CHANGELOG.md

1. Replace `## [Unreleased]` with `## [<new_version>] - <today's date in YYYY-MM-DD>`.
2. Insert a fresh `## [Unreleased]` section with empty `### Added`, `### Changed`, `### Removed`, `### Fixed` subsections **above** the newly-versioned section.
3. Write the updated file.

---

## Step 3: Bump the Version in Source Files

Update the version string in **both** of the following files:

- `pyproject.toml` — the `version = "..."` field under `[tool.poetry]`
- `src/doc_kg/__init__.py` — the `__version__` assignment

Set both to the new version string (without the `v` prefix).

---

## Step 4: Write release-notes.md

Create (or overwrite) `release-notes.md` in the project root with the following structure:

```markdown
# Release Notes — v<new_version>

> Released: <today's date in YYYY-MM-DD>

<copy the full content of the promoted [Unreleased] section verbatim — all subsections and bullet points>

---

_Full changelog: [CHANGELOG.md](CHANGELOG.md)_
```

Do not summarise or rewrite the changelog content — copy it exactly.

---

## Step 4b: Update Version Badge in README.md

In `README.md`, find the version badge line:

```
[![Version](https://img.shields.io/badge/version-<current_version>-blue.svg)](https://github.com/Flux-Frontiers/code_kg/releases)
```

Replace `<current_version>` with `<new_version>` (e.g. `0.2.3` → `0.2.4`).

---

## Step 4c: Rebuild Knowledge Graphs & Generate Analysis

**CodeKG Build & Snapshot:**
1. Rebuild the CodeKG index against the current source:
   ```bash
   .venv/bin/pycodekg build --repo .
   ```
2. CodeKG snapshot is automatically saved by pre-commit hook; verify `.pycodekg/snapshots/manifest.json` was updated.
3. Stage the CodeKG artifacts:
   ```bash
   git add .pycodekg/snapshots/
   ```

**DocKG Build & Analysis:**
1. Rebuild the DocKG index against the current source (default is full wipe-and-rebuild; no flag needed):
   ```bash
   poetry run dockg build --repo .
   ```
2. Run the thorough analysis:
   ```bash
   poetry run dockg analyze --repo .
   ```
   Output is saved to `analysis/doc_kg_analysis_<date>.md` automatically.
3. Open the analysis file and ensure the header contains:
   ```
   **Version:** <new_version>
   **Generated:** <today's date in YYYY-MM-DD>
   ```
   Add or update these fields if missing.
4. DocKG snapshot is automatically saved by the analyze process; verify `.dockg/snapshots/manifest.json` was updated.
5. Stage the generated artifacts:
   ```bash
   git add analysis/doc_kg_analysis_*.md
   git add .dockg/
   ```

---

## Step 5: Commit the Release Files

1. Ensure all files from Step 4c are staged (`git add -A` to catch all changes).
2. Stage the following core release files explicitly:
   - `CHANGELOG.md`
   - `release-notes.md`
   - `pyproject.toml`
   - `src/doc_kg/__init__.py`
   - `README.md`
   - `analysis/doc_kg_analysis_*.md`
   - `.pycodekg/snapshots/` (CodeKG snapshots — lancedb/sqlite are gitignored)
   - `.dockg/snapshots/` (DocKG snapshots — lancedb/sqlite are gitignored)
3. Create a commit with message:
   ```
   chore(release): v<new_version> release notes

   Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
   ```

---

## Step 6: Create the Git Tag

Run:
```bash
git tag -a v<new_version> -m "v<new_version>"
```

---

## Step 7: Push the Tag

**Before pushing**, display the tag name and ask the user to confirm:

> Ready to push tag `v<new_version>` to `origin`. Proceed? (yes / no)

If confirmed, run:
```bash
git push origin v<new_version>
```

If the user declines, tell them they can push later with:
```bash
git push origin v<new_version>
```

---

## Completion

After all steps succeed, print a summary:

```
✓ CHANGELOG.md promoted [Unreleased] → [<new_version>] - <date>
✓ release-notes.md written
✓ pyproject.toml + src/doc_kg/__init__.py bumped to <new_version>
✓ README.md version badge updated
✓ CodeKG indices rebuilt (SQLite + LanceDB) with snapshot
✓ DocKG indices rebuilt with analysis generated
✓ Both .pycodekg/snapshots/ and .dockg/snapshots/ staged
✓ Commit created (chore(release): v<new_version>)
✓ Tag v<new_version> created
✓ Tag pushed to origin   (or: tag ready to push manually)
```
