#!/usr/bin/env bash
# Snapshot pohon kerja (pengganti Git) — PRD §6.2. Pemilik: Nico (D).
# Usage: bash scripts/snapshot.sh "<alasan>"
set -euo pipefail

WORK="$HOME/work"
SRC="$WORK/formulapilot"
DEST="$WORK/snapshots"
KEEP=40

reason="$(printf '%s' "${1:-manual}" | tr -c 'A-Za-z0-9._-' '-' | cut -c1-40)"
member="${FP_MEMBER:-unknown}"
mkdir -p "$DEST" "$SRC/var/locks"

exec 9>"$SRC/var/locks/snapshot.lock"
if ! flock -w 60 9; then
  echo "snapshot.sh: kunci snapshot dipegang proses lain lebih dari 60 detik. Coba lagi." >&2
  exit 75
fi

out="$DEST/fp-$(date +%Y%m%d-%H%M%S)-$member-$reason.tar.gz"
tmp="$out.part"
trap 'rm -f "$tmp"' EXIT

rc=0
tar -C "$WORK" -czf "$tmp" \
  --warning=no-file-changed \
  --exclude='formulapilot/frontend/node_modules' \
  --exclude='formulapilot/frontend/dist' \
  --exclude='formulapilot/var' \
  --exclude='__pycache__' \
  --exclude='.pytest_cache' \
  --exclude='formulapilot/artifacts/scout/embeddings.npy' \
  --exclude='formulapilot/data/market/obf_raw.csv.gz' \
  --exclude='formulapilot/data/validation/liposome/*.zip' \
  formulapilot || rc=$?
# tar exit 1 = ada file berubah saat dibaca (wajar, 4 agent bekerja paralel).
if [ "$rc" -gt 1 ]; then
  echo "snapshot.sh: tar gagal (exit $rc)" >&2
  exit "$rc"
fi
mv -f "$tmp" "$out"
trap - EXIT

ls -1t "$DEST"/fp-*.tar.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f
echo "$out"
