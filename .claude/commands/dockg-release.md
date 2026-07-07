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
the commit** (so the snapshot lands in the release commit). Then commit/tag/push per the
generic Steps 5–7.

---

## Insert: Rebuild PyCodeKG

Do this once the new version is written into `pyproject.toml` and `src/doc_kg/__init__.py`.

```bash
.venv/bin/pycodekg build --repo .
```
The snapshot is written to `.pycodekg/snapshots/` (manifest updated automatically). Stage it —
the lancedb/sqlite payloads are gitignored, only the snapshot is tracked:
```bash
git add .pycodekg/snapshots/
```

---

## Then: Commit, Tag, Push (generic Steps 5–7)

Fold the staged snapshot into the release commit alongside `CHANGELOG.md`, `release-notes.md`,
`pyproject.toml`, `src/doc_kg/__init__.py`, and `README.md`. Use the standard commit message
and confirm before pushing the tag, exactly as the generic workflow describes. Do **not** use
`git commit -o <paths>` — it bypasses the hook's `git add` and leaves the fresh
`.dockg/snapshots/` churn uncommitted; let the commit stage the tree normally.

Completion summary should additionally note:
```
✓ PyCodeKG rebuilt + snapshot staged (.pycodekg/snapshots/)
✓ DocKG index + snapshot refreshed by commit hook
```
