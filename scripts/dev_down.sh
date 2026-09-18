#!/usr/bin/env bash
# Matikan backend dev milik anggota — PRD §6.4, §16 (tugas D-03). Pemilik: Nico (D).
# Usage: bash scripts/dev_down.sh <nama>
# Hanya mematikan PID dari file PID milik sendiri (R7); tanpa pkill/killall.
set -euo pipefail

name="${1:-}"
case "$name" in
  marshal | david | dafa | nico) ;;
  *) echo "Usage: bash scripts/dev_down.sh <marshal|david|dafa|nico>" >&2; exit 2 ;;
esac
if [ "${FP_MEMBER:-}" != "$name" ]; then
  echo "dev_down.sh: ditolak — FP_MEMBER='${FP_MEMBER:-}' bukan '$name'." >&2
  exit 1
fi

FP_HOME="${FP_HOME:-$HOME/work/formulapilot}"
pidf="${FP_RUNTIME_DIR:-$FP_HOME/var/$name}/run/app.pid"
if [ ! -s "$pidf" ]; then
  echo "dev_down.sh: $name tidak berjalan (tidak ada $pidf)."
  exit 0
fi
pid="$(tr -dc '0-9' < "$pidf")"
if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
  echo "dev_down.sh: PID basi ($pid), file PID dihapus."
  rm -f "$pidf"
  exit 0
fi
if ! tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -q uvicorn; then
  echo "dev_down.sh: PID $pid bukan proses uvicorn (PID dipakai ulang?). Tidak di-kill; file PID dihapus." >&2
  rm -f "$pidf"
  exit 1
fi

# dev_up.sh menyalakan dengan setsid → PID = process group (termasuk worker --reload).
kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
for _ in 1 2 3 4 5; do
  kill -0 "$pid" 2>/dev/null || break
  sleep 1
done
if kill -0 "$pid" 2>/dev/null; then
  echo "dev_down.sh: belum berhenti setelah 5 detik, SIGKILL pid $pid."
  kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
fi
rm -f "$pidf"
echo "dev_down.sh: $name dimatikan (pid $pid)."
