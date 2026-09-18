#!/usr/bin/env bash
# Latih model dasar Designer — PRD §9.6, §16 (tugas A-06). Pemilik: Marshal (A).
# Wajib lewat antrean: bash scripts/heavy.sh bash scripts/train.sh
set -euo pipefail
FP_HOME="${FP_HOME:-$HOME/work/formulapilot}"
cd "$FP_HOME"
python -m fp.designer --train --scope global --version gp-global-v1
python -m fp.designer --bench
