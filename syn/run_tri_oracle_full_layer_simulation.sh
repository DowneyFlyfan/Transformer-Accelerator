#!/usr/bin/env bash
# Run inside cadence-ddi. This exercises the complete first-layer feed-forward
# integer tensor through five hardware transactions; no model-accuracy claim.
set -euo pipefail
export TRI_ORACLE_MODEL_FIXTURE=${TRI_ORACLE_MODEL_FIXTURE:-.cache/model_reference/full_layer_fixture}
binary=.cache/tri_oracle_full_layer.vvp
trap 'rm -f "$binary"' EXIT
python3 -B syn/test_tri_oracle_model_reference.py
python3 -B - <<'PY_CHECK'
from pathlib import Path
import hashlib,json,os,re
folder=Path(os.environ['TRI_ORACLE_MODEL_FIXTURE'])
if not folder.resolve().is_relative_to(Path('.cache').resolve()):
    raise ValueError('Keep full-layer inputs in the project cache')
manifest=json.loads((folder/'manifest.json').read_text())
if not (manifest['hidden_features']==2048 and manifest['dense_intermediate_stride']==5632 and
        manifest['selected_channels']==list(range(5632)) and manifest['selected_groups']==list(range(176)) and
        manifest['output_start']==0 and manifest['output_count']==2048):
    raise ValueError('Full-layer input/output coverage is incomplete')
for name,digest in manifest['files'].items():
    if hashlib.sha256((folder/name).read_bytes()).hexdigest()!=digest:
        raise ValueError('Full-layer fixture checksum mismatch: '+name)
counts={'activation.hex':(2048,2),'norm.hex':(2048,4),'gate.hex':(5632*2048,2),
        'up.hex':(5632*2048,2),'down.hex':(2048*5632,2),'skip.hex':(5632,2),
        'expected.hex':(2048,8),'groups.hex':(176,4),'configuration.hex':(5,8)}
for name,(count,width) in counts.items():
    pattern=re.compile(rb'[0-9a-f]{'+str(width).encode()+rb'}\n')
    observed=0
    with (folder/name).open('rb') as stream:
        for line in stream:
            if not pattern.fullmatch(line):raise ValueError('Invalid hex input: '+name)
            observed+=1
    if observed!=count:raise ValueError('Incorrect element count: '+name)
print('TRI_ORACLE_FULL_LAYER_FIXTURE_VALIDATED',hashlib.sha256((folder/'manifest.json').read_bytes()).hexdigest(),flush=True)
PY_CHECK
iverilog -g2012 -s tri_oracle_full_layer_tb -o "$binary" \
    verilog/tri_oracle_full_layer_tb.sv \
    verilog/tri_oracle_feedforward_core.sv verilog/tri_oracle_down_executor.sv \
    verilog/tri_oracle_silu_gate.sv verilog/tri_oracle_gated_executor.sv \
    verilog/tri_oracle_predicted_core.sv verilog/tri_oracle_strip_predictor.sv \
    verilog/tri_oracle_channel_compactor.sv verilog/tri_oracle_predicted_dispatch.sv \
    verilog/tri_oracle_sparse_weight_dma.sv verilog/tri_oracle_tile_executor.sv \
    verilog/tri_oracle_pe_array.sv verilog/tri_oracle_word_bank.sv \
    verilog/tri_oracle_memory_compute.sv
timeout 10800 vvp "$binary" "+FIXTURE_DIR=$TRI_ORACLE_MODEL_FIXTURE"
