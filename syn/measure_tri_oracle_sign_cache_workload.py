"""Replay sign-cache addresses on the same workload used for the port budget."""

import argparse
import json
from pathlib import Path
import re

import numpy as np

import measure_tri_oracle_packed_workload_traffic as traffic
from verify_tri_oracle_packed_down_weights import ROOT, sha256


WORDS_PER_PAIR = 2  # One 8-byte word for each of the gate and up branches.
GROUPS = traffic.CHANNELS // 32
PAIRS = traffic.HIDDEN // 2
ENTRIES = (64, 128, 256)
PREFILL_BATCH = 16


def read(path):
    return json.loads(path.read_text())


def requests(mask, bases):
    """Return word addresses in group, token, outlier pair, then branch order."""
    assert mask.ndim == 2 and mask.shape[1] == PAIRS
    assert all(base % 8 == 0 for base in bases) and abs(bases[1] - bases[0]) >= GROUPS * PAIRS * 8
    pairs = np.nonzero(mask)[1].astype(np.uint64)  # [active token-pair positions].
    offsets = np.arange(GROUPS, dtype=np.uint64) * PAIRS  # [groups].
    branches = np.array(bases, dtype=np.uint64) // 8  # [gate, up].
    return (offsets[:, None, None] + pairs[None, :, None] + branches[None, None, :]).reshape(-1)


def misses(words, entries):
    """Find misses from a cold direct-mapped cache with the RTL's XOR-folded index."""
    assert entries > 1 and entries & (entries - 1) == 0
    if not words.size:
        return words
    width = entries.bit_length() - 1
    folded = words.copy()
    for shift in range(width, 61, width):
        folded ^= words >> shift
    order = np.argsort(folded & (entries - 1), kind="stable")
    ordered = words[order]
    # In stable slot order, the immediately preceding request is the only
    # possible hit. Equal addresses always have equal slots.
    miss = np.empty(words.shape, dtype=bool)
    miss[order] = np.r_[True, ordered[1:] != ordered[:-1]]
    return words[miss]


def check_native_fixture(pins):
    record = ROOT / "records/wac_sign_cache_trained_masks_result.json"
    proof = read(record)
    assert proof["state"] == "trained_predictor_masks_and_exact_cached_sign_reads_verified"
    stage = ROOT / ".cache/physical/sign_word_cache_native/trained_masks"
    receipt, trace, expected = (stage / name for name in ("receipt.json", "native/xrun.log", "expected_addresses.hex"))
    bench = ROOT / "verilog/tri_oracle_sign_cache_trained_masks_tb.sv"
    native = read(receipt)
    norm = traffic.DATA / "batch403/norm.hex"
    cache = ROOT / "verilog/tri_oracle_sign_word_cache.sv"
    for path in (record, receipt, trace, expected, norm, bench, cache):
        key = str(path.relative_to(ROOT))
        digest = sha256(path)
        if path in (receipt, trace, expected, bench):
            assert digest == proof["evidence_sha256"][key], path
        if path in (norm, cache):
            assert digest == native["input_sha256"][key], path
        pins[key] = digest
    counts = proof["counted"]
    marker = f"logical={counts['logical']} external={counts['external']} cycles={counts['cycles']}"
    log = trace.read_text()
    assert log.count(marker) == log.count("Simulation complete via $finish(1)") == 1
    bases = tuple(int(re.search(rf"\b{branch}_BASE = 64'h([0-9a-fA-F]+)", bench.read_text())[1], 16)
                  for branch in ("GATE", "UP"))
    signed_norm = np.array([int(word, 16) for word in norm.read_text().split()], dtype=np.uint16).view(np.int16)
    tokens = proof["trained_tokens"]
    mask = (np.abs(signed_norm.astype(np.int32)) > 768).reshape(tokens, PAIRS, 2).any(axis=2)
    words = requests(mask, bases)
    observed = misses(words, entries=64) * 8
    addresses = np.array([int(address, 16) for address in expected.read_text().split()], dtype=np.uint64)
    assert words.size == counts["logical"] and observed.size == counts["external"]
    assert np.array_equal(observed, addresses), "Native cache miss order changed"
    return bases, counts["logical"], counts["external"]


def run(output):
    budget = ROOT / "records/wac_weight_burst_schedule_result.json"
    budget_data = read(budget)
    prior = traffic.DATA / "packed_workload_traffic_v1/packed_traffic.json"
    pinned = (budget, prior, Path(__file__).resolve(), Path(traffic.__file__).resolve())
    pins = {str(path.relative_to(ROOT)): sha256(path) for path in pinned}
    assert pins[str(prior.relative_to(ROOT))] == budget_data["evidence_sha256"][str(prior.relative_to(ROOT))]
    fixture_bases, fixture_logical, fixture_external = check_native_fixture(pins)
    layouts = {"trained_fixture": fixture_bases, "aligned_example": (0x10000000, 0x20000000)}
    counts = {name: {"frames": 0, "logical": 0, "ideal_distinct": 0,
                     "external": {size: {layout: 0 for layout in layouts} for size in ENTRIES}}
              for name in ("prefill", "decode")}
    original = traffic.reconstruct

    def capture(reference, activation, stats):
        result = original(reference, activation, stats)
        norms = stats["norm_codes"]  # [token rows, hidden], signed normalized inputs from the integer policy.
        rows = len(norms)
        active = (norms.abs() > 768).reshape(rows, PAIRS, 2).any(dim=2).cpu().numpy()  # [rows, outlier pairs].
        phase = counts["decode" if rows == 1 else "prefill"]
        logical = 0
        for first in range(0, rows, PREFILL_BATCH):
            mask = active[first:first + PREFILL_BATCH]  # [frame rows, outlier pairs].
            frame_logical = int(mask.sum()) * GROUPS * WORDS_PER_PAIR
            logical += frame_logical
            phase["frames"] += 1
            phase["ideal_distinct"] += int(mask.any(axis=0).sum()) * GROUPS * WORDS_PER_PAIR
            for layout, bases in layouts.items():
                words = requests(mask, bases) if rows > 1 else None
                for size in ENTRIES:
                    # A one-token frame requests each address at most once.
                    phase["external"][size][layout] += frame_logical if words is None else misses(words, size).size
        phase["logical"] += logical
        assert logical * 8 == result[-1]
        return result

    output.mkdir()
    traffic.reconstruct = capture
    try:
        traffic.run(output / "replay")
    finally:
        traffic.reconstruct = original
    observed_path = output / "replay/packed_traffic.json"
    observed, archived = read(observed_path), read(prior)
    for key in ("prefill_tokens", "decode_steps", "prefill_by_batch_size", "decode", "layers"):
        assert observed[key] == archived[key], key
    assert counts["prefill"]["frames"] == budget_data["phases"]["prefill"]["batches"]
    assert counts["decode"]["frames"] == budget_data["phases"]["decode"]["batches"]
    logical = sum(phase["logical"] for phase in counts.values())
    assert logical == budget_data["uncached_narrow_sign_response_beats"]
    minimum_reduction = budget_data["minimum_uncached_sign_responses_to_avoid_if_weights_unchanged"]
    summary = {}
    for entries in ENTRIES:
        summary[entries] = {}
        for layout in layouts:
            external = sum(phase["external"][entries][layout] for phase in counts.values())
            assert sum(phase["ideal_distinct"] for phase in counts.values()) <= external <= logical
            summary[entries][layout] = {"external": external, "saved": logical - external,
                                        "meets_primary_payload_budget": logical - external >= minimum_reduction}
    assert all(sha256(ROOT / name) == digest for name, digest in pins.items())
    pins[str(observed_path.relative_to(ROOT))] = sha256(observed_path)
    result = {
        "state": "normalized_sign_cache_requests_modeled_with_native_address_control",
        "native_control": {"logical": fixture_logical, "external": fixture_external, "ordered_misses_match": True},
        "layouts_byte_addresses": layouts, "phases": counts, "summary": summary,
        "minimum_sign_responses_to_avoid": minimum_reduction,
        "ideal_command_local_responses_avoided": logical - sum(phase["ideal_distinct"] for phase in counts.values()),
        "peak_gpu_bytes": observed["peak_gpu_bytes"],
        "scope": "One archived workload with contiguous 16-row prefill frames and one-row decode frames. "
                 "The cache starts cold on each frame. The 64-entry model follows the current RTL. Larger entry counts "
                 "are modeled with the same address-folding rule. The primary payload budget excludes other traffic, "
                 "request gaps and computation.",
        "evidence_sha256": pins,
    }
    with (output / "receipt.json").open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(result["state"], summary, result["ideal_command_local_responses_avoided"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=lambda path: Path(path).resolve())
    run(parser.parse_args().output)
