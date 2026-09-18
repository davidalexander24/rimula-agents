#!/usr/bin/env bash
# Start Qwen3-30B-A3B llama-server on port 8080. Usage: bash ~/work/start_llm.sh [n_cpu_moe] [ctx]
NCM=${1:-36}; CTX=${2:-16384}
source ~/work/llm-env.sh
pkill -x llama-server 2>/dev/null; sleep 2
cd ~/work/llama.cpp
nohup ./build/bin/llama-server \
  -m ~/work/models/Qwen3-30B-A3B-Instruct-2507-Q4_K_M.gguf \
  --alias qwen3-30b --host 0.0.0.0 --port 8080 --jinja \
  -ngl 99 --n-cpu-moe $NCM -c $CTX -fa on -t 16 --load-mode none \
  > ~/work/logs/llama-server.log 2>&1 &
echo "started (n-cpu-moe=$NCM ctx=$CTX); log: ~/work/logs/llama-server.log"
