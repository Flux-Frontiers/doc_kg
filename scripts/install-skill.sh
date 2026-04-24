#!/usr/bin/env bash
# =============================================================================
# install-skill.sh — Bootstrap the DocKG AI integration layer
#
# Installs SKILL.md reference files and the /dockg slash command for AI agents,
# then configures MCP server integration for the specified providers.
#
# Supported providers:
#   claude   — Claude Code  (.claude/claude_code_config.json)
#   kilo     — Kilo Code    (.mcp.json, shared with Claude Code)
#   copilot  — GitHub Copilot (.vscode/mcp.json)
#   cline    — Cline        (.claude/commands/dockg.md slash command)
#
# Usage (from a target repo, no clone needed):
#   curl -fsSL https://raw.githubusercontent.com/Flux-Frontiers/doc_kg/main/scripts/install-skill.sh | bash
#
# With provider selection:
#   curl -fsSL .../install-skill.sh | bash -s -- --providers all
#   curl -fsSL .../install-skill.sh | bash -s -- --providers claude,copilot
#   bash scripts/install-skill.sh --providers kilo,cline
#
# Flags:
#   --providers <list>   Comma-separated provider names, or "all" (default: all)
#   --wipe               Force rebuild of graph and vector index
#   --dry-run            Print what would be done without making any changes
#
# What it does:
#   1. Creates skill directories for Claude Code, Kilo Code, and other agents
#      and installs SKILL.md + references/installation.md into each
#   2. Installs Claude Code slash commands (dockg, dockg-rebuild, setup-mcp, changelog-commit,
#      release) to ~/.claude/commands/
#   3. Installs the /dockg slash command into the target repo for Cline
#   4. Installs doc-kg if dockg is not found:
#        a. pip install from latest GitHub release wheel (preferred, no git needed)
#        b. pip install from git+https (fallback, needs git)
#        c. poetry add (fallback for Poetry-managed repos)
#   5. Builds the graph store (skips if already present, unless --wipe)
#   6. Builds the vector index  (skips if already present, unless --wipe)
#   7. Writes provider MCP configs as requested
#   8. Prints a final summary
#
# Author: Eric G. Suchanek, PhD
# Last Revision: 2026-04-24
# License: Elastic 2.0
# =============================================================================

set -eo pipefail

# ── Parse arguments ───────────────────────────────────────────────────────────
PROVIDERS_ARG="all"
WIPE_FLAG=""
DRY_RUN=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --providers)
            PROVIDERS_ARG="${2:-all}"
            shift 2
            ;;
        --providers=*)
            PROVIDERS_ARG="${1#*=}"
            shift
            ;;
        --wipe)
            WIPE_FLAG="1"
            shift
            ;;
        --dry-run)
            DRY_RUN="1"
            shift
            ;;
        *)
            echo "Unknown flag: $1"
            echo "Usage: $0 [--providers all|claude,kilo,copilot,cline] [--wipe] [--dry-run]"
            exit 1
            ;;
    esac
done

# Run a command, or in dry-run mode just print what would be executed.
_exec() {
    if [ -n "$DRY_RUN" ]; then
        echo "  [dry-run] $*"
    else
        "$@"
    fi
}

# Normalise to a set of boolean flags
DO_CLAUDE=0; DO_KILO=0; DO_COPILOT=0; DO_CLINE=0

_enable_provider() {
    case "$1" in
        all)    DO_CLAUDE=1; DO_KILO=1; DO_COPILOT=1; DO_CLINE=1 ;;
        claude) DO_CLAUDE=1 ;;
        kilo)   DO_KILO=1 ;;
        copilot)DO_COPILOT=1 ;;
        cline)  DO_CLINE=1 ;;
        *)
            echo "Unknown provider: $1  (valid: all, claude, kilo, copilot, cline)"
            exit 1
            ;;
    esac
}

IFS=',' read -ra _PLIST <<< "$PROVIDERS_ARG"
for _p in "${_PLIST[@]}"; do
    _enable_provider "$(echo "$_p" | tr -d ' ')"
done

REPO="Flux-Frontiers/doc_kg"
BRANCH="main"
RAW_BASE="https://raw.githubusercontent.com/${REPO}/${BRANCH}"

# Install to Claude Code, Kilo Code, and other agent skill directories
SKILL_DIRS=(
    "${HOME}/.claude/skills/dockg"
    "${HOME}/.kilocode/skills/dockg"
    "${HOME}/.agents/skills/dockg"
)

# Global Claude Code command files to install to ~/.claude/commands/
CLAUDE_COMMAND_FILES=(
    "dockg.md"
    "dockg-rebuild.md"
    "setup-mcp.md"
    "changelog-commit.md"
    "release.md"
)

# ── Detect if we're running from inside the repo ─────────────────────────────
# BASH_SOURCE[0] is unbound when piped via curl | bash.
# Use ${BASH_SOURCE:-} (no array index) which is safe even when unset.
_BASH_SOURCE="${BASH_SOURCE:-}"
if [ -n "$_BASH_SOURCE" ] && [ "$_BASH_SOURCE" != "bash" ]; then
    SCRIPT_DIR="$(cd "$(dirname "$_BASH_SOURCE")" && pwd)"
    REPO_ROOT="$(dirname "$SCRIPT_DIR")"
else
    # Running via curl | bash — no local clone available
    SCRIPT_DIR=""
    REPO_ROOT=""
fi
LOCAL_SKILL="${REPO_ROOT:+${REPO_ROOT}/.claude/skills/dockg/SKILL.md}"

# The target repo is where the user ran the script from (CWD).
TARGET_REPO="${PWD}"
GRAPH_DB="${TARGET_REPO}/.dockg/graph.sqlite"
LANCEDB_DIR="${TARGET_REPO}/.dockg/lancedb"

echo "╔══════════════════════════════════════════════════╗"
echo "║     DocKG Integration Installer (doc_kg)         ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""
[ -n "$DRY_RUN" ] && echo "  *** DRY RUN — no changes will be made ***"
echo "  Target repo: ${TARGET_REPO}"
_PNAMES=""
[ "$DO_CLAUDE"  = "1" ] && _PNAMES="${_PNAMES} claude"
[ "$DO_KILO"    = "1" ] && _PNAMES="${_PNAMES} kilo"
[ "$DO_COPILOT" = "1" ] && _PNAMES="${_PNAMES} copilot"
[ "$DO_CLINE"   = "1" ] && _PNAMES="${_PNAMES} cline"
echo "  Providers:   ${_PNAMES# }"
echo ""

# ── Step 1: Install skill files to agent directories ─────────────────────────
echo "── Step 1: Installing skill files ──────────────────"
echo ""

for SKILL_DIR in "${SKILL_DIRS[@]}"; do
    REFS_DIR="${SKILL_DIR}/references"
    _exec mkdir -p "$SKILL_DIR"
    _exec mkdir -p "$REFS_DIR"

    if [ -f "$LOCAL_SKILL" ]; then
        if [ "${FIRST_RUN:-1}" = "1" ]; then
            echo "→ Local repo detected at: $REPO_ROOT"
            echo "  Copying skill files from local clone..."
            FIRST_RUN=0
        fi
        _exec cp "${REPO_ROOT}/.claude/skills/dockg/SKILL.md" "${SKILL_DIR}/SKILL.md"
        _exec cp "${REPO_ROOT}/.claude/skills/dockg/references/installation.md" "${REFS_DIR}/installation.md"
    else
        if [ "${FIRST_RUN:-1}" = "1" ]; then
            echo "→ No local clone detected. Downloading from GitHub..."
            FIRST_RUN=0
        fi
        if [ -n "$DRY_RUN" ]; then
            echo "  [dry-run] would download ${RAW_BASE}/.claude/skills/dockg/SKILL.md → ${SKILL_DIR}/SKILL.md"
            echo "  [dry-run] would download ${RAW_BASE}/.claude/skills/dockg/references/installation.md → ${REFS_DIR}/installation.md"
        elif command -v curl &>/dev/null; then
            curl -fsSL "${RAW_BASE}/.claude/skills/dockg/SKILL.md" -o "${SKILL_DIR}/SKILL.md"
            curl -fsSL "${RAW_BASE}/.claude/skills/dockg/references/installation.md" -o "${REFS_DIR}/installation.md"
        elif command -v wget &>/dev/null; then
            wget -q "${RAW_BASE}/.claude/skills/dockg/SKILL.md" -O "${SKILL_DIR}/SKILL.md"
            wget -q "${RAW_BASE}/.claude/skills/dockg/references/installation.md" -O "${REFS_DIR}/installation.md"
        else
            echo "ERROR: Neither curl nor wget found. Install one and retry."
            exit 1
        fi
    fi

    # Verify (skip in dry-run — files may not exist yet)
    if [ -z "$DRY_RUN" ]; then
        if [ ! -f "${SKILL_DIR}/SKILL.md" ] || [ ! -f "${REFS_DIR}/installation.md" ]; then
            echo "ERROR: Installation failed for ${SKILL_DIR}"
            exit 1
        fi
    fi

    echo "  ✓ ${SKILL_DIR}/SKILL.md"
    echo "  ✓ ${REFS_DIR}/installation.md"
done

# ── Step 2: Install Claude Code commands to ~/.claude/commands/ ───────────────
echo ""
echo "── Step 2: Installing Claude Code commands ──────────"
echo ""

CLAUDE_CMD_DIR="${HOME}/.claude/commands"
_exec mkdir -p "$CLAUDE_CMD_DIR"

for _CMD_FILE in "${CLAUDE_COMMAND_FILES[@]}"; do
    _DST="${CLAUDE_CMD_DIR}/${_CMD_FILE}"
    _LOCAL_CMD="${REPO_ROOT:+${REPO_ROOT}/.claude/commands/${_CMD_FILE}}"

    if [ -n "$_LOCAL_CMD" ] && [ -f "$_LOCAL_CMD" ]; then
        _exec cp "$_LOCAL_CMD" "$_DST"
        echo "  ✓ Copied from local repo → ${_DST}"
    else
        if [ -n "$DRY_RUN" ]; then
            echo "  [dry-run] would download ${RAW_BASE}/.claude/commands/${_CMD_FILE} → ${_DST}"
        elif command -v curl &>/dev/null; then
            curl -fsSL "${RAW_BASE}/.claude/commands/${_CMD_FILE}" -o "$_DST"
            echo "  ✓ Downloaded → ${_DST}"
        elif command -v wget &>/dev/null; then
            wget -q "${RAW_BASE}/.claude/commands/${_CMD_FILE}" -O "$_DST"
            echo "  ✓ Downloaded → ${_DST}"
        else
            echo "  ⚠ Neither curl nor wget found — skipping ${_CMD_FILE}"
        fi
    fi
done

# ── Step 3: Install Cline slash command into the target repo ──────────────────
echo ""
echo "── Step 3: Installing Cline slash command ───────────"
echo ""

if [ "$DO_CLINE" = "1" ]; then
    CLINE_CMD_DIR="${TARGET_REPO}/.claude/commands"
    CLINE_CMD_FILE="${CLINE_CMD_DIR}/dockg.md"
    _LOCAL_CMD="${REPO_ROOT:+${REPO_ROOT}/.claude/commands/dockg.md}"

    _exec mkdir -p "$CLINE_CMD_DIR"

    if [ -f "$CLINE_CMD_FILE" ]; then
        echo "  ✓ ${CLINE_CMD_FILE} already exists — skipping"
    elif [ -n "$_LOCAL_CMD" ] && [ -f "$_LOCAL_CMD" ]; then
        _exec cp "$_LOCAL_CMD" "$CLINE_CMD_FILE"
        echo "  ✓ Copied from local repo → ${CLINE_CMD_FILE}"
    else
        # Download from GitHub
        if [ -n "$DRY_RUN" ]; then
            echo "  [dry-run] would download ${RAW_BASE}/.claude/commands/dockg.md → ${CLINE_CMD_FILE}"
        elif command -v curl &>/dev/null; then
            curl -fsSL "${RAW_BASE}/.claude/commands/dockg.md" -o "$CLINE_CMD_FILE"
            echo "  ✓ Downloaded → ${CLINE_CMD_FILE}"
        elif command -v wget &>/dev/null; then
            wget -q "${RAW_BASE}/.claude/commands/dockg.md" -O "$CLINE_CMD_FILE"
            echo "  ✓ Downloaded → ${CLINE_CMD_FILE}"
        else
            echo "  ⚠ Neither curl nor wget found — skipping Cline command install"
        fi
    fi
else
    echo "  – Skipped (cline not selected)"
fi

# ── Step 4: Install doc-kg if not already present ────────────────────────────
echo ""
echo "── Step 4: Checking doc-kg installation ─────────────"
echo ""

# Resolve the latest GitHub release wheel URL (requires curl or wget + python3).
# Returns empty string if no release exists yet.
_latest_wheel_url() {
    local _api="https://api.github.com/repos/${REPO}/releases/latest"
    local _json=""
    if command -v curl &>/dev/null; then
        _json="$(curl -fsSL "$_api" 2>/dev/null || true)"
    elif command -v wget &>/dev/null; then
        _json="$(wget -qO- "$_api" 2>/dev/null || true)"
    fi
    [ -z "$_json" ] && return
    python3 - <<PYEOF
import json, sys
try:
    data = json.loads('''$_json''')
    assets = data.get("assets", [])
    whl = next((a["browser_download_url"] for a in assets if a["name"].endswith(".whl")), None)
    if whl:
        print(whl)
except Exception:
    pass
PYEOF
}

DOCKG_BIN=""

# Probe for an existing installation in order of priority:
#   1. Local .venv in the target repo (Poetry project that added doc-kg)
#   2. Local .venv in the doc_kg source repo (running the script from the repo itself)
#   3. Importable in the active Python environment
#   4. On $PATH
if [ -x "${TARGET_REPO}/.venv/bin/dockg" ]; then
    DOCKG_BIN="${TARGET_REPO}/.venv/bin/dockg"
    echo "  ✓ Found dockg in local venv: ${DOCKG_BIN}"
elif [ -n "${REPO_ROOT}" ] && [ -x "${REPO_ROOT}/.venv/bin/dockg" ]; then
    DOCKG_BIN="${REPO_ROOT}/.venv/bin/dockg"
    echo "  ✓ Found dockg in source venv: ${DOCKG_BIN}"
elif python3 -c "import doc_kg" &>/dev/null 2>&1; then
    # Importable — resolve the binary from the same interpreter's Scripts/bin
    DOCKG_BIN="$(python3 -c "import sysconfig; print(sysconfig.get_path('scripts'))")/dockg"
    [ -x "$DOCKG_BIN" ] || DOCKG_BIN="dockg"   # fallback to PATH entry
    echo "  ✓ Found doc_kg in Python environment — dockg: ${DOCKG_BIN}"
elif command -v dockg &>/dev/null; then
    DOCKG_BIN="$(command -v dockg)"
    echo "  ✓ Found dockg on PATH: ${DOCKG_BIN}"
fi

if [ -z "$DOCKG_BIN" ]; then
    if [ -n "$DRY_RUN" ]; then
        echo "  [dry-run] would install doc-kg from GitHub (wheel or git source)"
        DOCKG_BIN="dockg"
    else
        # ── Preferred: latest GitHub release wheel (no git needed) ────────────
        WHEEL_URL="$(_latest_wheel_url || true)"
        if [ -n "$WHEEL_URL" ]; then
            echo "  → Installing doc-kg from GitHub release wheel..."
            pip install --quiet "doc-kg @ ${WHEEL_URL}"
        else
            # ── Fallback: pip from git source ─────────────────────────────────
            echo "  → Installing doc-kg from GitHub source..."
            pip install --quiet "doc-kg @ git+https://github.com/${REPO}.git"
        fi
        # Re-probe after install
        DOCKG_BIN="$(command -v dockg 2>/dev/null || true)"
        if [ -n "$DOCKG_BIN" ]; then
            echo "  ✓ Installed doc-kg — dockg at: ${DOCKG_BIN}"
        else
            echo "  ✗ Installation failed. Install manually:"
            echo "      pip install 'doc-kg @ git+https://github.com/${REPO}.git'"
            exit 1
        fi
    fi
fi

# ── Step 4b: Write Cline MCP settings (cline_mcp_settings.json) ─────────────
# Must run after DOCKG_BIN is resolved above.
echo ""
echo "── Step 4b: Configuring Cline MCP settings ──────────"
echo ""

if [ "$DO_CLINE" = "1" ]; then
    # Cline global MCP settings — macOS/Linux paths
    CLINE_SETTINGS=""
    if [ -f "${HOME}/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json" ]; then
        CLINE_SETTINGS="${HOME}/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json"
    elif [ -f "${HOME}/.config/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json" ]; then
        CLINE_SETTINGS="${HOME}/.config/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json"
    fi

    if [ -z "$CLINE_SETTINGS" ]; then
        echo "  ⚠ cline_mcp_settings.json not found — is Cline installed?"
        echo "    Expected: ~/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json"
    elif [ -n "$DRY_RUN" ]; then
        REPO_NAME="$(basename "${TARGET_REPO}")"
        echo "  [dry-run] would upsert dockg-${REPO_NAME} in ${CLINE_SETTINGS}"
    else
        REPO_NAME="$(basename "${TARGET_REPO}")"
        python3 - "$CLINE_SETTINGS" "$TARGET_REPO" "$REPO_NAME" "$DOCKG_BIN" <<'PYEOF'
import json, sys
cline_settings = sys.argv[1]
target_repo    = sys.argv[2]
repo_name      = sys.argv[3]
dockg_bin      = sys.argv[4]
server_key     = f"dockg-{repo_name}"

with open(cline_settings, "r") as f:
    data = json.load(f)
if "mcpServers" not in data:
    data["mcpServers"] = {}

data["mcpServers"][server_key] = {
    "command": dockg_bin,
    "args": ["mcp", "--repo", target_repo]
}

with open(cline_settings, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
print(f"  ✓ Upserted {server_key} in {cline_settings}")
PYEOF
    fi
else
    echo "  – Skipped (cline not selected)"
fi

# ── Step 5: Build the graph store ─────────────────────────────────────────────
echo ""
echo "── Step 5: Building graph store ─────────────────────"
echo ""

if [ -f "$GRAPH_DB" ] && [ -z "$WIPE_FLAG" ]; then
    echo "  ✓ Graph store already exists: ${GRAPH_DB} — skipping build"
    echo "    (Run with --wipe to force rebuild)"
else
    if [ -n "$DRY_RUN" ]; then
        echo "  [dry-run] would run: dockg build-graph --repo ${TARGET_REPO}${WIPE_FLAG:+ --wipe}"
    else
        _exec mkdir -p "$(dirname "$GRAPH_DB")"
        echo "  → Building graph store at: ${GRAPH_DB}"
        _WIPE_ARG=${WIPE_FLAG:+--wipe}
        (cd "${TARGET_REPO}" && "${DOCKG_BIN}" build-graph --repo "${TARGET_REPO}" ${_WIPE_ARG})
        if [ -f "$GRAPH_DB" ]; then
            echo "  ✓ Built: ${GRAPH_DB}"
        else
            echo "  ✗ Build failed — ${GRAPH_DB} not created"
            exit 1
        fi
    fi
fi

# ── Step 6: Build the vector index ───────────────────────────────────────────
echo ""
echo "── Step 6: Building vector index ───────────────────"
echo ""

if [ -d "$LANCEDB_DIR" ] && [ "$(ls -A "$LANCEDB_DIR" 2>/dev/null)" ] && [ -z "$WIPE_FLAG" ]; then
    echo "  ✓ Vector index already exists: ${LANCEDB_DIR} — skipping build"
    echo "    (Run with --wipe to force rebuild)"
else
    if [ -n "$DRY_RUN" ]; then
        echo "  [dry-run] would run: dockg build-index --repo ${TARGET_REPO}${WIPE_FLAG:+ --wipe}"
    else
        echo "  → Building vector index at: ${LANCEDB_DIR}"
        _WIPE_ARG=${WIPE_FLAG:+--wipe}
        (cd "${TARGET_REPO}" && "${DOCKG_BIN}" build-index --repo "${TARGET_REPO}" ${_WIPE_ARG})
        if [ -d "$LANCEDB_DIR" ] && [ "$(ls -A "$LANCEDB_DIR" 2>/dev/null)" ]; then
            echo "  ✓ Built: ${LANCEDB_DIR}"
        else
            echo "  ✗ Build failed — ${LANCEDB_DIR} not populated"
            exit 1
        fi
    fi
fi

# ── Step 7: Write .mcp.json (Claude Code + Kilo Code) ────────────────────────
echo ""
echo "── Step 7: Configuring .mcp.json (Claude Code + Kilo Code) ──"
echo ""

MCP_JSON="${TARGET_REPO}/.mcp.json"

if [ "$DO_KILO" = "0" ] && [ "$DO_CLAUDE" = "0" ]; then
    echo "  – Skipped (neither claude nor kilo selected)"
elif [ -n "$DRY_RUN" ]; then
    echo "  [dry-run] would upsert dockg entry in ${MCP_JSON}"
elif [ ! -f "$MCP_JSON" ]; then
    cat > "$MCP_JSON" <<EOF
{
  "mcpServers": {
    "dockg": {
      "command": "${DOCKG_BIN}",
      "args": [
        "mcp",
        "--repo", "${TARGET_REPO}"
      ]
    }
  }
}
EOF
    echo "  ✓ Created ${MCP_JSON}"
else
    python3 - "$MCP_JSON" "$TARGET_REPO" "$DOCKG_BIN" <<'PYEOF'
import json, sys
mcp_json   = sys.argv[1]
target_repo = sys.argv[2]
dockg_bin  = sys.argv[3]
with open(mcp_json, "r") as f:
    data = json.load(f)
if "mcpServers" not in data:
    data["mcpServers"] = {}
data["mcpServers"]["dockg"] = {
    "command": dockg_bin,
    "args": ["mcp", "--repo", target_repo]
}
with open(mcp_json, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
PYEOF
    echo "  ✓ Updated dockg entry in ${MCP_JSON}"
fi

# ── Step 8: Write .vscode/mcp.json (GitHub Copilot) ──────────────────────────
echo ""
echo "── Step 8: Configuring .vscode/mcp.json (GitHub Copilot) ──"
echo ""

VSCODE_DIR="${TARGET_REPO}/.vscode"
VSCODE_MCP="${VSCODE_DIR}/mcp.json"

if [ "$DO_COPILOT" = "0" ]; then
    echo "  – Skipped (copilot not selected)"
elif [ -n "$DRY_RUN" ]; then
    if [ ! -f "$VSCODE_MCP" ]; then
        echo "  [dry-run] would create ${VSCODE_MCP}"
    else
        echo "  [dry-run] would upsert dockg entry in existing ${VSCODE_MCP}"
    fi
else
    _exec mkdir -p "$VSCODE_DIR"

    if [ ! -f "$VSCODE_MCP" ]; then
        cat > "$VSCODE_MCP" <<EOF
{
  "servers": {
    "dockg": {
      "type": "stdio",
      "command": "${DOCKG_BIN}",
      "args": [
        "mcp",
        "--repo", "${TARGET_REPO}"
      ]
    }
  }
}
EOF
        echo "  ✓ Created ${VSCODE_MCP}"
    else
        python3 - "$VSCODE_MCP" "$TARGET_REPO" "$DOCKG_BIN" <<'PYEOF'
import json, sys
vscode_mcp  = sys.argv[1]
target_repo = sys.argv[2]
dockg_bin   = sys.argv[3]
with open(vscode_mcp, "r") as f:
    data = json.load(f)
if "servers" not in data:
    data["servers"] = {}
data["servers"]["dockg"] = {
    "type": "stdio",
    "command": dockg_bin,
    "args": ["mcp", "--repo", target_repo]
}
with open(vscode_mcp, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
PYEOF
        echo "  ✓ Updated dockg entry in ${VSCODE_MCP}"
    fi
fi  # DO_COPILOT

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
if [ -n "$DRY_RUN" ]; then
echo "╔══════════════════════════════════════════════════╗"
echo "║   DocKG dry-run complete — no changes made.      ║"
echo "╚══════════════════════════════════════════════════╝"
else
echo "╔══════════════════════════════════════════════════╗"
echo "║   DocKG installed and configured successfully!   ║"
echo "╚══════════════════════════════════════════════════╝"
fi
echo ""
echo "  Repo:     ${TARGET_REPO}"
echo "  Graph DB: ${GRAPH_DB}"
echo "  LanceDB:  ${LANCEDB_DIR}"
echo ""
echo "  Claude commands installed:"
echo "    ✓ ~/.claude/commands/dockg.md"
echo "    ✓ ~/.claude/commands/dockg-rebuild.md"
echo "    ✓ ~/.claude/commands/setup-mcp.md"
echo "    ✓ ~/.claude/commands/changelog-commit.md"
echo "    ✓ ~/.claude/commands/release.md"
echo ""
echo "  Providers configured:"
( [ "$DO_CLAUDE" = "1" ] || [ "$DO_KILO" = "1" ] ) && echo "    ✓ Claude Code + Kilo Code  (.mcp.json)"
[ "$DO_COPILOT" = "1" ] && echo "    ✓ GitHub Copilot (.vscode/mcp.json)"
[ "$DO_CLINE"   = "1" ] && echo "    ✓ Cline          (.claude/commands/dockg.md + cline_mcp_settings.json)"
echo ""
echo "  ⚠ One manual step required:"
echo "    Reload VS Code to activate the MCP servers:"
echo "    Cmd+Shift+P → 'Developer: Reload Window'"
echo ""
[ "$DO_COPILOT" = "1" ] && echo "  GitHub Copilot: VS Code will prompt you to Trust the dockg server on first use."
echo ""
echo "  Full docs: https://github.com/Flux-Frontiers/doc_kg/blob/main/docs/MCP.md"
