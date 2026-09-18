#!/usr/bin/env bash
# Smoke test API satu instance - PRD §17.3 (tugas D-08). Pemilik: Nico (D).
# Usage: bash scripts/smoke_test.sh [port]      (default 8000 = demo; env harus sudah dimuat)
# Mencetak PASS/FAIL per langkah dan berhenti pada kegagalan pertama. Loop global di-reset di awal dan akhir,
# jadi JANGAN diarahkan ke instance anggota lain yang sedang dipakai.
set -euo pipefail

port="${1:-8000}"
case "$port" in
  '' | *[!0-9]*) echo "Usage: bash scripts/smoke_test.sh [port]" >&2; exit 2 ;;
esac
if [ -z "${FP_RUNTIME_DIR:-}" ]; then
  echo "smoke_test.sh: env belum dimuat. FP_MEMBER=<nama> source ~/work/formulapilot/scripts/env.sh" >&2
  exit 2
fi

API="http://localhost:$port/api/v1"
BRIEF="${SMOKE_BRIEF:-niacinamide_gel_cream}"
PY="$(command -v python3 || command -v python)"
mkdir -p "$FP_RUNTIME_DIR"
tmp="$(mktemp -d "$FP_RUNTIME_DIR/smoke.XXXXXX")"
trap 'rm -rf "$tmp"' EXIT
body="$tmp/body.json"
status=000

now_ms() { echo $(( $(date +%s%N) / 1000000 )); }
secs() { awk -v ms="$1" 'BEGIN { printf "%.1f", ms / 1000 }'; }

call() {
  local method="$1" path="$2" data="${3:-}"
  local args=(-sS -m 60 -o "$body" -w '%{http_code}' -X "$method" "$API$path")
  if [ -n "$data" ]; then args+=(-H 'Content-Type: application/json' --data "$data"); fi
  : > "$body"
  status="$(curl "${args[@]}" 2>"$tmp/curl.err" || true)"
  [ -n "$status" ] || status=000
}

field() {
  "$PY" - "${2:-$body}" "$1" 2>/dev/null <<'PY' || true
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    v = eval(sys.argv[2], {"d": d})
except Exception:
    v = ""
if isinstance(v, (dict, list, bool)):
    print(json.dumps(v, ensure_ascii=False))
else:
    print("" if v is None else v)
PY
}

errmsg() {
  local e
  e="$(field 'd["error"]["code"] + ": " + d["error"]["message"]')"
  if [ -z "$e" ] && [ -s "$tmp/curl.err" ]; then e="$(tr '\n' ' ' < "$tmp/curl.err")"; fi
  printf '%s' "$e"
}

step=0
dirty=0
t_start="$(now_ms)"
pass() { echo "PASS $step. $*"; }
fail() {
  echo "FAIL $step. $*"
  if [ "$dirty" = 1 ]; then
    call POST /progress/reset '{"scope":"global"}'
    echo "       loop global di-reset agar demo tetap bersih (HTTP $status)"
  fi
  exit 1
}

echo "smoke_test.sh: $API · brief $BRIEF · $(TZ=Asia/Jakarta date '+%H:%M:%S') WIB"

step=1
call GET /health
[ "$status" = 200 ] || fail "GET /health -> HTTP $status $(errmsg)"
[ "$(field 'd["data"]["model_ready"]')" = true ] || fail "model_ready bukan true: $(field 'd["data"]')"
pass "health: instance $(field 'd["data"]["instance"]'), model $(field 'd["data"]["model_version"]'), $(field '" ".join(k + "=" + str(d["data"][k]).lower() for k in ("llm_ready", "scout_ready", "market_ready", "evaluation_ready", "db_ready"))')"

step=2
call POST /progress/reset '{"scope":"global"}'
[ "$status" = 200 ] || fail "POST /progress/reset -> HTTP $status $(errmsg)"
[ "$(field 'd["data"]["batches"]')" = 0 ] || fail "batches setelah reset bukan 0: $(field 'd["data"]["batches"]')"
pass "reset loop global: batches 0"

step=3
t0="$(now_ms)"
call POST /runs "{\"run_mode\":\"explore\",\"brief_id\":\"$BRIEF\",\"n\":3,\"use_orchestrator\":false}"
[ "$status" = 202 ] || fail "POST /runs -> HTTP $status $(errmsg)"
run_id="$(field 'd["data"]["run_id"]')"
[ -n "$run_id" ] || fail "POST /runs tidak mengembalikan run_id"
run_status=running
for _ in $(seq 1 60); do
  sleep 1
  call GET "/runs/$run_id"
  [ "$status" = 200 ] || fail "GET /runs/$run_id -> HTTP $status $(errmsg)"
  run_status="$(field 'd["data"]["status"]')"
  [ "$run_status" = running ] || break
done
run_ms=$(( $(now_ms) - t0 ))
cp "$body" "$tmp/run.json"
[ "$run_status" = done ] || fail "run $run_id berstatus '$run_status' setelah $(secs "$run_ms") dtk (maks 60): $(field 'd["data"]["error"]')"
n_cand="$(field 'len(d["data"]["candidates"])')"
[ "$n_cand" = 3 ] || fail "run $run_id selesai dengan $n_cand kandidat (harus 3)"
bad_total="$(field '[c["candidate_id"] for c in d["data"]["candidates"] if abs(sum(c["formula"][k] for k in ("GLYCERIN", "NIACINAMIDE", "CETEARYL_ALCOHOL", "EMULSIFIER", "CCT", "DIMETHICONE", "XANTHAN", "CARBOMER", "NAOH", "PHENOXYETHANOL", "AQUA")) - 100) > 0.01]')"
[ "$bad_total" = "[]" ] || fail "total komposisi bukan 100% pada kandidat $bad_total"
pass "run explore $run_id done dalam $(secs "$run_ms") dtk: 3 kandidat, total 100%, gate $(field '[c["gate"]["status"] for c in sorted(d["data"]["candidates"], key=lambda c: c["rank"])]'), P_TARGET $(field '[round(c["prediction"]["P_TARGET"], 3) if c.get("prediction") else None for c in sorted(d["data"]["candidates"], key=lambda c: c["rank"])]')"

step=4
cand_id="$(field 'next((c["candidate_id"] for c in sorted(d["data"]["candidates"], key=lambda c: c["rank"]) if c["gate"]["status"] != "blocked"), "")' "$tmp/run.json")"
if [ -z "$cand_id" ]; then
  fail "semua kandidat blocked. Brief/Designer perlu dicek (A), bukan script ini. Issue error: $(field 'sorted({i["code"] for c in d["data"]["candidates"] for i in c["gate"]["issues"] if i["severity"] == "error"})' "$tmp/run.json")"
fi
pass "kandidat $cand_id (rank $(field 'next(c["rank"] for c in d["data"]["candidates"] if c["candidate_id"] == "'"$cand_id"'")' "$tmp/run.json"), gate $(field 'next(c["gate"]["status"] for c in d["data"]["candidates"] if c["candidate_id"] == "'"$cand_id"'")' "$tmp/run.json"))"

step=5
call POST "/candidates/$cand_id/decision" '{"decision":"approved","reason":"smoke test","acknowledged":true}'
[ "$status" = 200 ] || fail "POST /candidates/$cand_id/decision -> HTTP $status $(errmsg)"
[ "$(field 'd["data"]["decision"]')" = approved ] || fail "decision bukan approved: $(field 'd["data"]["decision"]')"
pass "keputusan approved"

step=6
dirty=1
t0="$(now_ms)"
call POST "/candidates/$cand_id/test"
test_ms=$(( $(now_ms) - t0 ))
[ "$status" = 200 ] || fail "POST /candidates/$cand_id/test -> HTTP $status $(errmsg)"
new_version="$(field 'd["data"]["lab_result"]["retrained_model_version"]')"
[ -n "$new_version" ] || fail "lab_result.retrained_model_version kosong"
pass "uji Virtual Lab batch $(field 'd["data"]["lab_result"]["batch_index"]'): $(field 'sum(1 for k, v in d["data"]["lab_result"]["specs_met"].items() if k != "ALL" and v)')/6 spesifikasi (ALL=$(field 'd["data"]["lab_result"]["specs_met"]["ALL"]')), model -> $new_version dalam $(secs "$test_ms") dtk"

step=7
call GET /evaluation
[ "$status" = 200 ] || fail "GET /evaluation -> HTTP $status $(errmsg)"
quick="$(field 'd["data"].get("quick")')"
pass "evaluation.json: generated_at $(field 'd["data"].get("generated_at")'), quick=$quick, varian closed_loop $(field 'sorted(k for k, v in d["data"].get("closed_loop", {}).get("results", {}).items() if v)')"
if [ "$quick" = true ]; then
  echo "WARN 7. evaluation.json hasil --quick, bukan evaluasi penuh. Tab Bukti belum memuat 20 seed x 3 varian."
fi

step=8
call POST /progress/reset '{"scope":"global"}'
[ "$status" = 200 ] || fail "POST /progress/reset -> HTTP $status $(errmsg)"
[ "$(field 'd["data"]["batches"]')" = 0 ] || fail "batches setelah reset bukan 0"
dirty=0
call GET /health
[ "$(field 'd["data"]["model_version"]')" = gp-global-v1 ] || fail "model setelah reset bukan gp-global-v1: $(field 'd["data"]["model_version"]')"
pass "reset loop global: batches 0, model gp-global-v1"

echo "SMOKE PASS: port $port, 8/8 langkah, $(secs $(( $(now_ms) - t_start ))) dtk"
