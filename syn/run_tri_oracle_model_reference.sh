#!/usr/bin/env bash
# Uses the project environment; no complete model is materialized.
set -euo pipefail
export HF_HOME="$PWD/.cache/huggingface"
export TORCH_HOME="$PWD/.cache/torch"
export CUDA_CACHE_PATH="$PWD/.cache/cuda"
export HF_HUB_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 USE_HUB_KERNELS=NO
.venv/bin/python -B - <<'PY'
from importlib.metadata import version
from pathlib import Path
assert version('kernels')=='0.12.0', 'Use the project environment with kernels==0.12.0'
available=int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:')))*1024
if available<4*1024**3:raise RuntimeError('Insufficient host memory available for this reference stage')
PY
timeout 180 .venv/bin/python -B syn/tri_oracle_model_reference.py
