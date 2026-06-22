#!/usr/bin/env bash
# codeviz installer (from a clone). Installs the `codeviz` command and the VS
# Code extension. Safe to re-run. Clone-free alternative (no clone to keep):
#
#   uv tool install git+https://github.com/manzoid/codeviz
#   codeviz install-extension
#
# Prerequisites: Python 3.9+ (required). Node 18+ (JavaScript/TypeScript) and
# Docker (C/C++/Java/asm) are optional — those languages activate when present.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
say() { printf '\033[1m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33m  ! %s\033[0m\n' "$*"; }

# --- 1. Install the codeviz command (non-editable; clone can be removed after) ---
say "Installing the codeviz command…"
if command -v uv >/dev/null 2>&1; then
  uv tool install --force . >/dev/null
elif command -v pipx >/dev/null 2>&1; then
  pipx install --force . >/dev/null
else
  python3 -m pip install --user . >/dev/null 2>&1 || python3 -m pip install . >/dev/null 2>&1 \
    || warn "install failed; try installing uv (https://docs.astral.sh/uv/) then re-run."
  command -v pyenv >/dev/null 2>&1 && pyenv rehash >/dev/null 2>&1 || true
fi
if command -v codeviz >/dev/null 2>&1; then
  say "codeviz: $(command -v codeviz)"
else
  warn "codeviz not on PATH yet — restart your shell (or run: uv tool update-shell)."
fi

# --- 2. VS Code extension (optional) ---
if command -v code >/dev/null 2>&1 && command -v codeviz >/dev/null 2>&1; then
  say "Installing the VS Code extension…"
  codeviz install-extension || warn "extension install failed"
else
  warn "skipping VS Code extension (need the 'code' CLI + codeviz on PATH)."
fi

# --- 3. Report ---
echo
if command -v codeviz >/dev/null 2>&1; then codeviz doctor || true; fi
echo
say "Done. Open a file and press Cmd+Alt+V in VS Code, or run:  codeviz <file> --open"
say "(Node enables JS/TS; Docker enables C/C++/Java/asm — see 'codeviz doctor'.)"
