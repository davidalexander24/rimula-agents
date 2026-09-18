#!/usr/bin/env bash
# Release beku untuk demo port 8000 - PRD §6.3 (tugas D-08). Pemilik: Nico (D). Hanya Nico (R26).
# Usage:
#   bash scripts/release.sh [--allow-quick-eval]   release baru dari ~/work/formulapilot, current diarahkan ke sana
#   bash scripts/release.sh --list                 daftar release (* = current)
#   bash scripts/release.sh --rollback [fp-...]    current kembali ke release sebelumnya (atau yang disebut)
# Setelah release/rollback, demo yang sedang jalan tetap memakai release lamanya sampai: bash scripts/start_demo.sh
# Release tidak pernah menjalankan npm; frontend/dist wajib sudah di-build Dafa.
set -euo pipefail

WORK="$HOME/work"
SRC="$WORK/formulapilot"
REL_DIR="$WORK/release"
CURRENT="$REL_DIR/current"

if [ "${FP_MEMBER:-}" != nico ]; then
  echo "release.sh: hanya Nico (R26). Muat env: FP_MEMBER=nico source ~/work/formulapilot/scripts/env.sh" >&2
  exit 1
fi

mode=release
allow_quick=0
target=""
while [ $# -gt 0 ]; do
  case "$1" in
    --allow-quick-eval) allow_quick=1 ;;
    --list) mode=list ;;
    --rollback)
      mode=rollback
      if [ $# -gt 1 ] && [ "${2#--}" = "$2" ]; then target="$(basename "$2")"; shift; fi ;;
    *) echo "release.sh: argumen tidak dikenal: $1" >&2; exit 2 ;;
  esac
  shift
done

mkdir -p "$REL_DIR" "$SRC/var/locks" "$SRC/var/nico/logs"
list_releases() {
  find "$REL_DIR" -mindepth 1 -maxdepth 1 -type d -name 'fp-*' ! -name '*.part' -printf '%f\n' | sort
}
cur="$(readlink "$CURRENT" 2>/dev/null || true)"
point_current() {
  ln -sfn "$1" "$REL_DIR/current.tmp.$$"
  mv -Tf "$REL_DIR/current.tmp.$$" "$CURRENT"
}

if [ "$mode" = list ]; then
  list_releases | while read -r r; do
    if [ "$r" = "$cur" ]; then echo "* $r"; else echo "  $r"; fi
  done
  exit 0
fi

exec 9>"$SRC/var/locks/release.lock"
if ! flock -n 9; then
  echo "release.sh: release/rollback lain sedang berjalan (var/locks/release.lock)." >&2
  exit 75
fi

if [ "$mode" = rollback ]; then
  if [ -z "$target" ]; then
    target="$(list_releases | awk -v c="$cur" '$0 == c { print prev; exit } { prev = $0 }')"
  fi
  if [ -z "$target" ] || [ ! -d "$REL_DIR/$target" ]; then
    echo "release.sh: tidak ada release tujuan rollback (current: ${cur:-kosong}). Lihat: bash scripts/release.sh --list" >&2
    exit 1
  fi
  point_current "$target"
  echo "release.sh: current -> $target (sebelumnya ${cur:-kosong}). Muat ulang demo: bash scripts/start_demo.sh"
  exit 0
fi

name="fp-$(date +%Y%m%d-%H%M%S)"
part="$REL_DIR/$name.part"
log="$SRC/var/nico/logs/release-$name.log"
cd "$SRC"
stop() {
  echo "release.sh: BERHENTI - $*" >&2
  exit 1
}

echo "== [1/7] compileall fp backend"
python -m compileall -q fp backend || stop "compileall gagal"

echo "== [2/7] pytest backend/tests lewat heavy.sh (log: $log)"
if ! bash scripts/heavy.sh python -m pytest -q -p no:cacheprovider backend/tests 2>&1 | tee "$log"; then
  stop "test gagal, release tidak dibuat. Lihat $log"
fi
tests_summary="$(grep -E '(passed|failed|error)' "$log" | tail -1 || true)"

echo "== [3/7] artefak: frontend/dist, model dasar, evaluation.json"
[ -f frontend/dist/index.html ] || stop "frontend/dist/index.html belum ada. Minta Dafa: bash scripts/heavy.sh bash scripts/build_frontend.sh"
stale="$(find frontend/src -type f -newer frontend/dist/index.html 2>/dev/null | head -5)"
if [ -n "$stale" ]; then
  stop "frontend/dist lebih lama dari frontend/src (mis. ${stale//$'\n'/, }). Minta Dafa: bash scripts/heavy.sh bash scripts/build_frontend.sh"
fi
[ -f artifacts/models/gp-global-v1.joblib ] || stop "artifacts/models/gp-global-v1.joblib belum ada (A-06)"
eval_quick="$(python -c 'import json; print(str(json.load(open("artifacts/evaluation.json")).get("quick")).lower())' 2>/dev/null)" \
  || stop "artifacts/evaluation.json tidak ada/tidak valid (A-11)"
if [ "$eval_quick" = true ] && [ "$allow_quick" = 0 ]; then
  stop "artifacts/evaluation.json hasil --quick (bukan 20 seed x 3 varian). Jalankan evaluasi penuh dulu, atau ulangi dengan --allow-quick-eval bila memang disengaja"
fi

echo "== [4/7] snapshot pre-release"
bash scripts/snapshot.sh pre-release

echo "== [5/7] salin ke $part"
trap 'rm -rf "$part"' EXIT
mkdir -p "$part"
rc=0
tar -C "$SRC" -cf - \
  --anchored \
  --exclude=./var --exclude=./coordination \
  --exclude=./frontend/node_modules --exclude=./frontend/src \
  --exclude=./frontend/dist.tmp --exclude=./frontend/dist.previous \
  --no-anchored \
  --exclude=__pycache__ --exclude=.pytest_cache \
  . | tar -C "$part" -xf - || rc=$?
# tar exit 1 = file berubah saat dibaca (agent lain sedang menulis); isi tetap tersalin.
if [ "$rc" -gt 1 ]; then stop "tar gagal (exit $rc)"; fi
mkdir -p "$part/var/demo/models" "$part/var/demo/logs" "$part/var/demo/run"

REL_NAME="$name" REL_TESTS="$tests_summary" REL_ALLOW_QUICK="$allow_quick" python - "$part" <<'PY'
import json, os, sys
from pathlib import Path
from fp.config import now_iso
from fp.io_utils import write_json

part = Path(sys.argv[1])
ev = json.loads((part / "artifacts/evaluation.json").read_text())
model = part / "artifacts/models/gp-global-v1.json"
write_json(part / "RELEASE.json", {
    "release": os.environ["REL_NAME"],
    "created_at": now_iso(),
    "created_by": os.environ.get("FP_MEMBER"),
    "source": "~/work/formulapilot",
    "tests": os.environ["REL_TESTS"],
    "evaluation": {"generated_at": ev.get("generated_at"), "quick": ev.get("quick"),
                   "allowed_quick": os.environ["REL_ALLOW_QUICK"] == "1"},
    "base_model": json.loads(model.read_text()) if model.exists() else None,
    "frontend_dist_mtime": os.path.getmtime(part / "frontend/dist/index.html"),
})
PY
mv "$part" "$REL_DIR/$name"
trap - EXIT

echo "== [6/7] current -> $name (sebelumnya ${cur:-kosong})"
point_current "$name"

echo "== [7/7] selesai"
echo "$REL_DIR/$name"
for pidf in "$REL_DIR"/fp-*/var/demo/run/app.pid; do
  [ -s "$pidf" ] || continue
  pid="$(tr -dc '0-9' < "$pidf")"
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    echo "release.sh: demo masih berjalan dari release lama (pid $pid). Pindahkan: bash scripts/start_demo.sh"
  fi
done
