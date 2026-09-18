#!/usr/bin/env bash
# Status operasional (read-only) — PRD §16 (tugas D-03). Pemilik: Nico (D).
# Usage: bash scripts/status.sh
set -uo pipefail

WORK="$HOME/work"
FP_HOME_DEV="$WORK/formulapilot"
REL="$WORK/release/current"

human() {
  if [ -f "$1" ]; then du -h "$1" | cut -f1; else echo "-"; fi
}

echo "== Instance ($(TZ=Asia/Jakarta date '+%H:%M:%S') WIB)"
printf "  %-8s %-5s %-8s %-15s %-7s %-6s %s\n" INSTANCE PORT PID PROSES HEALTH DB KODE
for inst in demo marshal david dafa nico; do
  case "$inst" in
    demo) port=8000; home="$REL" ;;
    marshal) port=8001; home="$FP_HOME_DEV" ;;
    david) port=8002; home="$FP_HOME_DEV" ;;
    dafa) port=8003; home="$FP_HOME_DEV" ;;
    nico) port=8004; home="$FP_HOME_DEV" ;;
  esac
  rt="$home/var/$inst"
  pid="-"; state="mati"; health="-"
  if [ -s "$rt/run/app.pid" ]; then
    pid="$(tr -dc '0-9' < "$rt/run/app.pid")"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then state="hidup"; else state="mati(pid basi)"; fi
  fi
  if [ "$state" = hidup ]; then
    health="$(curl -s -o /dev/null -m 2 -w '%{http_code}' "http://localhost:$port/api/v1/health" || echo err)"
  fi
  printf "  %-8s %-5s %-8s %-15s %-7s %-6s %s\n" "$inst" "$port" "$pid" "$state" "$health" "$(human "$rt/app.db")" "$home"
done

echo
echo "== LLM (llama-server :8080)"
llm_pid="$(pgrep -x llama-server | head -1 || true)"
if [ -n "$llm_pid" ]; then
  models="$(curl -s -m 3 http://localhost:8080/v1/models | python3 -c 'import sys,json; print(",".join(m["id"] for m in json.load(sys.stdin)["data"]))' 2>/dev/null || echo 'belum siap')"
  echo "  hidup pid $llm_pid · model: $models"
else
  echo "  mati (nyalakan: David, bash ~/work/start_llm.sh)"
fi

echo
echo "== GPU"
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi --query-gpu=memory.used,memory.total --format=csv 2>/dev/null | grep -v HAMI | sed 's/^/  /'
else
  echo "  nvidia-smi tidak ada"
fi

echo
echo "== Snapshot & release"
last_snap="$(ls -1t "$WORK"/snapshots/fp-*.tar.gz 2>/dev/null | head -1)"
if [ -n "$last_snap" ]; then
  echo "  snapshot terakhir: $(basename "$last_snap") ($(human "$last_snap"))"
else
  echo "  snapshot terakhir: belum ada"
fi
echo "  jumlah snapshot : $(ls -1 "$WORK"/snapshots/fp-*.tar.gz 2>/dev/null | wc -l)"
if [ -L "$REL" ]; then
  echo "  release aktif   : $(readlink "$REL")"
else
  echo "  release aktif   : belum ada"
fi

echo
echo "== Antrean heavy"
if [ -s "$FP_HOME_DEV/var/locks/heavy.owner" ]; then
  echo "  dipegang: $(cat "$FP_HOME_DEV/var/locks/heavy.owner")"
else
  echo "  kosong"
fi
