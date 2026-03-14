"""
cmd_hooks.py

CLI command for installing DocKG git hooks:

  install-hooks — install the pre-commit snapshot hook into .git/hooks/

  Author: Eric G. Suchanek, PhD
  Last Revision: 2026-03-12
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
# DocKG pre-commit hook — runs quality checks, rebuilds the index, captures snapshot.
# Installed by: dockg install-hooks
# Skip with: DOCKG_SKIP_SNAPSHOT=1 git commit ...
set -euo pipefail

[ "${DOCKG_SKIP_SNAPSHOT:-0}" = "1" ] && exit 0

REPO_ROOT="$(git rev-parse --show-toplevel)"

# Run pre-commit framework checks (ruff, mypy, detect-secrets, etc.)
# Delegates to .pre-commit-config.yaml so quality checks stay in one place.
PRECOMMIT="$REPO_ROOT/.venv/bin/pre-commit"
if [ -x "$PRECOMMIT" ]; then
    "$PRECOMMIT" run || exit 1
elif command -v pre-commit &>/dev/null; then
    pre-commit run || exit 1
fi

cd "$REPO_ROOT"

VERSION=$(grep '^version' pyproject.toml 2>/dev/null | head -1 | cut -d'"' -f2)
TREE_HASH=$(git write-tree)
BRANCH=$(git rev-parse --abbrev-ref HEAD)

# Rebuild local DocKG index to keep it in sync
"$REPO_ROOT/.venv/bin/dockg" build --wipe || exit 1

"$REPO_ROOT/.venv/bin/dockg" snapshot save "${VERSION:-unknown}" \\
    --repo . \\
    --commit "$TREE_HASH" \\
    --branch "$BRANCH" \\
  || { echo "[dockg] snapshot skipped (run 'dockg build' to initialize)" >&2; exit 0; }

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

    After installation, a metrics snapshot is captured automatically before
    each commit, keyed by the commit hash. The snapshot file is staged
    and included in the commit atomically.

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
