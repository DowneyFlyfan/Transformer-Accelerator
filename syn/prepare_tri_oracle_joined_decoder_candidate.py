"""Join the verified weight handoff and prefetched packed predictor in one source chip."""

import argparse
import json
from pathlib import Path
import re

from prepare_tri_oracle_packed_sign_predictor import ROOT, rewrite, sha


PHYSICAL = ROOT / ".cache/physical"
WIDE = PHYSICAL / "wide_weight_loader"
BASE = WIDE / "dual_lane_sign_chip"
HANDOFF = WIDE / "parallel_chip_weight_handoff"
PREDICTOR = PHYSICAL / "ranked_sign_slots"
REPLAY = "tri_oracle_packed_outlier_replay.sv"
INCLUDE = re.compile(r'(?m)^`include "([^"]+)"$')


def read(path):
    return json.loads(path.read_text())


def run(output):
    packed_path = ROOT / "records/wac_dual_lane_packed_sign_directed_result.json"
    handoff_path = ROOT / "records/wac_dual_lane_handoff_trained_result.json"
    prefetch_path = ROOT / "records/wac_prefetched_metadata_native_result.json"
    packed, handoff, prefetch = (read(path) for path in (packed_path, handoff_path, prefetch_path))
    assert packed["state"] == "packed_sign_predictor_and_weight_lanes_integrated_and_directed_fault_recovery_verified"
    assert packed["directed_counters"]["exact_outputs"] == prefetch["decoder_fault_recovery_exact_outputs"] == 504
    assert handoff["state"] == "dual_lane_handoff_reproduced_all_trained_outputs" and handoff["exact_outputs"] == 32768
    assert prefetch["state"] == "prefetched_metadata_verified_in_xcelium" and prefetch["fixture_cycles_added"] == 0

    setup_path = BASE / "prepared.json"
    setup = read(setup_path)
    assert setup["state"] == "dual_lane_packed_sign_chip_source_prepared"
    assert sha(setup_path) == packed["evidence_sha256"][str(setup_path.relative_to(ROOT))]
    source_run = HANDOFF / "full_native/trained_receipt.json"
    assert sha(source_run) == handoff["evidence_sha256"][str(source_run.relative_to(ROOT))]
    handoff_run = read(source_run)
    assert handoff_run["native"]["native_exit_status"] == 0 and handoff_run["counters"]["exact_outputs"] == 32768
    assert handoff_run["simulated_cycles"] == handoff["handoff_cycles"]

    rtl = ROOT / "verilog"
    weights = WIDE / "burst_handoff/rtl"
    replacements = {
        WIDE / "parallel_chip_v3/tri_oracle_batched_tensor390.sv":
            WIDE / "parallel_chip_load_address/tri_oracle_batched_tensor390.sv",
        rtl / "tri_oracle_wide_weight_loader.sv": weights / "tri_oracle_wide_weight_loader.sv",
        rtl / "tri_oracle_packed_weight_schedule.sv": weights / "tri_oracle_packed_weight_schedule.sv",
        PREDICTOR / "banked_observation_32" / REPLAY: PREDICTOR / "prefetched_metadata_32" / REPLAY,
    }
    for previous, selected in replacements.items():
        previous_key, selected_key = (str(path.relative_to(ROOT)) for path in (previous, selected))
        assert setup["input_sha256"][previous_key] == sha(previous)
        pins = prefetch["input_sha256"] if selected.name == REPLAY else handoff_run["input_sha256"]
        assert pins[selected_key] == sha(selected)

    bundle = BASE / "bundle.sv"
    baseline = bundle.read_text()
    code = rewrite(baseline, tuple(
        (f'`include "{previous}"', f'`include "{selected}"') for previous, selected in replacements.items()
    ))
    includes = [Path(name) for name in INCLUDE.findall(code)]
    assert len(includes) == len(set(includes)) and len(includes) == len(INCLUDE.findall(baseline))
    selected = set(replacements.values())
    assert selected <= set(includes)
    for path in includes:
        if path not in selected:
            assert setup["input_sha256"][str(path.relative_to(ROOT))] == sha(path)
    old_bench = BASE / "trained_tb.sv"
    assert setup["input_sha256"][str(old_bench.relative_to(ROOT))] == sha(old_bench)

    output.mkdir()
    joined = output / "bundle.sv"
    joined.write_text(code)
    bench = output / old_bench.name
    bench.write_text(old_bench.read_text())
    paths = {packed_path, handoff_path, prefetch_path, setup_path, source_run,
             Path(__file__).resolve(), bundle, joined, old_bench, bench, *includes}
    result = {
        "state": "prefetched_packed_sign_and_weight_handoff_decoder_prepared",
        "replacement_sources": {str(previous.relative_to(ROOT)): str(changed.relative_to(ROOT))
                                for previous, changed in replacements.items()},
        "input_sha256": {str(path.relative_to(ROOT)): sha(path) for path in sorted(paths)},
    }
    (output / "prepared.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(result["state"], len(includes), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=lambda value: Path(value).resolve())
    run(parser.parse_args().output)
