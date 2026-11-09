#!/usr/bin/env bash
# Run inside cadence-ddi; source fixture requires independently verified weights.
set -euo pipefail
export TRI_ORACLE_MODEL_FIXTURE=${TRI_ORACLE_MODEL_FIXTURE:-.cache/model_reference/feedforward_fixture}
binary=.cache/tri_oracle_model_feedforward.vvp
trap 'rm -f "$binary"' EXIT
python3 -B syn/test_tri_oracle_model_reference.py
python3 -B - <<'PY_CHECK'
from pathlib import Path
import hashlib,json,os
folder=Path(os.environ['TRI_ORACLE_MODEL_FIXTURE'])
manifest=json.loads((folder/'manifest.json').read_text())
for name, expected in manifest['files'].items():
    if hashlib.sha256((folder/name).read_bytes()).hexdigest()!=expected:
        raise ValueError('Model fixture checksum mismatch: '+name)
PY_CHECK
iverilog -g2012 -s tri_oracle_model_feedforward_tb -o "$binary" \
    verilog/tri_oracle_model_feedforward_tb.sv \
    verilog/tri_oracle_feedforward_core.sv verilog/tri_oracle_down_executor.sv \
    verilog/tri_oracle_silu_gate.sv verilog/tri_oracle_gated_executor.sv \
    verilog/tri_oracle_predicted_core.sv verilog/tri_oracle_strip_predictor.sv \
    verilog/tri_oracle_channel_compactor.sv verilog/tri_oracle_predicted_dispatch.sv \
    verilog/tri_oracle_sparse_weight_dma.sv verilog/tri_oracle_tile_executor.sv \
    verilog/tri_oracle_pe_array.sv verilog/tri_oracle_word_bank.sv \
    verilog/tri_oracle_memory_compute.sv
timeout 240 vvp "$binary" "+FIXTURE_DIR=$TRI_ORACLE_MODEL_FIXTURE"
