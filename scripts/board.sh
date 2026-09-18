#!/usr/bin/env bash
# Papan koordinasi (read-only) — PRD §6.5. Pemilik: Nico (D).
# Usage: bash scripts/board.sh
set -euo pipefail

FP_HOME="${FP_HOME:-$HOME/work/formulapilot}"
C="$FP_HOME/coordination"
LOCK_DIR="$FP_HOME/var/locks"

echo "================ STATUS · $(TZ=Asia/Jakarta date '+%d %b %H:%M') WIB ================"
for n in marshal david dafa nico; do
  f="$C/status/$n.md"
  [ -f "$f" ] || continue
  echo
  sed -n '1p' "$f"
  grep -E '^\| [A-D]-[0-9]+' "$f" | awk -F'|' '{
    for (i = 2; i <= 6; i++) gsub(/^ +| +$/, "", $i)
    printf "  %-24.24s %-5s %-50.50s %s\n", $3, $4, $2, $6
  }' || true
done

echo
echo "================ REQUEST BELUM DIJAWAB ================"
found=0
for f in "$C"/requests/*.md; do
  [ -e "$f" ] || continue
  answer="$(awk '/^## Jawaban/{f=1; next} f' "$f" | grep -vE '^[[:space:]]*$|^[[:space:]]*<!--' || true)"
  if [ -z "$answer" ]; then
    untuk="$(grep -m1 -i 'untuk:' "$f" | sed -E 's/.*[Uu]ntuk:[*]* *//' || true)"
    mendesak="$(grep -m1 -i 'mendesak:' "$f" | sed -E 's/.*[Mm]endesak:[*]* *//' || true)"
    echo "  $(basename "$f")  -> ${untuk:-?}  (mendesak: ${mendesak:-?})"
    found=1
  fi
done
[ "$found" -eq 1 ] || echo "  (tidak ada)"

echo
echo "================ ANTREAN HEAVY ================"
if [ -s "$LOCK_DIR/heavy.owner" ]; then
  echo "  dipegang: $(cat "$LOCK_DIR/heavy.owner")"
else
  echo "  kosong"
fi

echo
echo "================ INSTANCE ================"
for inst in demo marshal david dafa nico; do
  case "$inst" in
    demo) port=8000; pidf="$HOME/work/release/current/var/demo/run/app.pid" ;;
    marshal) port=8001; pidf="$FP_HOME/var/marshal/run/app.pid" ;;
    david) port=8002; pidf="$FP_HOME/var/david/run/app.pid" ;;
    dafa) port=8003; pidf="$FP_HOME/var/dafa/run/app.pid" ;;
    nico) port=8004; pidf="$FP_HOME/var/nico/run/app.pid" ;;
  esac
  pid="-"; state="mati"; health="-"
  if [ -s "$pidf" ]; then
    pid="$(cat "$pidf")"
    if kill -0 "$pid" 2>/dev/null; then state="hidup"; else state="mati(pid basi)"; fi
  fi
  if [ "$state" = hidup ]; then
    health="$(curl -s -o /dev/null -m 2 -w '%{http_code}' "http://localhost:$port/api/v1/health" || true)"
  fi
  printf "  %-8s port %s  pid %-8s %-15s health %s\n" "$inst" "$port" "$pid" "$state" "$health"
done
if pgrep -x llama-server >/dev/null 2>&1; then
  echo "  llama-server (8080): hidup"
else
  echo "  llama-server (8080): mati"
fi
