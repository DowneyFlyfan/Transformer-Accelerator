#!/usr/bin/env python3
"""Prepare small, synthetic, exact-rational context-spool component vectors.

Only Python's standard library is used.  Nothing imports the RTL's arithmetic
implementation or the attention producer.  Generated files belong under .cache.
The consumer of these vectors must still execute the complete hardware protocol.
"""
from __future__ import annotations

import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import random

HEADS, LANES, DENOMINATOR = 32, 64, 65535
HEADER_WORDS = 7
UNIT_OFFSET = HEADER_WORDS
WEIGHT_OFFSET = UNIT_OFFSET + HEADS
OUTPUT_OFFSET = WEIGHT_OFFSET + HEADS
ORDER_OFFSET = OUTPUT_OFFSET + HEADS
DATA_OFFSET = ORDER_OFFSET + HEADS
CODE_OFFSET = DATA_OFFSET + HEADS * LANES
STRIDE = CODE_OFFSET + HEADS * LANES


def dyadic(exponent: int) -> Fraction:
    return Fraction(1 << exponent) if exponent >= 0 else Fraction(1, 1 << -exponent)


def round_away(value: Fraction) -> int:
    sign = -1 if value < 0 else 1
    magnitude = abs(value)
    quotient, remainder = divmod(magnitude.numerator, magnitude.denominator)
    return sign * (quotient + int(2 * remainder >= magnitude.denominator))


def context_reference(data: list[list[int]], units: list[int],
                      weights: list[int], outputs: list[int]) -> tuple[int, list[int]]:
    """Select the unrounded common unit, then round each physical rational once."""
    if len(data) != HEADS or any(len(row) != LANES for row in data):
        raise ValueError("exactly 32 heads of 64 signed32 lanes required")
    if any(len(vector) != HEADS for vector in (units, weights, outputs)):
        raise ValueError("exactly 32 unit entries required")
    if any(type(x) is not int or not -256 <= x <= 255
           for vector in (units, weights, outputs) for x in vector):
        raise ValueError("signed9 unit required")
    if any(type(x) is not int or not -(1 << 31) <= x < (1 << 31)
           for row in data for x in row):
        raise ValueError("signed32 context required")
    peaks = [max(abs(value) for value in row) for row in data]
    candidates = []
    for peak, unit in zip(peaks, units):
        if peak:
            candidates.append(next(unit + power for power in range(-22, 10)
                                   if Fraction(peak) <= 127 * DENOMINATOR * dyadic(power)))
    differences = [out - weight for out, weight in zip(outputs, weights)]
    if candidates:
        common = max(candidates)
    else:
        lower = max(max(units) - 31, max(differences) - 48)
        legacy = min(min(units), min(differences) - 1)
        expanded = min(min(units) + 31, min(differences) - 1)
        if lower > expanded:
            raise ValueError("no common zero-context unit")
        common = legacy if lower <= legacy else expanded
    if not all(-31 <= unit - common <= 31 for unit in units):
        raise ValueError("unsupported context transfer")
    if not all(1 <= difference - common <= 48 for difference in differences):
        raise ValueError("unsupported output projection shift")
    codes = []
    for row, unit in zip(data, units):
        for value in row:
            physical = Fraction(value, DENOMINATOR) * dyadic(unit - common)
            codes.append(max(-128, min(127, round_away(physical))))
    return common, codes


def build_cases() -> list[dict]:
    rng = random.Random(0x4353504F4F4C)
    cases: list[dict] = []

    def add(name: str, scenario: int = 0, data=None, units=None,
            weights=None, outputs=None, numeric_error=False, success=False):
        index = len(cases)
        if data is None:
            boundary = [-(1 << 31), (1 << 31) - 1, -(1 << 24) - 1,
                        (1 << 24) + 1, 0, -1, 1, 32767, 32768,
                        65534, 65535, 65536, -65534, -65535, -65536]
            data = [[boundary[(lane + head) % len(boundary)] if lane < 15
                     else rng.randrange(-(1 << 31), 1 << 31)
                     for lane in range(LANES)] for head in range(HEADS)]
        data = [list(row) for row in data]
        units = list(units if units is not None else [-12 + head // 8 for head in range(HEADS)])
        weights = list(weights if weights is not None else [-30 + head % 31 for head in range(HEADS)])
        if outputs is None:
            # Choose legal output units only after independently selecting p.
            peaks = [max(abs(value) for value in row) for row in data]
            common = max(unit + next(power for power in range(-22, 10)
                                    if Fraction(peak) <= 127 * DENOMINATOR * dyadic(power))
                         for unit, peak in zip(units, peaks) if peak)
            outputs = [weight + common + 24 for weight in weights]
        outputs = list(outputs)
        try:
            common, codes = context_reference(data, units, weights, outputs)
            if numeric_error:
                raise AssertionError("negative arithmetic vector is actually legal")
        except ValueError:
            if not numeric_error:
                raise
            common, codes = 0, [0] * (HEADS * LANES)
        order = list(range(HEADS))
        rng.shuffle(order)
        cases.append(dict(id=index, name=name, scenario=scenario,
                          expected_error=bool(scenario or numeric_error) and not success,
                          tag=0xC5000000 + index, query=0x8000 + index,
                          epoch=0xF000 + index, common=common, units=units,
                          weights=weights, outputs=outputs, order=order,
                          data=data, codes=codes))

    zero = [[0] * LANES for _ in range(HEADS)]
    add("signed32_random_order_and_stalls")
    add("allzero_legacy", data=zero, units=[-10] * HEADS,
        weights=[-20] * HEADS, outputs=[10] * HEADS)
    add("allzero_expanded", data=zero, units=[0] * HEADS,
        weights=[0] * HEADS, outputs=[70] * HEADS)
    add("common_positive_286", data=zero, units=[255] * HEADS,
        weights=[-79] * HEADS, outputs=[255] * HEADS)
    add("common_negative_287", data=zero, units=[-256] * HEADS,
        weights=[30] * HEADS, outputs=[-256] * HEADS)
    tiny = [[(-1 if lane & 1 else 1) for lane in range(LANES)] for _ in range(HEADS)]
    add("nonzero_minimum_common", data=tiny, units=[-256] * HEADS,
        weights=[0] * HEADS, outputs=[-254] * HEADS)
    huge = [[-(1 << 31) if lane & 1 else (1 << 31) - 1 for lane in range(LANES)]
            for _ in range(HEADS)]
    add("nonzero_maximum_common", data=huge, units=[255] * HEADS,
        weights=[-10] * HEADS, outputs=[255] * HEADS)
    half = [row[:] for row in zero]
    half[0] = huge[0][:]
    ties = [65534, 65535, 65536, 196604, 196605, 196606,
            -65534, -65535, -65536, -196604, -196605, -196606]
    for head in range(1, HEADS):
        half[head] = [ties[lane % len(ties)] for lane in range(LANES)]
    add("right_one_half_thresholds", data=half, units=[0] + [8] * 31,
        weights=[0] * HEADS, outputs=[33] * HEADS)
    direct = [[value for _ in range(8) for value in
               [32767, 32768, 65534, 65535, 65536, -32767, -32768, -65536]]
              for _ in range(HEADS)]
    add("left_and_zero_odd_denominator", data=direct, units=[0] * HEADS)
    mixed = [row[:] for row in zero]
    mixed[0] = huge[0][:]
    add("zero_heads_full_transfer_extent", data=mixed,
        units=[0, 40, -22] + [9] * 29, weights=[0] * HEADS,
        outputs=[33] * HEADS)
    add("invalid_transfer_spread", units=[-256, 255] + [0] * 30,
        weights=[0] * HEADS, outputs=[30] * HEADS, numeric_error=True)
    numeric = cases[0]
    bad_outputs = numeric["outputs"][:]
    bad_outputs[17] = numeric["weights"][17] + numeric["common"]
    add("invalid_output_shift_zero", data=numeric["data"], units=numeric["units"],
        weights=numeric["weights"], outputs=bad_outputs, numeric_error=True)
    bad_outputs = numeric["outputs"][:]
    bad_outputs[19] = numeric["weights"][19] + numeric["common"] + 49
    add("invalid_output_shift_49", data=numeric["data"], units=numeric["units"],
        weights=numeric["weights"], outputs=bad_outputs, numeric_error=True)
    # Scenario numbers are testbench-owned protocol injections, not DUT state.
    for scenario, name in enumerate([
        "wrong_tag", "wrong_query", "wrong_epoch", "duplicate_head",
        "early_broker_terminal", "broker_error", "scratch_write_ack_error",
        "output_write_ack_error", "read_error", "read_early_last",
        "configuration_unaligned", "configuration_overlap", "configuration_wrap",
        "unknown_context_data", "unknown_context_unit", "unknown_config_unit",
        "unknown_broker_error"], 1):
        add(name, scenario=scenario)
    # Append only: the original thirty records retain every input and expected
    # byte.  New timing cases use the same packed vector ABI and rational oracle.
    for scenario, name in enumerate([
        "same_edge_final_context_and_success_terminal",
        "same_edge_final_context_and_error_terminal",
        "same_edge_final_scratch_ack_and_success_terminal",
        "same_edge_final_scratch_ack_and_error_terminal",
        "final_output_ack_error",
        "final_output_ack_unknown_error",
        "middle_raw_read_error_then_drain",
        "missing_final_read_last_then_drain",
        "unknown_middle_read_last_then_drain",
        "persisted_unit_nonzero_padding",
        "persisted_unit_unknown_data",
        "persisted_unit_transfer_out_of_range",
        "final_scratch_ack_error_after_terminal",
        "final_scratch_ack_unknown_error_after_terminal",
        "middle_raw_read_unknown_data_then_drain"], 18):
        add(name, scenario=scenario, success=scenario in (18, 20))
    return cases


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path(".cache/context_spool_vectors"))
    args = parser.parse_args()
    out = args.out.resolve()
    project = Path(__file__).resolve().parents[1]
    if not out.is_relative_to(project / ".cache"):
        raise SystemExit("generated vectors must remain inside the project's .cache")
    out.mkdir(parents=True, exist_ok=True)
    cases = build_cases()
    words = []
    for case in cases:
        row = [case["id"], case["scenario"], case["tag"], case["query"], case["epoch"],
               case["common"], int(case["expected_error"])]
        row += case["units"] + case["weights"] + case["outputs"] + case["order"]
        row += [value for head in case["data"] for value in head] + case["codes"]
        assert len(row) == STRIDE
        words.extend(row)
    payload = "".join(f"{word & 0xFFFFFFFF:08x}\n" for word in words).encode("ascii")
    path = out / "context_spool_vectors.hex"
    if path.exists():
        raise SystemExit(f"refusing to overwrite existing vectors: {path}")
    path.write_bytes(payload)
    manifest = dict(schema="tri_oracle_context_spool_synthetic_vectors_v1",
                    component_only=True, trained_or_full_attention_verified=False,
                    seed="0x4353504f4f4c", cases=len(cases), stride_words=STRIDE,
                    vector_file=path.name, bytes=len(payload),
                    sha256=hashlib.sha256(payload).hexdigest(),
                    source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    oracle="independent Fraction physical-rational round-away, no RTL math imports",
                    offsets=dict(units=UNIT_OFFSET, weights=WEIGHT_OFFSET, outputs=OUTPUT_OFFSET,
                                 order=ORDER_OFFSET, data=DATA_OFFSET, codes=CODE_OFFSET),
                    ordered_cases=[{key: case[key] for key in
                                    ("id", "name", "scenario", "expected_error", "common")}
                                   for case in cases])
    (out / "context_spool_vectors.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(dict(cases=len(cases), words=len(words), bytes=len(payload),
                          sha256=manifest["sha256"], path=str(path))))


if __name__ == "__main__":
    main()
