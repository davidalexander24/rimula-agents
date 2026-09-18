# shellcheck shell=bash
# FormulaPilot — environment per anggota (PRD §7.3). Pemilik: Nico (D). Jangan diedit anggota lain (R24).
#
# Di-SOURCE, bukan dijalankan:
#   FP_MEMBER=<marshal|david|dafa|nico> source ~/work/formulapilot/scripts/env.sh
#   FP_MEMBER=demo source ~/work/formulapilot/scripts/env.sh     # khusus Nico; FP_HOME = ~/work/release/current
#
# Jangan memuat ~/work/llm-env.sh di terminal aplikasi (khusus llama.cpp).

if [ "${BASH_SOURCE[0]:-$0}" = "$0" ]; then
  echo "env.sh harus di-source: FP_MEMBER=<nama> source $0" >&2
  exit 1
fi

_fp_env() {
  local member="${FP_MEMBER:-}" port work="$HOME/work"

  # 1. FP_MEMBER wajib valid; jika tidak, keluar tanpa mengubah env.
  case "$member" in
    demo) port=8000 ;;
    marshal) port=8001 ;;
    david) port=8002 ;;
    dafa) port=8003 ;;
    nico) port=8004 ;;
    *)
      echo "env.sh: FP_MEMBER wajib salah satu dari marshal|david|dafa|nico|demo (sekarang: '${member}'). Env tidak diubah." >&2
      return 1 ;;
  esac

  # 2. FP_HOME: default per instance, bisa di-override. Default lama dihitung ulang saat ganti anggota.
  local home_default="$work/formulapilot" fp_home
  if [ "$member" = demo ]; then home_default="$work/release/current"; fi
  if [ -z "${FP_HOME:-}" ] || [ "${FP_HOME}" = "${_FP_HOME_AUTO:-}" ]; then
    fp_home="$home_default"
  else
    fp_home="$FP_HOME"
  fi
  if [ ! -d "$fp_home" ]; then
    echo "env.sh: FP_HOME tidak ditemukan: $fp_home. Env tidak diubah." >&2
    return 1
  fi
  if [ "$fp_home" = "$home_default" ]; then _FP_HOME_AUTO="$fp_home"; fi

  # 8 (bagian .env). Muat .env tanpa menimpa variabel instance, thread, dan path.
  local envfile="$fp_home/.env" line key val
  local protected=" FP_MEMBER FP_HOME INSTANCE APP_PORT FP_RUNTIME_DIR PUBLIC_ROOT_PATH OMP_NUM_THREADS OPENBLAS_NUM_THREADS MKL_NUM_THREADS NUMEXPR_NUM_THREADS TOKENIZERS_PARALLELISM PYTHONPATH PATH HOME CLAUDE_CONFIG_DIR CODEX_HOME "
  if [ -f "$envfile" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
      line="${line%$'\r'}"
      case "$line" in
        '' | '#'*) continue ;;
      esac
      [[ "$line" == *=* ]] || continue
      line="${line#export }"
      key="${line%%=*}"
      val="${line#*=}"
      [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
      [[ "$protected" == *" $key "* ]] && continue
      if [[ "$val" =~ ^\"(.*)\"$ ]] || [[ "$val" =~ ^\'(.*)\'$ ]]; then val="${BASH_REMATCH[1]}"; fi
      export "$key=$val"
    done < "$envfile"
  fi

  # 3. Instance (PRD §6.4).
  local nb="${NOTEBOOK_ID:-}"
  if [ -z "$nb" ]; then
    nb="<NOTEBOOK_ID>"
    echo "env.sh: NOTEBOOK_ID belum diisi di .env (hanya dipakai di balik proxy Jupyter)" >&2
  fi
  export NOTEBOOK_ID="$nb"
  # `FP_MEMBER=x source env.sh` membuat FP_MEMBER/FP_HOME sementara yang dikembalikan bash setelah source
  # selesai (walau di-export). unset + declare -g menulis ke scope global agar nilainya bertahan.
  unset FP_MEMBER FP_HOME
  declare -gx FP_MEMBER="$member" FP_HOME="$fp_home"
  export INSTANCE="$member" APP_PORT="$port"
  export FP_RUNTIME_DIR="$fp_home/var/$member"
  export PUBLIC_ROOT_PATH="/respati/$nb/proxy/$port"
  mkdir -p "$FP_RUNTIME_DIR/models" "$FP_RUNTIME_DIR/logs" "$FP_RUNTIME_DIR/run"
  if [ "$member" != demo ]; then mkdir -p "$fp_home/var/test/$member"; fi

  # 4. Semua cache di ~/work.
  export PIP_CACHE_DIR="$work/pip-cache"
  export HF_HOME="$work/hf"
  export npm_config_cache="$work/npm-cache"
  export MPLCONFIGDIR="$work/.mplconfig/$member"
  mkdir -p "$MPLCONFIGDIR" "$npm_config_cache"

  # 5. Batas thread (PRD §6.8, R18). Jangan diubah.
  export OMP_NUM_THREADS=3 OPENBLAS_NUM_THREADS=3 MKL_NUM_THREADS=3 NUMEXPR_NUM_THREADS=3
  export TOKENIZERS_PARALLELISM=false

  # 6. Config AI agent per anggota (PRD §6.9).
  if [ "$member" != demo ]; then
    mkdir -p "$work/.agents/$member/claude" "$work/.agents/$member/codex"
    chmod 700 "$work/.agents" "$work/.agents/$member" "$work/.agents/$member/claude" "$work/.agents/$member/codex" 2>/dev/null || true
    export CLAUDE_CONFIG_DIR="$work/.agents/$member/claude"
    export CODEX_HOME="$work/.agents/$member/codex"
  fi

  # 7. Node.js & venv.
  case ":$PATH:" in
    *":$work/node-env/bin:"*) ;;
    *) export PATH="$work/node-env/bin:$PATH" ;;
  esac
  if [ -f "$work/venvs/fp/bin/activate" ]; then
    # shellcheck disable=SC1091
    VIRTUAL_ENV_DISABLE_PROMPT=1 . "$work/venvs/fp/bin/activate"
  else
    echo "env.sh: PERINGATAN venv ~/work/venvs/fp belum ada (dibuat oleh D-02)." >&2
  fi

  # 8. PYTHONPATH & folder kerja.
  export PYTHONPATH="$fp_home"
  cd "$fp_home" || return 1

  # 9. Prompt terminal.
  PS1="[fp:$member] \w\$ "

  echo "FormulaPilot env aktif: member=$member port=$APP_PORT"
  echo "  FP_HOME=$FP_HOME"
  echo "  FP_RUNTIME_DIR=$FP_RUNTIME_DIR"
  echo "  URL: ${FP_PUBLIC_HOST:-http://<jupyter-host>}$PUBLIC_ROOT_PATH/"
}

_fp_env
_fp_rc=$?
unset -f _fp_env
return "$_fp_rc"
