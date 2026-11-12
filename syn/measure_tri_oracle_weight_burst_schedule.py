"""Count fixed-layout weight bursts on the archived 600/60 workload replay."""

import argparse
from collections import Counter
import json
from pathlib import Path

import measure_tri_oracle_packed_workload_traffic as traffic
from verify_tri_oracle_packed_down_weights import ROOT, sha256


PACKED = 8
PARTITIONS = 4
BURST_LIMIT = 32
BEAT_BYTES = 64
PREFILL_BATCH = 16


def read(path):
    return json.loads(path.read_text())


def packed_masks(active, batch):
    """Convert active positions [rows, features] to masks [batches, words]."""
    rows, features = active.shape
    assert rows > 0 and features % PACKED == 0
    padded = traffic.trace.torch.nn.functional.pad(active, (0, 0, 0, (-rows) % batch))
    return padded.reshape(-1, batch, features // PACKED, PACKED).any(dim=3).any(dim=1).tolist()


def partition_runs(words):
    """Yield one burst histogram per core partition, splitting at tile boundaries."""
    assert words and len(words) % PARTITIONS == 0
    part_words = len(words) // PARTITIONS
    for part in range(0, len(words), part_words):
        lengths = Counter()
        for start in range(part, part + part_words, BURST_LIMIT):
            end = min(part + part_words, start + BURST_LIMIT)
            lengths.update(len(run) for run in bytes(words[start:end]).split(b"\0") if run)
        assert sum(length * count for length, count in lengths.items()) == sum(words[part:part + part_words])
        yield lengths


def lane_runs(words, kept_groups, groups_per_tile):
    """Assign clusters 0–1 and 3–4 exclusively and split cluster 2 by partition."""
    groups_per_cluster = groups_per_tile // 5
    positions = [sum(kept_groups[start::groups_per_tile]) for start in range(groups_per_tile)]
    low, middle = 2 * groups_per_cluster, 3 * groups_per_cluster
    exclusive = (sum(positions[:low]), sum(positions[middle:]))
    shared = sum(positions[low:middle])
    lanes = (Counter(), Counter())
    for part, histogram in enumerate(partition_runs(words)):
        for lane, result in enumerate(lanes):
            groups = exclusive[lane] + (shared if part // 2 == lane else 0)
            result.update({length: count * groups for length, count in histogram.items()})
    return tuple(+histogram for histogram in lanes)


def projection_histograms(activation, keep, down, batch):
    """Use [rows, hidden] activations and [rows, channels] keep/down masks."""
    for gate_mask, keep_mask, down_mask in zip(
        packed_masks(activation.ne(0), batch), packed_masks(keep, batch),
        packed_masks(down.ne(0), batch), strict=True,
    ):
        gate = lane_runs(gate_mask, keep_mask, groups_per_tile=80 // PACKED)
        down = lane_runs(down_mask, [True] * (traffic.HIDDEN // PACKED), groups_per_tile=160 // PACKED)
        yield tuple(item + item for item in gate), down


def reuse_bound(histogram, capacity_beats):
    """Give each batch the full cache and eliminate the shortest bursts first."""
    available = capacity_beats
    removed = 0
    for length, count in sorted(histogram.items()):
        take = min(count, available // length)
        available -= take * length
        removed += take
    payload = sum(length * count for length, count in histogram.items())
    return max(0, payload - capacity_beats), sum(histogram.values()) - removed


def run(output):
    budget_path = ROOT / "records/wac_dual_lane_burst_budget_result.json"
    budget = read(budget_path)
    for name, expected in budget["evidence_sha256"].items():
        assert sha256(ROOT / name) == expected, name
    assert budget["native_burst_probe"]["max_beats"] == BURST_LIMIT
    prior_path = traffic.DATA / "packed_workload_traffic_v1/packed_traffic.json"
    prior = read(prior_path)
    prior_record_path = ROOT / "records/wac_packed_workload_traffic_result.json"
    assert sha256(prior_path) == read(prior_record_path)["evidence_sha256"][str(prior_path.relative_to(ROOT))]
    capacity_path = ROOT / "records/wac_assembled_context_chip_structure_result.json"
    capacity = read(capacity_path)["structure"]["memory"]["compiled_bytes"]
    control_path = ROOT / "records/wac_packed_trained_weight_traffic_result.json"
    control = read(control_path)
    chip = ROOT / ".cache/physical/wide_weight_loader/parallel_chip_v3"
    control_replay_path = chip / "full_native_retry/trained_receipt.json"
    control_replay = read(control_replay_path)
    assert control_replay["native"]["native_exit_status"] == 0
    assert control_replay["counters"]["exact_outputs"] == 32768
    control_log = chip / "full_native_retry/trained/xrun.log"
    assert sha256(control_log) == control_replay["native"]["log_sha256"]
    assert "BATCH408_SHARED_BUS sign_requests=55616" in control_log.read_text()
    loader_path = ROOT / "verilog/tri_oracle_parallel_weight_loader.sv"
    mux_path = ROOT / "verilog/tri_oracle_packed_read_mux.sv"
    boundary_path = chip / "boundary.sv"
    tensor_path = chip / "tri_oracle_batched_tensor390.sv"
    frame_path = chip / "tri_oracle_batched_frame393.sv"
    sign_path = ROOT / "verilog/tri_oracle_sign_fetch.sv"
    prepared = read(chip / "prepared.json")
    for path in (loader_path, mux_path, boundary_path, tensor_path, frame_path, sign_path):
        assert sha256(path) == prepared["input_sha256"][str(path.relative_to(ROOT))], path
    assert "gate_count=gate_final ? 7'(remaining_intermediate) : 7'd80" in frame_path.read_text()
    assert "down_count=down_final ? 8'(remaining_outputs) : 8'd160" in frame_path.read_text()
    assert ".rsp_valid({aux_rsp_valid,wide_rsp_valid})" in tensor_path.read_text()
    assert ".mem_rsp_valid(rsp_valid), .mem_rsp_ready(rsp_ready)" in boundary_path.read_text()
    assert "assign narrow_rsp_valid = active && !owner && mem_rsp_valid;" in mux_path.read_text()
    assert "assign wide_rsp_valid = active && owner && mem_rsp_valid;" in mux_path.read_text()
    assert "req_length = 5'd1;" in sign_path.read_text()
    handoff_path = ROOT / "records/wac_weight_handoff_mapped_result.json"
    handoff = read(handoff_path)
    assert handoff["state"] == "mapped_dual_lane_weight_handoff_verified"
    assert handoff["candidate"]["dense_parallel"]["gap"] == 1
    evidence = (budget_path, prior_path, prior_record_path, capacity_path, control_path, control_replay_path,
                control_log, chip / "prepared.json", handoff_path, loader_path, mux_path, boundary_path, tensor_path, frame_path,
                sign_path, Path(__file__).resolve(), Path(traffic.__file__).resolve())
    pins = {str(path.relative_to(ROOT)): sha256(path) for path in evidence}
    phases = {name: {"gate_up": Counter(), "down": Counter(), "batches": 0, "lane_payload_beats": [0, 0],
                     "minimum_beats": 0, "minimum_bursts": 0, "minimum_primary_weight_beats": 0}
              for name in ("prefill", "decode")}
    control_checked = False
    original = traffic.group_traffic

    def capture(activation, keep, dense_down, pruned_down, size):
        nonlocal control_checked
        totals = original(activation, keep, dense_down, pruned_down, size)
        if size != PREFILL_BATCH and (size != 1 or len(activation) != 1):
            return totals
        phase = phases["prefill" if size == PREFILL_BATCH else "decode"]
        gate_beats = down_beats = 0
        for gate_lanes, down_lanes in projection_histograms(activation, keep, pruned_down, size):
            gate, down = sum(gate_lanes, Counter()), sum(down_lanes, Counter())
            gate_beats += sum(length * count for length, count in gate.items())
            down_beats += sum(length * count for length, count in down.items())
            lane_beats = [sum(length * count for length, count in (lane_gate + lane_down).items())
                          for lane_gate, lane_down in zip(gate_lanes, down_lanes, strict=True)]
            if activation.device.type == "cpu":
                assert not control_checked and size == PREFILL_BATCH and len(activation) == 16
                assert gate_beats == control["packed_beats"]["gate"] + control["packed_beats"]["up"]
                assert down_beats == control["packed_beats"]["down"]
                assert set(gate) == {32} and set(down) == {16, 32}
                for lane, known in enumerate(control_replay["responses_by_lane"]):
                    assert sum(length * count for length, count in gate_lanes[lane].items()) == known["gate"] + known["up"]
                    assert sum(length * count for length, count in down_lanes[lane].items()) == known["down"]
                control_checked = True
                continue
            phase["gate_up"].update(gate)
            phase["down"].update(down)
            reuse_beats = capacity // BEAT_BYTES
            beats, bursts = reuse_bound(gate + down, reuse_beats)
            phase["minimum_beats"] += beats
            phase["minimum_bursts"] += bursts
            for lane, payload in enumerate(lane_beats):
                phase["lane_payload_beats"][lane] += payload
            phase["minimum_primary_weight_beats"] += max(0, lane_beats[0] - reuse_beats)
            phase["batches"] += 1
        assert gate_beats * BEAT_BYTES == totals["predictor_gate_up_bytes"]
        assert down_beats * BEAT_BYTES == totals["predictor_down_bytes"]
        return totals

    output.mkdir()
    traffic.group_traffic = capture
    try:
        traffic.run(output / "replay")
    finally:
        traffic.group_traffic = original
    assert control_checked
    observed_path = output / "replay/packed_traffic.json"
    observed = read(observed_path)
    for key in ("prefill_tokens", "decode_steps", "prefill_by_batch_size", "decode", "layers"):
        assert observed[key] == prior[key], key
    assert phases["decode"]["batches"] == observed["decode_steps"] * len(observed["layers"])
    assert sum(phase["batches"] for phase in phases.values()) * capacity == budget["optimistic_reuse_bytes"]
    beats = sum(phase["minimum_beats"] for phase in phases.values())
    bursts = sum(phase["minimum_bursts"] for phase in phases.values())
    # Each lane can accept one beat per cycle and spends at least one request
    # cycle between bursts. Grant each lane its initial request for free.
    cycles = (beats + max(0, bursts - 2) + 1) // 2
    clock_mhz = budget["clock_megahertz"]
    # The uncached sign fetch issues one narrow beat per sign word. Its
    # responses and lane-zero weight responses share the primary data port.
    signs = observed["prefill_by_batch_size"][str(PREFILL_BATCH)]["sign_bytes"] + observed["decode"]["sign_bytes"]
    assert signs % 8 == 0
    primary_weight = sum(phase["minimum_primary_weight_beats"] for phase in phases.values())
    primary_payload = primary_weight + signs // 8
    assert all(sha256(ROOT / name) == digest for name, digest in pins.items())
    pins[str(observed_path.relative_to(ROOT))] = sha256(observed_path)
    result = {
        "state": "normalized_weight_bursts_reconstructed_from_fixed_layout",
        "phases": phases,
        "minimum_payload_beats_after_optimistic_reuse": beats,
        "minimum_bursts_after_optimistic_reuse": bursts,
        "minimum_dual_lane_transfer_cycles": cycles,
        "minimum_weight_transfer_ms_at_paper_clock": cycles / (1000 * clock_mhz),
        "minimum_primary_weight_beats_after_optimistic_reuse": primary_weight,
        "uncached_narrow_sign_response_beats": signs // 8,
        "minimum_primary_weight_and_uncached_sign_payload_ms": primary_payload / (1000 * clock_mhz),
        "primary_payload_exceeds_paper_cycle_budget": primary_payload > budget["paper_latency_cycle_budget"],
        "peak_gpu_bytes": observed["peak_gpu_bytes"],
        "paper_latency_ms": budget["paper_latency_ms"],
        "scope": "Modeled fixed-layout requests from the archived integer replay. The weight-only bound assumes "
                 "perfectly balanced lanes. The primary-port payload bound uses fixed lane assignment and uncached "
                 "sign requests. Both grant the entire compiled memory to weight reuse in every batch. "
                 "Whole-chip latency remains unmeasured.",
        "evidence_sha256": pins,
    }
    with (output / "receipt.json").open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(result["state"], cycles, result["minimum_weight_transfer_ms_at_paper_clock"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=lambda path: Path(path).resolve())
    run(parser.parse_args().output)
