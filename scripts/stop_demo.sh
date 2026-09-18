#!/usr/bin/env bash
# Matikan instance demo port 8000 - PRD §16 (tugas D-08). Pemilik: Nico (D). Hanya Nico (R26).
# Usage: bash scripts/stop_demo.sh [--llm]
#   Demo dicari lewat PID file ~/work/release/*/var/demo/run/app.pid (release mana pun), tanpa pkill/killall (R7).
#   --llm ikut mematikan llama-server, hanya dengan izin David (R9):
#     LLM_STOP_APPROVED_BY=david bash scripts/stop_demo.sh --llm
set -euo pipefail

if [ "${FP_MEMBER:-}" != nico ]; then
  echo "stop_demo.sh: hanya Nico (R26). Muat env: FP_MEMBER=nico source ~/work/formulapilot/scripts/env.sh" >&2
  exit 1
fi

stop_llm=0
case "${1:-}" in
  '') ;;
  --llm) stop_llm=1 ;;
  *) echo "Usage: bash scripts/stop_demo.sh [--llm]" >&2; exit 2 ;;
esac
if [ "$stop_llm" = 1 ] && [ "${LLM_STOP_APPROVED_BY:-}" != david ]; then
  echo "stop_demo.sh: --llm butuh izin David (R9). Setelah David setuju: LLM_STOP_APPROVED_BY=david bash scripts/stop_demo.sh --llm" >&2
  exit 1
fi

stopped=0
for pidf in "$HOME"/work/release/*/var/demo/run/app.pid; do
  [ -s "$pidf" ] || continue
  release="$(cd "$(dirname "$pidf")/../../.." && pwd -P)"
  pid="$(tr -dc '0-9' < "$pidf")"
  if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
    echo "stop_demo.sh: PID basi ($pid) di $(basename "$release"), file PID dihapus."
    rm -f "$pidf"
    continue
  fi
  if ! tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -q 'uvicorn.*--port 8000'; then
    echo "stop_demo.sh: PID $pid bukan uvicorn port 8000 (PID dipakai ulang?). Tidak di-kill; file PID dihapus." >&2
    rm -f "$pidf"
    continue
  fi
  # start_demo.sh menyalakan dengan setsid, jadi PID = process group.
  kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
  for _ in 1 2 3 4 5; do
    kill -0 "$pid" 2>/dev/null || break
    sleep 1
  done
  if kill -0 "$pid" 2>/dev/null; then
    echo "stop_demo.sh: belum berhenti setelah 5 detik, SIGKILL pid $pid."
    kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
  fi
  rm -f "$pidf"
  echo "stop_demo.sh: demo dimatikan (pid $pid, release $(basename "$release"))."
  stopped=1
done
if [ "$stopped" = 0 ]; then
  echo "stop_demo.sh: demo tidak berjalan."
fi

if [ "$stop_llm" = 1 ]; then
  llm_pid="$(pgrep -x llama-server | head -1 || true)"
  if [ -z "$llm_pid" ]; then
    echo "stop_demo.sh: llama-server tidak berjalan."
  else
    kill -TERM "$llm_pid" 2>/dev/null || true
    for _ in $(seq 1 15); do
      kill -0 "$llm_pid" 2>/dev/null || break
      sleep 1
    done
    if kill -0 "$llm_pid" 2>/dev/null; then
      echo "stop_demo.sh: llama-server belum berhenti setelah 15 detik (pid $llm_pid). Tanyakan David." >&2
      exit 1
    fi
    echo "stop_demo.sh: llama-server dimatikan (pid $llm_pid, izin David). Nyalakan lagi: bash ~/work/start_llm.sh"
  fi
fi
