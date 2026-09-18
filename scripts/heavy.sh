#!/usr/bin/env bash
# Antrean global proses berat (PRD §6.8). Pemilik: Nico (D).
# Usage: bash scripts/heavy.sh <perintah...>
#   HEAVY_WAIT_MIN=<menit>  batas tunggu kunci (default 30)
set -euo pipefail

if [ $# -eq 0 ]; then
  echo "Usage: bash scripts/heavy.sh <perintah...>" >&2
  exit 2
fi

FP_HOME="${FP_HOME:-$HOME/work/formulapilot}"
LOCK_DIR="$FP_HOME/var/locks"
LOCK="$LOCK_DIR/heavy.lock"
OWNER="$LOCK_DIR/heavy.owner"
WAIT_MIN="${HEAVY_WAIT_MIN:-30}"
mkdir -p "$LOCK_DIR"

deadline=$(( $(date +%s) + WAIT_MIN * 60 ))
last_msg=0
wait_note() {
  local now
  now=$(date +%s)
  if (( now >= deadline )); then
    echo "heavy.sh: menyerah setelah ${WAIT_MIN} menit menunggu kunci." >&2
    exit 75
  fi
  if (( now - last_msg >= 30 )); then
    echo "heavy.sh: menunggu antrean — dipegang: $(cat "$OWNER" 2>/dev/null || echo 'tidak diketahui')" >&2
    last_msg=$now
  fi
  sleep 2
}

if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK"
  until flock -n 9; do wait_note; done
  release() { rm -f "$OWNER"; }
else
  # Cadangan tanpa flock: kunci berbasis pembuatan folder.
  until mkdir "$LOCK.d" 2>/dev/null; do wait_note; done
  release() { rm -f "$OWNER"; rmdir "$LOCK.d" 2>/dev/null || true; }
fi
trap release EXIT
trap 'exit 130' INT TERM

printf '%s · sejak %s · pid %s · %s\n' "${FP_MEMBER:-?}" "$(date '+%H:%M:%S')" "$$" "$*" > "$OWNER.tmp.$$"
mv -f "$OWNER.tmp.$$" "$OWNER"

export OMP_NUM_THREADS=8 OPENBLAS_NUM_THREADS=8 MKL_NUM_THREADS=8 NUMEXPR_NUM_THREADS=8
export LOKY_MAX_CPU_COUNT=8
set +e
nice -n 10 "$@"
rc=$?
set -e
exit "$rc"
