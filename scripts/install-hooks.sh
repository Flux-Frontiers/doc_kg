#!/usr/bin/env bash
# install-hooks.sh — Install DocKG git hooks into .git/hooks/
#
# Usage:
#   ./scripts/install-hooks.sh [--force]
#
# Installs a pre-commit hook that runs the quality checks. A DocKG metrics
# snapshot is opt-in and off by default (DOCKG_SNAPSHOT=1).
#
# Force off with: DOCKG_SKIP_SNAPSHOT=1 git commit ...

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
HOOKS_DIR="$REPO_ROOT/.git/hooks"
HOOK_PATH="$HOOKS_DIR/pre-commit"
FORCE=0

for arg in "$@"; do
    case "$arg" in
        --force) FORCE=1 ;;
        *) echo "Unknown argument: $arg" >&2; exit 1 ;;
    esac
done

if [ -f "$HOOK_PATH" ] && [ "$FORCE" -eq 0 ]; then
    echo "Hook already exists: $HOOK_PATH"
    echo "Use --force to overwrite."
    exit 1
fi

mkdir -p "$HOOKS_DIR"

cat > "$HOOK_PATH" << 'HOOK'
#!/usr/bin/env bash
# DocKG pre-commit hook — runs quality checks. The index rebuild and metrics
# snapshot are opt-in and OFF by default; see "Why snapshots are off" below.
# Installed by: scripts/install-hooks.sh
#
#   DOCKG_SNAPSHOT=1 git commit ...        opt in to a per-commit snapshot
#   DOCKG_SKIP_SNAPSHOT=1 git commit ...   force snapshots off (wins)
#
# Note that DOCKG_SKIP_SNAPSHOT no longer skips the quality checks. It used to
# short-circuit the whole hook, so a variable named "skip snapshot" also
# silently skipped ruff, ty and pytest. It now gates only what it names.
#
# Why snapshots are off by default (2026-08-18)
# ---------------------------------------------
# A per-commit snapshot records `git write-tree` and is then itself staged into
# that same commit. Staging changes the index, so the recorded hash can never
# equal the tree it claims to describe — and manifest.json carries a
# `last_update` timestamp, so the `git add` is never a no-op. The drift is
# guaranteed by construction, not caused by formatting.
#
# An audit of 605 snapshots across 29 fleet manifests found 63 (10.4%) keyed to
# a tree any commit actually has; this repo's .dockg manifest held 98, of which
# 5 qualified. `snapshot diff` between adjacent entries has therefore been
# comparing states that never existed.
#
# The fix is to snapshot at release, keyed on the tag rather than on an
# ephemeral pre-commit tree. See kgrag_priv/docs/SNAPSHOT_STRATEGY.md. Until
# that lands, this hook runs quality checks only.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

# Quality checks first (ruff, ty, pytest, detect-secrets, ...). Delegates to
# .pre-commit-config.yaml so quality checks stay in one place. A hook that
# rewrites files also exits non-zero here, so we never index a tree that is
# about to be reformatted. This script used to emit a hook with no quality
# checks at all, while the hook actually installed here had them — the two had
# drifted apart, and regenerating would have silently dropped them.
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
VERSION=$(grep '^version' pyproject.toml 2>/dev/null | head -1 | cut -d'"' -f2)
TREE_HASH=$(git write-tree)
BRANCH=$(git rev-parse --abbrev-ref HEAD)

"$REPO_ROOT/.venv/bin/dockg" build || exit 1

"$REPO_ROOT/.venv/bin/dockg" snapshot save "${VERSION:-unknown}" \
    --repo . \
    --tree-hash "$TREE_HASH" \
    --branch "$BRANCH" \
  || { echo "[dockg] snapshot skipped (run 'dockg build' to initialize)" >&2; exit 0; }

# Stage the snapshot directory so it is included in the commit. These files are
# added after `pre-commit run`, so they are not scanned by it — detect-secrets
# already excludes snapshots/ by config, which is why that is safe.
git add .dockg/snapshots/ 2>/dev/null || true

exit 0
HOOK

chmod +x "$HOOK_PATH"

echo "✓ Installed pre-commit hook: $HOOK_PATH"
echo "  Quality checks run on every commit."
echo "  Run 'dockg build' first if you haven't built the graph yet."
echo "  Snapshots are OFF by default -- see kgrag_priv/docs/SNAPSHOT_STRATEGY.md."
echo "  Opt in with:  DOCKG_SNAPSHOT=1 git commit ..."
echo "  Force off:    DOCKG_SKIP_SNAPSHOT=1 git commit ..."
