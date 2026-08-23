#!/usr/bin/env bash
# ============================================================================
# Cloud Agent install script for hermes-agent
# ============================================================================
# Idempotent, non-interactive bootstrap for a Cursor Cloud Agent dev
# environment. Referenced by the dashboard-managed environment's `install`
# command. Safe to run repeatedly and against a cached/partially-prepared
# checkout.
#
# What it sets up:
#   1. uv (installed to ~/.local/bin if missing)
#   2. Python .venv with core + dev dependencies (pytest/xdist/split/ruff/ty)
#      so `scripts/run_tests.sh` works out of the box
#   3. Node dependencies for the root, ui-tui, and web workspaces so the
#      TUI/dashboard dev commands work
#
# Deliberately NOT done here (per-boot / on-demand concerns):
#   * Building web/ui-tui dist bundles (run `npm run build` when needed)
#   * Playwright browser download (heavy; lazy-installed on first use)
#   * The private `dfy` extra (needs GH_TOKEN; not required for dev/tests)
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# Prevent uv from discovering config files from an unexpected home dir.
export UV_NO_CONFIG=1

# ── uv ──────────────────────────────────────────────────────────────────────
if ! command -v uv >/dev/null 2>&1; then
  echo "→ installing uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"
uv --version

# ── Python venv + dependencies ──────────────────────────────────────────────
# --frozen: use uv.lock exactly (CI enforces lock sync); no lockfile mutation.
# --extra dev: pytest, pytest-xdist, pytest-split, ruff, ty, mcp, debugpy.
echo "→ syncing Python dependencies (.venv, dev extra)"
uv sync --frozen --extra dev

# Verify the venv is usable.
.venv/bin/python -c "import pytest, xdist, openai, hermes_bootstrap; print('python env OK')"

# ── Node dependencies (TUI + dashboard) ─────────────────────────────────────
# install-links=false makes npm symlink the `file:` @hermes/ink workspace dep
# instead of copying it (matches how package-lock.json was generated). See the
# Dockerfile comment for the full rationale.
if command -v npm >/dev/null 2>&1; then
  export npm_config_install_links=false
  echo "→ installing Node dependencies (root)"
  npm ci --prefer-offline --no-audit
  echo "→ installing Node dependencies (ui-tui)"
  (cd ui-tui && npm ci --prefer-offline --no-audit)
  echo "→ installing Node dependencies (web)"
  (cd web && npm ci --prefer-offline --no-audit)
else
  echo "! npm not found on PATH — skipping Node dependency install"
fi

echo "✓ cloud-agent install complete"
