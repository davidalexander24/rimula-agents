#!/usr/bin/env bash
# Setup environment bersama — PRD §7, §16 (tugas D-02). Pemilik: Nico (D). Hanya Nico yang menjalankan (R17).
# Idempoten: aman dijalankan ulang (misalnya setelah requirements.txt berubah).
# Usage: bash scripts/setup_env.sh
#   SETUP_AGENTS="claude codex"   CLI AI agent yang dipasang ke ~/work/node-env (kosongkan untuk melewati)
# Tidak menyentuh frontend/ (milik Dafa).
set -euo pipefail

WORK="$HOME/work"
FP_HOME="${FP_HOME:-$WORK/formulapilot}"
NODE_ENV="$WORK/node-env"
VENV="$WORK/venvs/fp"
PY_BASE="${PY_BASE:-/opt/conda/bin/python}"
SETUP_AGENTS="${SETUP_AGENTS-claude codex}"

export PIP_CACHE_DIR="$WORK/pip-cache"
export HF_HOME="$WORK/hf"
export npm_config_cache="$WORK/npm-cache"
export CONDA_PKGS_DIRS="$WORK/conda-pkgs"
export PIP_DISABLE_PIP_VERSION_CHECK=1

log() { echo "[setup_env $(date +%H:%M:%S)] $*"; }

# 1. Node.js 22 (conda-forge) di ~/work/node-env
if [ ! -x "$NODE_ENV/bin/node" ]; then
  log "membuat $NODE_ENV (Node.js 22, conda-forge)"
  /opt/conda/bin/mamba create -y -p "$NODE_ENV" -c conda-forge --override-channels "nodejs=22"
fi
export PATH="$NODE_ENV/bin:$PATH"
log "node $(node --version), npm $(npm --version)"

# 2. CLI AI agent tim (PRD §6.9) — dipasang sekali ke node-env agar persisten
agent_pkgs=()
for a in $SETUP_AGENTS; do
  case "$a" in
    claude) agent_pkgs+=("@anthropic-ai/claude-code") ;;
    codex) agent_pkgs+=("@openai/codex") ;;
    *) log "agent tidak dikenal, dilewati: $a" ;;
  esac
done
if [ "${#agent_pkgs[@]}" -gt 0 ]; then
  log "memasang CLI agent: ${agent_pkgs[*]}"
  npm install -g --prefix "$NODE_ENV" "${agent_pkgs[@]}"
fi

# 3. Python venv ~/work/venvs/fp
if [ ! -x "$VENV/bin/python" ]; then
  log "membuat venv $VENV dengan $PY_BASE ($("$PY_BASE" --version))"
  mkdir -p "$(dirname "$VENV")"
  "$PY_BASE" -m venv "$VENV"
fi
log "venv python: $("$VENV/bin/python" --version)"
"$VENV/bin/python" -m pip install --upgrade pip
log "install requirements.txt"
"$VENV/bin/python" -m pip install -r "$FP_HOME/requirements.txt"

# 4. requirements.lock (atomik, R19)
lock="$FP_HOME/requirements.lock"
"$VENV/bin/python" -m pip freeze --exclude-editable > "$lock.tmp.$$"
mv -f "$lock.tmp.$$" "$lock"
log "requirements.lock: $(wc -l < "$lock") paket"

log "SELESAI"
