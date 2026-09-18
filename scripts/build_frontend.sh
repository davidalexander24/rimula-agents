#!/usr/bin/env bash
# Pemilik: Dafa (C). Jalankan: bash scripts/heavy.sh bash scripts/build_frontend.sh
set -euo pipefail
if [[ "${FP_MEMBER:-}" != dafa || -z "${FP_HOME:-}" ]]; then
  echo "Muat env Dafa sebelum build." >&2
  exit 2
fi
if [[ "${OMP_NUM_THREADS:-}" != 8 || ! -f "$FP_HOME/var/locks/heavy.owner" ]]; then
  echo "Build wajib lewat: bash scripts/heavy.sh bash scripts/build_frontend.sh" >&2
  exit 2
fi
cd "$FP_HOME/frontend"
export npm_config_progress=false
if [[ ! -f package-lock.json ]]; then
  npm install --package-lock-only --no-audit --no-fund
fi
fingerprint="$(python - <<'PY'
from pathlib import Path
import hashlib
print(hashlib.sha256(Path('package.json').read_bytes()+Path('package-lock.json').read_bytes()).hexdigest())
PY
)"
installed="$(cat .deps.sha256 2>/dev/null || true)"
if [[ ! -d node_modules || "$fingerprint" != "$installed" ]]; then
  npm ci --no-audit --no-fund
  FP_DEP_HASH="$fingerprint" python - <<'PY'
import os
from fp.io_utils import write_text
write_text('.deps.sha256', os.environ['FP_DEP_HASH']+'\n')
PY
fi
npm run build -- --outDir dist.tmp
python - <<'PY'
from pathlib import Path
from fp.io_utils import write_text
import os, shutil
root=Path.cwd()
assert root.name=='frontend'
staged=root/'dist.tmp'
current=root/'dist'
previous=root/'dist.previous'
assert (staged/'index.html').is_file(), 'Build belum memiliki index.html'
if (current/'assets').is_dir():
    shutil.copytree(current/'assets',staged/'assets',dirs_exist_ok=True)
if previous.exists():
    shutil.rmtree(previous)
moved=False
try:
    if current.exists():
        os.rename(current,previous)
        moved=True
    os.rename(staged,current)
except BaseException:
    if moved and not current.exists():
        os.rename(previous,current)
    raise
if previous.exists():
    shutil.rmtree(previous)
write_text(root/'.last-build','Build produksi selesai\n')
print('BUILD_READY: frontend/dist/index.html')
PY
