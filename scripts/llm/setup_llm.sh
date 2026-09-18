#!/usr/bin/env bash
# Install llama.cpp (CUDA) + Qwen3-30B-A3B-Instruct-2507 GGUF, everything under ~/work
set -o pipefail
W=$HOME/work
mkdir -p $W/{models,hf,pip-cache,conda-pkgs,logs}
exec > >(tee -a $W/logs/setup.log) 2>&1
echo "== START $(date)"

cat > $W/llm-env.sh <<'EOF'
export HF_HOME=$HOME/work/hf
export PIP_CACHE_DIR=$HOME/work/pip-cache
export CONDA_PKGS_DIRS=$HOME/work/conda-pkgs
export HF_XET_HIGH_PERFORMANCE=1
export PYTHONUSERBASE=$HOME/work/pyuser
export PATH=$HOME/work/pyuser/bin:$PATH
if [ -d $HOME/work/env ]; then source /opt/conda/etc/profile.d/conda.sh; conda activate $HOME/work/env; fi
EOF
source $W/llm-env.sh


# ---- toolchain
if [ ! -x $W/env/bin/nvcc ]; then
  echo "== MAMBA env $(date)"
  mamba create -y -p $W/env -c conda-forge \
    cuda-version=12.6 cuda-nvcc cuda-cudart-dev libcublas-dev cmake ninja
fi
source $W/llm-env.sh
which nvcc cmake ninja; nvcc --version | tail -2

# ---- build
echo "== BUILD $(date)"
cd $W
[ -d llama.cpp ] || git clone --depth 1 https://github.com/ggml-org/llama.cpp
cd llama.cpp
export CUDAToolkit_ROOT=$CONDA_PREFIX
cmake -B build -G Ninja -DGGML_CUDA=ON -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_CUDA_ARCHITECTURES=89 -DCMAKE_CUDA_HOST_COMPILER=/usr/bin/g++ \
  -DCMAKE_C_COMPILER=/usr/bin/gcc -DCMAKE_CXX_COMPILER=/usr/bin/g++ \
  -DLLAMA_CURL=OFF && \
cmake --build build -j 16 --target llama-server llama-cli llama-bench
echo "== BUILD rc=$? $(date)"
ls -la build/bin 2>/dev/null
echo "== SETUP SCRIPT DONE $(date)"
