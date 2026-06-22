#!/usr/bin/env bash
# codeviz installer — sets up the CLI, the JS/TS tracer deps, and the VS Code
# extension on this machine. Safe to re-run.
#
#   git clone https://github.com/manzoid/codeviz && cd codeviz && ./install.sh
#
# Prerequisites: python3 (required). node 18+ (for JavaScript/TypeScript) and
# Docker (for C/C++/Java/asm) are optional — codeviz works without them, those
# languages just won't be available. See `codeviz doctor` afterwards.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
say() { printf '\033[1m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33m  ! %s\033[0m\n' "$*"; }

# --- 1. Python CLI -----------------------------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
  echo "error: python3 is required but not found." >&2
  exit 1
fi
say "Installing the codeviz command (editable)…"
if command -v pipx >/dev/null 2>&1; then
  pipx install --force -e . >/dev/null
  PATH="$HOME/.local/bin:$PATH"
else
  python3 -m pip install -e . >/dev/null 2>&1 \
    || python3 -m pip install --user -e . >/dev/null 2>&1 \
    || { warn "pip install failed; try: pipx install -e .  (brew install pipx)"; }
  # pyenv needs a rehash to expose the new console script as a shim.
  command -v pyenv >/dev/null 2>&1 && pyenv rehash >/dev/null 2>&1 || true
fi
if command -v codeviz >/dev/null 2>&1; then
  say "codeviz command: $(command -v codeviz)"
else
  warn "codeviz not on PATH yet — you may need to restart your shell, or add your"
  warn "Python user-bin (e.g. ~/.local/bin or pyenv shims) to PATH."
fi

# --- 2. JS/TS tracer deps (optional) ----------------------------------------
if command -v node >/dev/null 2>&1; then
  say "Installing JS/TS tracer deps (npm) in tracers/js…"
  ( cd tracers/js && npm install --silent --no-audit --no-fund ) \
    && say "JS/TS ready." || warn "npm install failed — TypeScript may be unavailable."
else
  warn "node not found — JavaScript/TypeScript disabled (install Node 18+ to enable)."
fi

# --- 3. Docker note (optional) ----------------------------------------------
if command -v docker >/dev/null 2>&1; then
  say "Docker found — C/C++/Java/asm images build on first use (or: codeviz setup c|cpp|java|asm)."
else
  warn "docker not found — C/C++/Java/asm disabled (install Docker Desktop to enable)."
fi

# --- 4. VS Code extension (optional) ----------------------------------------
if command -v code >/dev/null 2>&1; then
  say "Building + installing the VS Code extension…"
  ( cd editor/vscode
    npx --yes @vscode/vsce package --allow-missing-repository --skip-license >/dev/null 2>&1
    VSIX="$(ls -t codeviz-*.vsix 2>/dev/null | head -1)"
    [ -n "$VSIX" ] && code --install-extension "$VSIX" --force >/dev/null 2>&1 \
      && echo "installed $VSIX" || warn "extension packaging/install failed"
  ) && say "VS Code extension installed (reload VS Code: Developer: Reload Window)."
else
  warn "VS Code 'code' CLI not found — skipping extension. Install it from VS Code:"
  warn "  Cmd+Shift+P → 'Shell Command: Install code command in PATH', then re-run."
fi

# --- 5. Report ---------------------------------------------------------------
echo
say "Environment check:"
if command -v codeviz >/dev/null 2>&1; then codeviz doctor || true; else python3 codeviz.py doctor || true; fi
echo
say "Done. Open a file and press Cmd+Alt+V in VS Code, or run:  codeviz <file> --open"
