#!/usr/bin/env bash
# Bangun artefak Scout (pasar + literatur) — PRD §12, §16 (tugas D-06/D-07). Pemilik: Nico (D).
# Wajib lewat antrean: bash scripts/heavy.sh bash scripts/build_scout.sh [argumen tambahan fp.scout]
#   contoh fallback tanpa torch: bash scripts/heavy.sh bash scripts/build_scout.sh --backend tfidf
set -euo pipefail

FP_HOME="${FP_HOME:-$HOME/work/formulapilot}"
cd "$FP_HOME"

echo "[build_scout $(date +%H:%M:%S)] market"
python -m fp.market --build
echo "[build_scout $(date +%H:%M:%S)] scout literatur"
python -m fp.scout --build "$@"
echo "[build_scout $(date +%H:%M:%S)] selesai"
