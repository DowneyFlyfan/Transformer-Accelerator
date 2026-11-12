"""Measure weight-read demand from the archived 600/60 model trajectory."""

import argparse
from fractions import Fraction
import json
from pathlib import Path

from check_tri_oracle_paper300_gate import PAPER_RELATIVE, PAPER_SHA256
import run_tri_oracle_normalized_workload_trace as trace
import tri_oracle_integer_reference as integer
from verify_tri_oracle_packed_down_weights import ROOT, sha256


ARCHIVED = ROOT / ".cache/model_reference/normalized_workload_trace/receipt.json"
MODE = "compact_streaming_pruned"
HIDDEN, CHANNELS, WORD_BYTES = 2048, 5632, 8
GIB = 2**30


def nonzero_words(codes, features):
    """Count nonzero words in the local signed-byte activation [one token, feature]."""
    assert codes.shape == (1, features) and codes.dtype == trace.torch.int8
    words = codes.reshape(features // WORD_BYTES, WORD_BYTES)  # [feature word, byte]
    return int(words.ne(0).any(dim=1).sum())


def measure(output):
    """Observe one decode row at a time while the archived model runs unchanged."""
    output.mkdir()
    calls = [[] for _ in range(22)]
    original_install = trace.install_channel_scaling
    original_dot = integer._dot
    original_memory_check = trace.check_memory
    active_row = None
    observed_memory = {"minimum_host_available_bytes": None, "maximum_container_anonymous_bytes": 0}

    def memory_check(reserve):
        available = next(int(line.split()[1]) * 1024 for line in Path("/proc/meminfo").read_text().splitlines()
                         if line.startswith("MemAvailable:"))
        anonymous = next(int(line.split()[1]) for line in Path("/sys/fs/cgroup/memory.stat").read_text().splitlines()
                         if line.startswith("anon "))
        minimum = 16 * GIB if reserve >= 16 * GIB else 15 * GIB
        assert available >= minimum and anonymous < 2.5 * GIB, (available, anonymous)
        prior = observed_memory["minimum_host_available_bytes"]
        observed_memory["minimum_host_available_bytes"] = min(prior or available, available)
        observed_memory["maximum_container_anonymous_bytes"] = max(
            observed_memory["maximum_container_anonymous_bytes"], anonymous)

    def measured_dot(left, right):
        # left [tokens, input features], right [output rows, input features]
        # are the operands supplied by the existing integer reference.
        if active_row is not None and left.shape[1] == CHANNELS:
            assert right.shape == (HIDDEN, CHANNELS)
            assert "down_words" not in active_row
            active_row["down_words"] = nonzero_words(left, CHANNELS)
        return original_dot(left, right)

    def install(replacement, layer, weight, context):
        # weight [hidden outputs, intermediate channels] is the trained down matrix.
        scales = original_install(replacement, layer, weight, context)
        evaluate = replacement.reference.evaluate

        def measured_evaluation(activation, residual, **settings):
            # activation and residual [retained tokens, hidden features]
            # come from the existing feed-forward reference.
            nonlocal active_row
            if context["mode"] != MODE or replacement.decoder.prefill_active:
                return evaluate(activation, residual, **settings)
            assert settings["prune"] and active_row is None
            assert activation.shape == residual.shape == (1, HIDDEN)
            codes, _ = integer._quantize(activation, per_row=True)  # [one token, hidden features]
            row = {
                "position": int(replacement.decoder.positions[0]),
                "gate_up_words": nonzero_words(codes, HIDDEN),
            }
            active_row = row
            try:
                result = evaluate(activation, residual, **settings)
            finally:
                active_row = None
            assert "down_words" in row
            skipped = result[2]["skip_count"]  # [one token], from the unchanged predicate.
            assert skipped.shape == (1,)
            row["retained_channels"] = CHANNELS - int(skipped[0])
            assert 0 <= row["retained_channels"] <= CHANNELS
            calls[layer].append(row)
            return result

        replacement.reference.evaluate = measured_evaluation
        return scales

    trace.install_channel_scaling = install
    trace.check_memory = memory_check
    integer._dot = measured_dot
    try:
        trace.run(output)
    finally:
        trace.install_channel_scaling = original_install
        trace.check_memory = original_memory_check
        integer._dot = original_dot
    return calls, observed_memory


def summarize(output, rows, memory):
    old = json.loads(ARCHIVED.read_text())
    rerun = output / "receipt.json"
    observed = json.loads(rerun.read_text())
    for key in ("state", "checkpoint_revision", "prefill_tokens", "decode_steps", "forced_tokens", "channels", "layers"):
        assert old[key] == observed[key], key
    prior_path = ROOT / "records/wac_decode_bandwidth_lower_bound.json"
    prior = json.loads(prior_path.read_text())
    assert sha256(ARCHIVED) == prior["evidence_sha256"][str(ARCHIVED.relative_to(ROOT))]
    source_inventory = ROOT / "records/wac_unified_chip_inventory_result.json"
    inventory = json.loads(source_inventory.read_text())
    assert inventory["state"] == "unified_chip_source_inventory_verified_and_synthesis_cut_widths_checked"
    assert inventory["compiled_bytes"] == prior["optimistic_weight_reuse_bytes_per_step"]
    interface = ROOT / ".cache/physical/wide_weight_loader/unified_decoder/boundary.sv"
    interface_path = ROOT / "records/wac_unified_decoder_read_result.json"
    interface_proof = json.loads(interface_path.read_text())
    assert interface_proof["evidence_sha256"][str(interface.relative_to(ROOT))] == sha256(interface)
    interface_text = interface.read_text()
    assert "wire [63:0] narrow_rsp_data;" in interface_text and "input [511:0] rsp_data;" in interface_text
    frame = ROOT / ".cache/physical/wide_weight_loader/packed_decoder/tri_oracle_batched_frame393.sv"
    assert "PACKED_DOWN_WEIGHTS && !attention_selected && state==DOWN_LAUNCH" in frame.read_text()
    targets = ROOT / "records/paper_result_targets.json"
    paper = ROOT / PAPER_RELATIVE
    assert sha256(paper) == PAPER_SHA256
    latency = json.loads(targets.read_text())["system_latency"]
    assert (latency["prefill_tokens"], latency["decode_tokens"]) == (old["prefill_tokens"], old["decode_steps"])

    layers = old["layers"][MODE]
    assert len(rows) == len(layers) == 22
    totals = {"gate_up_responses": 0, "down_responses": 0}
    for layer, (entries, archived) in enumerate(zip(rows, layers, strict=True)):
        assert archived["layer"] == layer and len(entries) == old["decode_steps"]
        assert [row["position"] for row in entries] == list(
            range(old["prefill_tokens"], old["prefill_tokens"] + old["decode_steps"]))
        assert sum(row["retained_channels"] for row in entries) == CHANNELS * len(entries) - archived["decode_skipped"]
        for row in entries:
            # Paired gate/up each load one eight-byte word per retained row.
            # Down loads one packed response per group of eight output rows.
            totals["gate_up_responses"] += 2 * row["retained_channels"] * row["gate_up_words"]
            totals["down_responses"] += (HIDDEN // 8) * row["down_words"]
    raw = output / "per_token_reads.json"
    raw.write_text(json.dumps(rows, separators=(",", ":")) + "\n")
    gate_up = totals["gate_up_responses"]
    down = totals["down_responses"]
    narrow_bytes, wide_bytes = WORD_BYTES, 8 * WORD_BYTES
    reuse = old["decode_steps"] * inventory["compiled_bytes"]
    assert reuse % narrow_bytes == 0
    clock = latency["clock_megahertz"] * 10**6
    budget = latency["milliseconds"]
    # Spend all hypothetical cache capacity on the slowest weights first.
    # This gives the current shared port the most optimistic cycle reduction.
    floor_cycles = max(0, gate_up + down - reuse // narrow_bytes)
    all_wide_cycles = Fraction(max(0, gate_up * narrow_bytes + down * wide_bytes - reuse), wide_bytes)
    floor_ms = Fraction(1000 * floor_cycles, clock)
    assert floor_ms > budget
    files = (ARCHIVED, rerun, raw, prior_path, source_inventory, interface, interface_path, frame,
             targets, paper, Path(trace.__file__).resolve(), Path(integer.__file__).resolve(), Path(__file__))
    result = {
        "state": "measured_local_decode_weight_demand_exceeds_paper_latency_budget",
        "archived_work_counts_exact": True,
        "trace_memory": memory,
        "layers": len(layers), "decode_steps": old["decode_steps"], "prefill_tokens": old["prefill_tokens"],
        "assumed_clock_megahertz": latency["clock_megahertz"], "paper_latency_ms": budget,
        "logical_responses_before_optimistic_reuse": totals,
        "gate_up_weight_bytes": gate_up * narrow_bytes, "down_weight_bytes": down * wide_bytes,
        "optimistic_cache_reuse_bytes": reuse, "current_shared_port_minimum_decode_weight_cycles": floor_cycles,
        "current_shared_port_minimum_decode_weight_ms": float(floor_ms),
        "ideal_all_wide_minimum_decode_weight_ms": float(1000 * all_wide_cycles / clock),
        "scope": "Quantized activation and pruning observations on the archived software trajectory. "
                 "The read floors assume one accepted response per clock, exclude prefill and other operations, "
                 "and use the local uncompressed layouts.",
        "evidence_sha256": {str(path.relative_to(ROOT)): sha256(path) for path in files},
    }
    (output / "read_budget.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f'DECODE_READ_BUDGET_PASS current_ms={float(floor_ms):.3f} '
          f'ideal_wide_ms={result["ideal_all_wide_minimum_decode_weight_ms"]:.3f}', flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    summarize(output, *measure(output))
