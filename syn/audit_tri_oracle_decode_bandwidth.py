"""Lower-bound traffic for the local signed-eight-bit decoder on its archived workload."""

import argparse
from fractions import Fraction
import json
from math import ceil
from pathlib import Path
import re

from check_tri_oracle_paper300_gate import PAPER_RELATIVE, PAPER_SHA256, sha

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text())


def audit():
    trace_path = ROOT / "records/normalized_workload_trace_result.json"
    trace = read(trace_path)
    assert trace["state"] == "normalized_workload_trace_independently_counted"
    for name, expected in trace["evidence_sha256"].items():
        assert sha(ROOT / name) == expected, name
    native_trace = ROOT / ".cache/model_reference/normalized_workload_trace/receipt.json"
    raw = read(native_trace)
    assert trace["checkpoint_revision"] == raw["checkpoint_revision"]
    mode = "compact_streaming_pruned"
    layers = raw["layers"][mode]
    totals = trace["totals"][mode]
    steps = trace["decode_steps"]
    channels = trace["channels_per_row"]
    model_path = ROOT / ".cache/model_reference/tiny_llava_v1/config.json"
    model = read(model_path)["text_config"]
    hidden = model["hidden_size"]
    assert trace["layers"] == len(layers) == model["num_hidden_layers"]
    assert channels == model["intermediate_size"]
    assert [row["layer"] for row in layers] == list(range(len(layers)))
    assert all(row["decode_rows"] == steps and 0 <= row["decode_skipped"] <= steps * channels for row in layers)
    active = sum(row["decode_rows"] * channels - row["decode_skipped"] for row in layers)
    assert active == totals["decode_rows"] * channels - totals["decode_skipped"]

    memory_path = ROOT / ".cache/physical/shared_memory_layer_boundary/physical_inputs/native_memory_partition_receipt.json"
    archived_memory = ROOT / "records/wac_shared_memory_layer_native_attention_result.json"
    memory = read(memory_path)
    assert read(archived_memory)["evidence_sha256"][str(memory_path.relative_to(ROOT))] == sha(memory_path)
    assert memory["state"] == "native_memory_inventory_verified" and memory["native_census_checked"] is True
    memory_bytes = memory["bytes"]
    assert memory_bytes == sum(item["instances"] * item["words"] * item["bits_per_word"] // 8
                               for item in memory["by_master"].values())
    assert memory_bytes == sum(memory["bytes_by_role"].values())

    physical = ROOT / ".cache/physical/context_external/shared_decoder"
    interface = physical / "boundary.sv"
    interface_proof = ROOT / "records/wac_shared_decoder_context_result.json"
    assert read(interface_proof)["evidence_sha256"][str(interface.relative_to(ROOT))] == sha(interface)
    ports = interface.read_text()
    most_significant_bit, = re.findall(r"(?m)^\s*input \[(\d+):0\] rsp_data;$", ports)
    assert re.search(r"(?m)^\s*input rsp_valid;$", ports) and re.search(r"(?m)^\s*output rsp_ready;$", ports)
    response_bits = int(most_significant_bit) + 1
    assert response_bits % 8 == 0

    paper = ROOT / PAPER_RELATIVE
    assert sha(paper) == PAPER_SHA256
    targets_path = ROOT / "records/paper_result_targets.json"
    targets = read(targets_path)
    assert targets["source"] == PAPER_RELATIVE
    latency = targets["system_latency"]
    assert latency["external_memory_access_included"] is True
    assert (trace["prefill_tokens"], steps) == (latency["prefill_tokens"], latency["decode_tokens"])
    assert targets["silicon"]["processing_element_precision"] == "signed INT8"
    clock_hz = latency["clock_megahertz"] * 10**6
    budget_seconds = Fraction(latency["milliseconds"], 1000)
    bytes_per_second = response_bits // 8 * clock_hz
    byte_budget = int(bytes_per_second * budget_seconds)

    # One distinct dense down-projection column per retained channel and layer.
    # Each column has one signed-eight-bit weight per hidden output. Even a
    # fully warmed, exclusively weight-filled SRAM can avoid at most one
    # capacity of external bytes per sequential decode step.
    logical_bytes = active * hidden
    lower_bound_bytes = max(0, logical_bytes - steps * memory_bytes)
    latency_floor = Fraction(lower_bound_bytes, bytes_per_second)
    required_bytes_per_second = Fraction(lower_bound_bytes, budget_seconds)
    return {
        "state": "local_decode_down_weight_bandwidth_lower_bound_exceeds_paper_latency_budget",
        "paper_latency_ms": latency["milliseconds"],
        "assumed_clock_mhz": latency["clock_megahertz"],
        "decode_steps": steps, "layers": len(layers), "active_channel_columns": active,
        "bytes_per_uncompressed_down_column": hidden,
        "logical_down_weight_bytes": logical_bytes,
        "optimistic_weight_reuse_bytes_per_step": memory_bytes,
        "minimum_external_read_bytes": lower_bound_bytes,
        "read_response_bits": response_bits, "peak_port_bytes_per_second": bytes_per_second,
        "maximum_port_bytes_in_paper_latency": byte_budget,
        "minimum_read_time_ms": float(1000 * latency_floor),
        "minimum_required_bytes_per_second": ceil(required_bytes_per_second),
        "minimum_equivalent_parallel_ports_at_clock": ceil(required_bytes_per_second / bytes_per_second),
        "scope": "Analytic lower bound for the local uncompressed weight layout and one archived pruning trace. "
                 "Only decode down-projection weights are counted. The hardware and paper system latencies remain unmeasured locally.",
        "evidence_sha256": {str(path.relative_to(ROOT)): sha(path) for path in (
            trace_path, native_trace, model_path, memory_path, archived_memory, interface,
            interface_proof, paper, targets_path, Path(__file__).resolve(),
        )},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = audit()
    assert result["minimum_external_read_bytes"] > result["maximum_port_bytes_in_paper_latency"]
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(result["state"], result["minimum_read_time_ms"], "ms", flush=True)
