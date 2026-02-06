#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ -n "${VIRTUAL_ENV:-}" ]; then
  unset VIRTUAL_ENV
fi

USE_CONDA=0
if command -v conda >/dev/null 2>&1; then
  if eval "$(conda shell.bash hook 2>/dev/null)"; then
    if conda env list | awk '{print $1}' | grep -qx "tgwatch"; then
      echo "[tgwatch] Using existing Conda environment: tgwatch"
    else
      echo "[tgwatch] Creating Conda environment: tgwatch"
      if conda create -y -n tgwatch python=3.11; then
        echo "[tgwatch] Conda environment created: tgwatch"
      else
        echo "[tgwatch] Conda create failed, falling back to venv"
      fi
    fi
    if conda activate tgwatch >/dev/null 2>&1; then
      USE_CONDA=1
    else
      echo "[tgwatch] Conda activate failed, falling back to venv"
    fi
  fi
fi

install_project() {
  if ! python -m pip install -U pip setuptools wheel; then
    echo "[tgwatch] Warning: failed to upgrade pip/setuptools/wheel; continuing with existing installer."
  fi
  if ! python -m pip install -e .; then
    echo "[tgwatch] Error: project install failed. Check network/proxy/pip index settings and retry."
    exit 1
  fi
}

if [ "$USE_CONDA" -eq 1 ]; then
  if ! python -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
    echo "[tgwatch] Conda environment must use Python 3.11+"
    exit 1
  fi
  INSTALL_MARKER=".conda-tgwatch-installed"
  if [ ! -f "$INSTALL_MARKER" ]; then
    install_project
    touch "$INSTALL_MARKER"
  fi
  echo "[tgwatch] Environment source: conda (tgwatch)"
else
  VENV_PYTHON=""
  if command -v python3.11 >/dev/null 2>&1; then
    VENV_PYTHON="python3.11"
  elif command -v python3 >/dev/null 2>&1; then
    VENV_PYTHON="python3"
  elif command -v python >/dev/null 2>&1; then
    VENV_PYTHON="python"
  else
    echo "[tgwatch] Python not found. Install Python 3.11+."
    exit 1
  fi
  if [ ! -d ".venv" ]; then
    "$VENV_PYTHON" -m venv .venv
  fi

  . .venv/bin/activate
  if ! python -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
    echo "[tgwatch] venv Python must be 3.11+"
    exit 1
  fi

  INSTALL_MARKER=".venv/.tgwatch_installed"
  if [ ! -f "$INSTALL_MARKER" ]; then
    install_project
    touch "$INSTALL_MARKER"
  fi
  echo "[tgwatch] Environment source: venv (.venv)"
fi

if [ ! -f "config.toml" ]; then
  cp config.example.toml config.toml
fi

python -m tgwatch gui --config config.toml
