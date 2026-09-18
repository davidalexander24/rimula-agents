#!/usr/bin/env bash
# Unduh data mentah — PRD §8.3, §8.4, §16 (tugas D-05). Pemilik: Nico (D).
# Wajib lewat antrean: bash scripts/heavy.sh bash scripts/fetch_data.sh [--force]
#   Open Beauty Facts -> data/market/obf_raw.csv.gz            (fp.market, milik Nico)
#   Dataset liposom   -> data/validation/liposome/*.zip         (fp.validation_liposome, milik Marshal)
#   SHA-256           -> data/market/SHA256SUMS, data/validation/liposome/SHA256SUMS
set -euo pipefail

FP_HOME="${FP_HOME:-$HOME/work/formulapilot}"
cd "$FP_HOME"
force=()
if [ "${1:-}" = "--force" ]; then force=(--force); fi

log() { echo "[fetch_data $(date +%H:%M:%S)] $*"; }
rc=0

write_sums() { # <folder> <pola file...>
  local dir="$1"; shift
  local files=()
  local pattern f
  for pattern in "$@"; do
    for f in "$dir"/$pattern; do [ -f "$f" ] && files+=("$(basename "$f")"); done
  done
  if [ "${#files[@]}" -eq 0 ]; then
    log "tidak ada file untuk SHA256SUMS di $dir"
    return 0
  fi
  (cd "$dir" && sha256sum "${files[@]}" > ".SHA256SUMS.tmp.$$" && mv -f ".SHA256SUMS.tmp.$$" SHA256SUMS)
  log "SHA256SUMS $dir:"
  sed 's/^/    /' "$dir/SHA256SUMS"
}

log "Open Beauty Facts"
if python -m fp.market --download "${force[@]}"; then
  write_sums data/market "obf_raw.csv.gz"
else
  log "GAGAL unduh Open Beauty Facts"
  rc=1
fi

log "Dataset liposom (milik Marshal)"
if [ -f fp/validation_liposome.py ]; then
  if python -m fp.validation_liposome --download "${force[@]}"; then
    write_sums data/validation/liposome "*.zip"
  else
    log "GAGAL unduh dataset liposom (fp.validation_liposome --download)"
    rc=1
  fi
else
  log "dilewati: fp/validation_liposome.py belum ada (A-10 Marshal)"
fi

log "selesai (exit $rc)"
exit "$rc"
