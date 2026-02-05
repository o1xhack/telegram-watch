#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

. .venv/bin/activate

INSTALL_MARKER=".venv/.tgwatch_installed"
if [ ! -f "$INSTALL_MARKER" ]; then
  python -m pip install -e .
  touch "$INSTALL_MARKER"
fi

if [ ! -f "config.toml" ]; then
  cp config.example.toml config.toml
fi

python -m tgwatch gui --config config.toml
