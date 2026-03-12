#!/usr/bin/env bash
# install-hooks.sh — Install DocKG git hooks into .git/hooks/
#
# Usage:
#   ./scripts/install-hooks.sh [--force]
#
# Installs a pre-commit hook that captures a DocKG metrics snapshot before
# each commit. The snapshot file is staged and included in the commit.
#
# Skip with: DOCKG_SKIP_SNAPSHOT=1 git commit ...

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
# DocKG pre-commit hook — captures a metrics snapshot keyed by tree hash.
# Installed by: scripts/install-hooks.sh
# Skip with: DOCKG_SKIP_SNAPSHOT=1 git commit ...
set -euo pipefail

[ "${DOCKG_SKIP_SNAPSHOT:-0}" = "1" ] && exit 0

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

VERSION=$(grep '^version' pyproject.toml 2>/dev/null | head -1 | cut -d'"' -f2)
TREE_HASH=$(git write-tree)
BRANCH=$(git rev-parse --abbrev-ref HEAD)

"$REPO_ROOT/.venv/bin/dockg" snapshot save "${VERSION:-unknown}" \
    --repo . \
    --commit "$TREE_HASH" \
    --branch "$BRANCH" \
  || { echo "[dockg] snapshot skipped (run 'dockg build' to initialize)" >&2; exit 0; }

git add -f .dockg/snapshots/ 2>/dev/null || true

exit 0
HOOK

chmod +x "$HOOK_PATH"

echo "✓ Installed pre-commit hook: $HOOK_PATH"
echo "  Snapshots will be captured automatically before each commit."
echo "  Run 'dockg build' first if you haven't built the graph yet."
echo "  Skip with: DOCKG_SKIP_SNAPSHOT=1 git commit ..."
