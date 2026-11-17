#!/usr/bin/env bash
set -euo pipefail

repo=$(cd -- "$(dirname -- "$0")/.." && pwd)
experiment="$repo/.cache/phase_chip"
if [[ ${BUFFERED_PHASE_CHIP:-0} == 1 ]]; then
  experiment="$repo/.cache/phase_chip_buffered"
fi
if [[ ${DERIVED_PHASE_CLOCK:-0} == 1 ]]; then
  experiment="$repo/.cache/phase_chip_clock"
fi
if [[ ${ACTIVATION_BROADCAST:-0} == 1 ]]; then
  experiment="$repo/.cache/phase_chip_activation"
fi
if [[ ${ACTIVATION_PREFETCH:-0} == 1 ]]; then
  experiment="$repo/.cache/phase_chip_prefetch"
fi
source_dir="$experiment/source"
name="${1:?run name is required}"
shift
case "$name" in (*[!a-zA-Z0-9_-]*|source) exit 2;; esac
work="$experiment/$name"
mkdir -p "$work"
top=tri_oracle_batched406_learned_tb
bench="$source_dir/bench.sv"
duration=240
intermediate="${PHASE_CHIP_INTERMEDIATE:-256}"
[[ "$intermediate" =~ ^[0-9]+$ ]]
arguments=(-defparam "$top.INTERMEDIATE=$intermediate")
if [[ "$name" == scalar ]]; then
  bench="$source_dir/scalar_bench.sv"
  arguments+=(-defparam "$top.PACKED=0")
fi
if [[ "$name" == trained ]]; then
  duration=14400
  bench="$source_dir/trained_bench.sv"
  fixtures="$repo/.cache/model_reference"
  arguments=(
    -defparam "$top.INTERMEDIATE=5632" -defparam "$top.HIDDEN=2048"
    -defparam "$top.OUTPUTS=2048" -defparam "$top.TOKENS=16" -defparam "$top.TRAINED=1"
    "+SIGN_READS=$repo/.cache/physical/ranked_sign_slots/banked_observation_32/miss_addresses.hex"
    "+PACKED_IMAGE=$fixtures/packed_down_export/v1/weights.bin"
    "+PAIR_IMAGE=$fixtures/packed_gate_up_export/v1/weights.bin"
    "+FIXTURE=$fixtures/batch389" "+RAW_FIXTURE=$fixtures/batch396"
    "+LEARNED_FIXTURE=$fixtures/batch403" "+INTERMEDIATE_FIXTURE=$fixtures/batch407"
  )
fi
if [[ "$name" == prefetch_fault ]]; then
  [[ ${ACTIVATION_PREFETCH:-0} == 1 ]]
  bench="$source_dir/prefetch_fault_bench.sv"
  arguments+=(-defparam "$top.FAULT=17" -defparam "$top.HIDDEN=1152")
fi
progress=(+PROGRESS=progress.log)
if [[ "$name" == attention ]]; then
  duration=2700
  bench="$source_dir/attention_bench.sv"
  top=tri_oracle_attention430_tb
  arguments=(-defparam "$top.INTEGRATE=1" "+FIXTURE=$repo/.cache/physical/shared437/fixture" +DUMP=attention.hex)
  progress=()
fi
run_replay() {
  local rc=0
  docker exec -w "$work" tri-oracle-eda timeout -k 5 "$duration" prlimit --as=5368709120 -- \
    /opt/cadence/bin/xrun -64bit -sv -sequdp_nba_delay -xmerror RECOME -top "$top" -log xrun.log \
    "${arguments[@]}" "$source_dir/bundle.sv" "$bench" \
    "$repo/verilog/tri_oracle_phase_chip_probe.sv" \
    "${progress[@]}" "$@" >"$work/console.log" 2>&1 || rc="$?"
  printf '%s\n' "$rc" >"$work/exit_status"
  rg '^(BATCH408_PASS|PACKED_DECODER_PASS|PHASE_CHIP|CHIP_ACTIVATION_PREFETCH)|\*[EF],' "$work/xrun.log" | head -18 || true
  return "$rc"
}
run_replay "$@"
