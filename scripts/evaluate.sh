#!/usr/bin/env bash
# Evaluasi & figur — PRD §10, §16 (tugas A-07..A-11). Pemilik: Marshal (A).
# Wajib lewat antrean:
#   bash scripts/heavy.sh bash scripts/evaluate.sh          # --all (khusus Marshal/pengganti, R26)
#   bash scripts/heavy.sh bash scripts/evaluate.sh quick    # --quick
set -euo pipefail
FP_HOME="${FP_HOME:-$HOME/work/formulapilot}"
cd "$FP_HOME"
mode="--all"
if [ "${1:-}" = "quick" ]; then mode="--quick"; shift; fi
python -m fp.evaluate "$mode" --out artifacts/evaluation.json --figdir artifacts/figures "$@"
