#!/usr/bin/env bash
# Nyalakan demo: LLM (bila mati) + release beku di port 8000 - PRD §16 (tugas D-08). Pemilik: Nico (D). Hanya Nico (R26).
# Usage: bash scripts/start_demo.sh
#   LLM_WAIT_S=<detik>    tunggu llama-server siap (default 180); lewat batas, demo tetap jalan dalam mode degraded
#   READY_WAIT_S=<detik>  tunggu health semua true, termasuk warmup Scout (default 120)
# Demo lama (dari release mana pun) dimatikan dulu lewat stop_demo.sh. Instance demo memakai path asli
# release (bukan symlink current), jadi release.sh berikutnya tidak mengganggu demo yang sedang jalan.
set -euo pipefail

WORK="$HOME/work"
CURRENT="$WORK/release/current"
PORT=8000
LLM_WAIT_S="${LLM_WAIT_S:-180}"
READY_WAIT_S="${READY_WAIT_S:-120}"
SCRIPTS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "${FP_MEMBER:-}" != nico ]; then
  echo "start_demo.sh: hanya Nico (R26). Muat env: FP_MEMBER=nico source ~/work/formulapilot/scripts/env.sh" >&2
  exit 1
fi
if [ ! -L "$CURRENT" ] || [ ! -f "$CURRENT/backend/app/main.py" ]; then
  echo "start_demo.sh: belum ada release aktif. Jalankan dulu: bash scripts/release.sh" >&2
  exit 1
fi
release="$(readlink -f "$CURRENT")"
t_start=$(date +%s)

echo "== [1/4] LLM"
if ! pgrep -x llama-server >/dev/null; then
  echo "start_demo.sh: llama-server mati, menyalakan lewat ~/work/start_llm.sh"
  bash "$WORK/start_llm.sh"
fi
llm_ready=0
deadline=$(( $(date +%s) + LLM_WAIT_S ))
while [ "$(date +%s)" -lt "$deadline" ]; do
  if curl -sf -m 3 http://localhost:8080/v1/models >/dev/null; then llm_ready=1; break; fi
  sleep 2
done
if [ "$llm_ready" = 1 ]; then
  echo "start_demo.sh: LLM siap."
else
  echo "start_demo.sh: PERINGATAN LLM belum siap setelah ${LLM_WAIT_S} dtk. Demo tetap dinyalakan (degraded, ringkasan template). Kabari David." >&2
fi

echo "== [2/4] matikan demo lama"
bash "$SCRIPTS/stop_demo.sh"
if curl -s -o /dev/null -m 2 "http://localhost:$PORT/"; then
  echo "start_demo.sh: port $PORT dipakai proses yang bukan demo (tidak ada di PID file). Tidak dinyalakan." >&2
  exit 1
fi

echo "== [3/4] nyalakan $(basename "$release") di port $PORT"
unset _FP_HOME_AUTO
export FP_HOME="$release"
set +u
if ! FP_MEMBER=demo source "$release/scripts/env.sh" >/dev/null; then
  echo "start_demo.sh: env demo gagal dimuat dari $release" >&2
  exit 1
fi
set -u
if [ "$APP_PORT" != "$PORT" ] || [ "$FP_RUNTIME_DIR" != "$release/var/demo" ]; then
  echo "start_demo.sh: env demo tidak cocok (APP_PORT=$APP_PORT, FP_RUNTIME_DIR=$FP_RUNTIME_DIR)." >&2
  exit 1
fi
mkdir -p "$FP_RUNTIME_DIR/models" "$FP_RUNTIME_DIR/logs" "$FP_RUNTIME_DIR/run"
log="$FP_RUNTIME_DIR/logs/app.log"
pidf="$FP_RUNTIME_DIR/run/app.pid"
cd "$release"
echo "=== $(date '+%F %T') start_demo $(basename "$release") port $PORT ===" >> "$log"
setsid nohup python -m uvicorn backend.app.main:app --host 0.0.0.0 --port "$PORT" --workers 1 \
  >> "$log" 2>&1 < /dev/null &
pid=$!
echo "$pid" > "$pidf.tmp.$$"
mv -f "$pidf.tmp.$$" "$pidf"

healthy=0
for _ in $(seq 1 60); do
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "start_demo.sh: proses demo berhenti saat startup. Log terakhir ($log):" >&2
    tail -n 30 "$log" >&2
    rm -f "$pidf"
    exit 1
  fi
  if [ "$(curl -s -o /dev/null -m 2 -w '%{http_code}' "http://localhost:$PORT/api/v1/health" || true)" = 200 ]; then
    healthy=1
    break
  fi
  sleep 1
done
if [ "$healthy" = 0 ]; then
  echo "start_demo.sh: /api/v1/health belum 200 setelah 60 dtk (pid $pid masih hidup). Log terakhir:" >&2
  tail -n 30 "$log" >&2
  exit 1
fi

echo "== [4/4] tunggu health lengkap (maks ${READY_WAIT_S} dtk)"
health=""
deadline=$(( $(date +%s) + READY_WAIT_S ))
while :; do
  health="$(curl -s -m 3 "http://localhost:$PORT/api/v1/health" | python -c '
import json, sys
d = json.load(sys.stdin)["data"]
keys = ("model_ready", "llm_ready", "scout_ready", "market_ready", "evaluation_ready", "db_ready")
missing = [k for k in keys if not d.get(k)]
print(("OK " if not missing else "BELUM " + ",".join(missing) + " ") + "model=" + str(d.get("model_version")))
' 2>/dev/null || echo "BELUM health-tidak-terbaca")"
  case "$health" in OK*) break ;; esac
  if [ "$(date +%s)" -ge "$deadline" ]; then break; fi
  sleep 3
done
echo "start_demo.sh: health $health · $(( $(date +%s) - t_start )) dtk sejak mulai"
echo "start_demo.sh: demo pid $pid · log $log"
echo "  URL: ${FP_PUBLIC_HOST:-http://<jupyter-host>}/respati/${NOTEBOOK_ID}/proxy/$PORT/"
echo "  Cek: bash scripts/smoke_test.sh $PORT"
echo
bash "$SCRIPTS/status.sh"
