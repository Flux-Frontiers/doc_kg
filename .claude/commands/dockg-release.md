# DocKG Release Workflow

Release doc-kg the same way as the generic `/release`, **plus** rebuild the knowledge-graph
artifacts (DocKG + PyCodeKG) and stage their snapshots into the release commit. Nothing else
rebuilds these — the pre-commit hooks only run ruff/ty/pytest and *exclude* the snapshot
dirs, so a plain `/release` would ship stale `.dockg/` / `.pycodekg/` snapshots.

**Follow the generic `~/.claude/commands/release.md` workflow for all the version machinery**
(detect project → bump → promote CHANGELOG → sync the version string across every file →
write prose `release-notes.md`). Insert the DocKG step below **after the version bump** (so
the analysis header carries the new version) and **before the commit** (so the artifacts land
in the release commit). Then commit/tag/push per the generic Steps 5–7.

---

## Insert: Rebuild KG Artifacts & Snapshots

Do this once the new version is written into `pyproject.toml` and `src/doc_kg/__init__.py`.

**PyCodeKG (code graph):**
```bash
.venv/bin/pycodekg build --repo .
```
The snapshot is written to `.pycodekg/snapshots/` (manifest updated automatically).

**DocKG (document graph + analysis):**
```bash
poetry run dockg build --repo .        # full wipe-and-rebuild (default)
poetry run dockg analyze --repo .      # writes analysis/doc_kg_analysis_<date>.md + snapshot
```
Open the generated `analysis/doc_kg_analysis_<date>.md` and confirm the header shows:
```
**Version:** <new_version>
**Generated:** <today YYYY-MM-DD>
```
Add/fix those fields if missing.

**Stage the artifacts** (the lancedb/sqlite payloads are gitignored — only snapshots +
analysis are tracked):
```bash
git add .pycodekg/snapshots/ .dockg/snapshots/ analysis/doc_kg_analysis_*.md
```

---

## Then: Commit, Tag, Push (generic Steps 5–7)

Fold the staged KG artifacts into the release commit alongside `CHANGELOG.md`,
`release-notes.md`, `pyproject.toml`, `src/doc_kg/__init__.py`, and `README.md`. Use the
standard commit message and confirm before pushing the tag, exactly as the generic workflow
describes.

Completion summary should additionally note:
```
✓ PyCodeKG rebuilt + snapshot staged (.pycodekg/snapshots/)
✓ DocKG rebuilt, analysis generated, snapshot staged (.dockg/snapshots/, analysis/)
```
