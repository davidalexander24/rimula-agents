#!/usr/bin/env bash
# Nyalakan backend dev milik anggota — PRD §6.4, §16 (tugas D-03). Pemilik: Nico (D).
# Usage: bash scripts/dev_up.sh <nama>        (env harus sudah dimuat: FP_MEMBER=<nama> source scripts/env.sh)
#   FP_ASGI_APP=<modul:app>  override aplikasi (default backend.app.main:app; hanya untuk test script)
set -euo pipefail

name="${1:-}"
if [ -z "$name" ]; then
  echo "Usage: bash scripts/dev_up.sh <marshal|david|dafa|nico>" >&2
  exit 2
fi
case "$name" in
  marshal) port=8001 ;;
  david) port=8002 ;;
  dafa) port=8003 ;;
  nico) port=8004 ;;
  demo) echo "dev_up.sh: instance demo dinyalakan lewat scripts/start_demo.sh (khusus Nico)." >&2; exit 2 ;;
  *) echo "dev_up.sh: nama tidak dikenal: $name" >&2; exit 2 ;;
esac
if [ "${FP_MEMBER:-}" != "$name" ]; then
  echo "dev_up.sh: ditolak — FP_MEMBER='${FP_MEMBER:-}' bukan '$name'. Muat env dulu: FP_MEMBER=$name source ~/work/formulapilot/scripts/env.sh" >&2
  exit 1
fi
if [ "${APP_PORT:-}" != "$port" ] || [ -z "${FP_RUNTIME_DIR:-}" ] || [ -z "${FP_HOME:-}" ]; then
  echo "dev_up.sh: env tidak lengkap/tidak cocok (APP_PORT='${APP_PORT:-}', harus $port). Muat ulang env.sh." >&2
  exit 1
fi

app="${FP_ASGI_APP:-backend.app.main:app}"
run_dir="$FP_RUNTIME_DIR/run"
log_dir="$FP_RUNTIME_DIR/logs"
pidf="$run_dir/app.pid"
log="$log_dir/app.log"
mkdir -p "$run_dir" "$log_dir" "$FP_RUNTIME_DIR/models"
cd "$FP_HOME"

if [ "$app" = "backend.app.main:app" ] && [ ! -f backend/app/main.py ]; then
  echo "dev_up.sh: backend/app/main.py belum ada (menunggu B-02 David)." >&2
  exit 1
fi
if ! command -v python >/dev/null 2>&1 || ! python -c "import uvicorn" 2>/dev/null; then
  echo "dev_up.sh: uvicorn tidak ditemukan; venv ~/work/venvs/fp belum aktif?" >&2
  exit 1
fi

# Hentikan instance lama milik sendiri (hanya dari PID file, R7).
if [ -s "$pidf" ]; then
  bash "$FP_HOME/scripts/dev_down.sh" "$name"
fi

# Port harus kosong.
if curl -s -o /dev/null -m 2 "http://localhost:$port/"; then
  echo "dev_up.sh: port $port sudah dipakai proses lain (bukan dari PID file $pidf). Tidak dinyalakan." >&2
  exit 1
fi

reload=()
if [ "$name" = david ]; then reload=(--reload --reload-dir fp --reload-dir backend); fi

echo "=== $(date '+%F %T') dev_up $name port $port app $app ===" >> "$log"
setsid nohup python -m uvicorn "$app" --host 0.0.0.0 --port "$port" --workers 1 "${reload[@]}" \
  >> "$log" 2>&1 < /dev/null &
pid=$!
echo "$pid" > "$pidf.tmp.$$"
mv -f "$pidf.tmp.$$" "$pidf"

echo "dev_up.sh: $name pid $pid, menunggu /api/v1/health (maks 40 detik)..."
for _ in $(seq 1 40); do
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "dev_up.sh: proses berhenti saat startup. Log terakhir ($log):" >&2
    tail -n 30 "$log" >&2
    rm -f "$pidf"
    exit 1
  fi
  code="$(curl -s -o /dev/null -m 2 -w '%{http_code}' "http://localhost:$port/api/v1/health" || true)"
  if [ "$code" = 200 ]; then
    echo "dev_up.sh: sehat. URL: ${FP_PUBLIC_HOST:-http://<jupyter-host>}/respati/${NOTEBOOK_ID:-<NOTEBOOK_ID>}/proxy/$port/"
    echo "  log: $log"
    exit 0
  fi
  sleep 1
done
echo "dev_up.sh: /api/v1/health belum 200 setelah 40 detik (proses masih hidup, pid $pid). Log terakhir:" >&2
tail -n 30 "$log" >&2
exit 1
