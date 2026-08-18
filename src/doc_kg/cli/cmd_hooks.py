"""
cmd_hooks.py

CLI command for installing DocKG git hooks:

  install-hooks — install the pre-commit snapshot hook into .git/hooks/

  Author: Eric G. Suchanek, PhD
"""

from __future__ import annotations

import stat
from pathlib import Path

import click

from doc_kg.cli.group import cli

# ---------------------------------------------------------------------------
# Hook script content (embedded so this module is self-contained when
# installed as a package in any repo, not just doc_kg itself)
# ---------------------------------------------------------------------------

_PRE_COMMIT_HOOK = """\
#!/usr/bin/env bash
# DocKG pre-commit hook — runs quality checks first, then rebuilds the local
# index and captures a metrics snapshot.
# Installed by: dockg install-hooks
# Skip with: DOCKG_SKIP_SNAPSHOT=1 git commit ...
#
# Order matters, and it is deliberately checks-then-index:
#
#   * `pre-commit run` stashes unstaged changes and restores them afterwards.
#     Rebuilding the index before that ran meant the build's freshly-rewritten
#     snapshots/manifest.json landed inside the stash window, where the restore
#     could fail with "patch does not apply" and abort the commit outright — or,
#     worse, let a staged deletion of a tracked snapshot slip into the commit.
#     Building afterwards keeps KG artifacts entirely outside that window.
#   * A full index rebuild is slow. There is no reason to pay it for a commit
#     that ruff/ty/pytest is about to reject.
#
# Snapshots are opt-in and OFF by default (2026-08-18):
#
#   DOCKG_SNAPSHOT=1 git commit ...        opt in to a per-commit snapshot
#   DOCKG_SKIP_SNAPSHOT=1 git commit ...   force snapshots off (wins)
#
# DOCKG_SKIP_SNAPSHOT no longer skips the quality checks. It used to
# short-circuit the whole hook, so a variable named "skip snapshot" also
# silently skipped ruff, ty and pytest. It now gates only what it names.
#
# A per-commit snapshot records `git write-tree` and is then staged into that
# same commit, so the recorded hash can never equal the tree it names — an
# audit of 605 fleet snapshots found only 63 (10.4%) keyed to a real commit
# tree. The fix is to snapshot at release, keyed on the tag; until that lands
# this hook runs quality checks only.
# See kgrag_priv/docs/SNAPSHOT_STRATEGY.md.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"

cd "$REPO_ROOT"

# Quality checks first (ruff, ty, pytest, detect-secrets, ...). Delegates to
# .pre-commit-config.yaml so quality checks stay in one place. A hook that
# rewrites files also exits non-zero here, so we never index a tree that is
# about to be reformatted.
PRECOMMIT="$REPO_ROOT/.venv/bin/pre-commit"
if [ -x "$PRECOMMIT" ]; then
    "$PRECOMMIT" run || exit 1
elif command -v pre-commit &>/dev/null; then
    pre-commit run || exit 1
fi

# ---------------------------------------------------------------------------
# Opt-in index rebuild + snapshot. Everything below is skipped unless
# DOCKG_SNAPSHOT=1 is set, and is skipped regardless if DOCKG_SKIP_SNAPSHOT=1.
# ---------------------------------------------------------------------------
[ "${DOCKG_SNAPSHOT:-0}" = "1" ] || exit 0
[ "${DOCKG_SKIP_SNAPSHOT:-0}" = "1" ] && exit 0

# Captured after the checks so nothing further modifies the working tree. Note
# the caveat above: this still cannot match the committed tree, because the
# `git add` below changes the index after this point.
TREE_HASH=$(git write-tree)
BRANCH=$(git rev-parse --abbrev-ref HEAD)

# Rebuild local DocKG index to keep it in sync with staged content.
"$REPO_ROOT/.venv/bin/dockg" build || exit 1

# Snapshot DocKG (version auto-detected from installed package).
"$REPO_ROOT/.venv/bin/dockg" snapshot save \\
    --repo . \\
    --tree-hash "$TREE_HASH" \\
    --branch "$BRANCH" \\
  || { echo "[dockg] snapshot skipped (run 'dockg build' to initialize)" >&2; }

# Stage snapshot directory so it is included in the commit. These files are
# added after `pre-commit run`, so they are not scanned by it — detect-secrets
# already excludes snapshots/ by config, which is why that is safe.
git add .dockg/snapshots/ 2>/dev/null || true

exit 0
"""


@cli.command("install-hooks")
@click.option(
    "--repo",
    default=".",
    type=click.Path(exists=True),
    show_default=True,
    help="Repository root.",
)
@click.option(
    "--force",
    is_flag=True,
    help="Overwrite an existing pre-commit hook.",
)
def install_hooks(repo: str, force: bool) -> None:
    """Install the DocKG pre-commit git hook.

    After installation, before each commit:
      1. Runs pre-commit framework checks (ruff, mypy, detect-secrets)
      2. Rebuilds local DocKG index (wipe by default)
      3. Captures a metrics snapshot (version auto-detected from installed package)
      4. Stages .dockg/snapshots/ atomically

    Skip with: DOCKG_SKIP_SNAPSHOT=1 git commit ...

    Example:
        dockg install-hooks --repo .
    """
    repo_root = Path(repo).resolve()
    git_dir = repo_root / ".git"

    if not git_dir.is_dir():
        click.echo(f"Error: {repo_root} is not a git repository.", err=True)
        raise SystemExit(1)

    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir(exist_ok=True)
    hook_path = hooks_dir / "pre-commit"

    if hook_path.exists() and not force:
        click.echo(f"Hook already exists: {hook_path}")
        click.echo("Use --force to overwrite.")
        raise SystemExit(1)

    hook_path.write_text(_PRE_COMMIT_HOOK)
    mode = hook_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    hook_path.chmod(mode)

    click.echo(f"OK Installed pre-commit hook: {hook_path}")
    click.echo("  Snapshots will be captured automatically before each commit.")
    click.echo("  Run 'dockg build' first if you haven't built the graph yet.")
