#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ -n "${VIRTUAL_ENV:-}" ]; then
  unset VIRTUAL_ENV
fi

GUI_HOST="${TGWATCH_GUI_HOST:-127.0.0.1}"
GUI_PORT="${TGWATCH_GUI_PORT:-8765}"

recover_gui_port() {
  if ! command -v lsof >/dev/null 2>&1; then
    echo "[tgwatch] Warning: lsof not found; skipping port recovery for ${GUI_PORT}."
    return 0
  fi

  local pids=()
  local pid
  local cmd
  while IFS= read -r pid; do
    [ -n "${pid}" ] && pids+=("${pid}")
  done <<EOF
$(lsof -nP -t -iTCP:"${GUI_PORT}" -sTCP:LISTEN 2>/dev/null || true)
EOF
  if [ "${#pids[@]}" -eq 0 ]; then
    return 0
  fi

  echo "[tgwatch] Port ${GUI_PORT} is in use. Attempting recovery..."
  for pid in "${pids[@]}"; do
    [ -z "${pid}" ] && continue
    cmd="$(ps -p "${pid}" -o command= 2>/dev/null || true)"
    echo "[tgwatch] Stopping PID ${pid}: ${cmd:-unknown}"
    kill "${pid}" 2>/dev/null || true
  done

  for _ in {1..20}; do
    if ! lsof -nP -iTCP:"${GUI_PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
      echo "[tgwatch] Port ${GUI_PORT} recovered."
      return 0
    fi
    sleep 0.1
  done

  pids=()
  while IFS= read -r pid; do
    [ -n "${pid}" ] && pids+=("${pid}")
  done <<EOF
$(lsof -nP -t -iTCP:"${GUI_PORT}" -sTCP:LISTEN 2>/dev/null || true)
EOF
  for pid in "${pids[@]}"; do
    [ -z "${pid}" ] && continue
    echo "[tgwatch] Force stopping PID ${pid}..."
    kill -9 "${pid}" 2>/dev/null || true
  done
  sleep 0.2

  if lsof -nP -iTCP:"${GUI_PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "[tgwatch] Error: port ${GUI_PORT} is still in use. Stop it manually and retry."
    lsof -nP -iTCP:"${GUI_PORT}" -sTCP:LISTEN || true
    return 1
  fi

  echo "[tgwatch] Port ${GUI_PORT} recovered."
  return 0
}

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

recover_gui_port
python -m tgwatch gui --config config.toml --host "${GUI_HOST}" --port "${GUI_PORT}"
