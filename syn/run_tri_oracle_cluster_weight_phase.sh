#!/usr/bin/env bash
set -euo pipefail

repo=$(cd -- "$(dirname -- "$0")/.." && pwd)
physical="$repo/.cache/physical"
memory="$physical/sram"
core="$physical/wac_core_local_outlier_v2"
overlap="$memory/dual_port_weight_probe_01/core_overlap"
fixtures="$repo/.cache/compiled_cluster_weight_overlap/reference"
data="$repo/.cache/model_reference/lossless_weight_burst_probe/streaming_probe/aligned/partial_retention/indexed_down"
indexed="$repo/.cache/indexed_whole_chip/dual_group_probe/controller"
transport="$repo/.cache/overlapped_weight_write/source"
rtl="$repo/verilog"
corner="${1:?memory model corner is required}"
name="${2:?run name is required}"
shift 2
case "$name$corner" in (*[!a-zA-Z0-9_-]*) exit 2;; esac
here="$repo/.cache/cluster_weight_phase/$name"
setup_options=()
address_space=4294967296
phase_fabric=("$rtl/tri_oracle_weight_phase_fabric.sv")
if [[ ${ALL_CLUSTERS:-0} == 1 ]]; then
  setup_options+=(--all-clusters)
  fixtures="$repo/.cache/cluster_weight_phase/five_cluster_reference"
  address_space=6442450944
fi
if [[ ${MAPPED_FABRIC:-0} == 1 ]]; then
  [[ ${ALL_CLUSTERS:-0} == 1 ]]
  setup_options+=(--mapped-fabric)
  phase_fabric=("$repo/.cache/cluster_weight_phase/fabric_mapping/mapped.v"
                "$physical/library/tcbn28hpcplusbwp12t40p140.v"
                "$here/mapped_fabric_adapter.sv")
fi
weight="$memory/core_weights_masks_01/ts5n28hpcpsvta32x128m2fw_130a/VERILOG/ts5n28hpcpsvta32x128m2fw_130a_$corner.v"
activation="$memory/activation_cache_banks_01/ts5n28hpcpsvta512x64m4f_130a/VERILOG/ts5n28hpcpsvta512x64m4f_130a_$corner.v"
result="$memory/core_outputs_01/ts6n28hpcpsvta16x128m2f_130a/VERILOG/ts6n28hpcpsvta16x128m2f_130a_$corner.v"

# Source preparation runs on the host. Cadence and vendor simulation models run
# together in the project's existing container.
python3 -B "$repo/syn/prepare_tri_oracle_cluster_weight_phase.py" \
  "$core/tri_oracle_sram_memory_compute.sv" "$overlap/cluster_candidate.sv" "$weight" "$here" "${setup_options[@]}"
ln -sfn -t "$here" "$fixtures/"*.hex "$data/down_index.bin" "$data/down_payload.bin"
rc=0
docker exec -w "$here" tri-oracle-eda timeout -k 5 180 prlimit --as="$address_space" -- \
  /opt/cadence/bin/xrun -64bit -sv -define UNIT_DELAY -sequdp_nba_delay \
  -xmerror RECOME -l xrun.log -top tri_oracle_compiled_cluster_weight_overlap_tb \
  "$weight" "$activation" "$result" "$here/weight_timed.v" \
  "$core/wac_softmax_types.sv" "$core/tri_oracle_wac_softmax.sv" \
  "$physical/shared437/local_token_size_integrated/portable/tri_oracle_cluster_token_sizes_with_layer_ports.sv" \
  "$physical/shared437/aggregator_local_merge/layer/rtl/tri_oracle_local_merge_fabric.sv" \
  "$physical/whole_chip_xcelium_speed/booth_multiplier/sparse_reduce_trial/array/array.sv" \
  "$rtl/tri_oracle_wac_outlier_sign.sv" "$rtl/tri_oracle_wac_imem_owner.sv" "$rtl/tri_oracle_wac_softmax_imem.sv" \
  "$here/core.sv" "$here/cluster.sv" \
  "$rtl/tri_oracle_weight_phase_clock.sv" "$rtl/tri_oracle_weight_phase_port.sv" \
  "$rtl/tri_oracle_cluster_weight_phase.sv" "${phase_fabric[@]}" \
  "$rtl/weight_stream_write_arbiter.sv" "$rtl/tri_oracle_weight_write_buffer.sv" \
  "$rtl/tri_oracle_packed_weight_schedule.sv" "$rtl/tri_oracle_paired_weight_schedule.sv" \
  "$rtl/tri_oracle_wide_weight_loader.sv" "$rtl/weight_decode_flush.sv" \
  "$rtl/tri_oracle_projection_weight_reuse.sv" "$rtl/tri_oracle_batched_projection356.sv" \
  "$data/weight_stream_schedule.sv" "$indexed/wide.sv" "$indexed/wide_lane.sv" "$indexed/wide_loader.sv" \
  "$transport/tri_oracle_backpressured_raw_weight_loader.sv" "$transport/tri_oracle_backpressured_weight_transport.sv" \
  "$here/bench.sv" "$@" >"$here/console.log" 2>&1 || rc="$?"
printf '%s\n' "$rc" >"$here/exit_status"
rg '^(COMPILED_CLUSTER_WEIGHT|CLUSTER_WEIGHT|Warning!  Timing violation)|\*[EF],' "$here/xrun.log" | head -18 || true
exit "$rc"
