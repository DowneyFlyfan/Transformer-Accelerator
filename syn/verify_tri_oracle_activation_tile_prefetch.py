"""Qualify activation prefetch at the integrated chip command interface."""

import argparse
import hashlib
import json
import re
from pathlib import Path

from prepare_tri_oracle_activation_bank_overlap import TIMED_ACTIVATION_MACRO, schedule_next_activation_tile, stage_activation_pins
from verify_tri_oracle_activation_data import CANDIDATE as BASELINE
from verify_tri_oracle_cluster_weight_phase import ROOT, require
from verify_tri_oracle_phase_chip import summary, verify_case


RUN = ROOT / ".cache/phase_chip_prefetch"
CASES = {
    "commanded": {"windows": 0, "writes": 0},
    "multitile_gate": {"windows": 4, "writes": 192},
    "multitile_down": {"windows": 2, "writes": 96},
}


def verify():
    source = RUN / "source"
    evidence = {
        source / "bundle.sv", source / "bench.sv", source / "activation_timed.v",
        ROOT / "syn/prepare_tri_oracle_activation_bank_overlap.py",
        ROOT / "syn/prepare_tri_oracle_phase_chip.py", ROOT / "syn/run_tri_oracle_phase_chip.sh",
        ROOT / "verilog/tri_oracle_activation_tile_prefetch_probe.sv",
    }
    for name, make in (("tri_oracle_batched_tensor390.sv", schedule_next_activation_tile),
                       ("tri_oracle_sram_memory_compute.sv", stage_activation_pins)):
        earlier = BASELINE / "source" / name
        current = source / name
        require(current.read_text() == make(earlier.read_text()), f"unexpected prefetch implementation for {name}")
        evidence.update((earlier, current))

    def native_case(name):
        text, physical = verify_case(RUN, name)
        log = RUN / name / "xrun.log"
        count = re.search(r"^\s*Timing checks:\s+([\d,]+)", text, re.M)
        require(count and int(count[1].replace(",", "")) == 440140 and TIMED_ACTIVATION_MACRO in text,
                f"{name}: expected native timing checks for both memory types")
        evidence.update((log, RUN / name / "exit_status", RUN / name / "progress.log"))
        return text, physical

    result = {}
    for name, expected in CASES.items():
        baseline, old_phase = verify_case(BASELINE, name)
        candidate, phase = native_case(name)
        require(all(summary(baseline, marker) == summary(candidate, marker) for marker in (
            "BATCH408_PASS", "BATCH408_ACTIVATION_PASS", "UNIFIED_CHIP_FEEDFORWARD_PASS"
        )), f"{name}: chip output or activation inventory differs")
        memories = ("scalar", "packed", "writes", "commits", "reads", "read_clusters", "write_clusters")
        require(all(old_phase[key] == phase[key] for key in memories), f"{name}: changed weight operations")
        control, trial = (summary(text, "PACKED_DECODER_PASS") for text in (baseline, candidate))
        old_cycles, new_cycles = control.pop("cycles"), trial.pop("cycles")
        require(control == trial and trial["outputs"] == 504, f"{name}: changed transfer or output count")
        activity = summary(candidate, "CHIP_ACTIVATION_PREFETCH")
        require(activity["windows"] == activity["retired"] == expected["windows"]
                and activity["writes"] == expected["writes"]
                and (activity["parallel"] > 0) == bool(expected["windows"])
                and (new_cycles < old_cycles if expected["windows"] else new_cycles == old_cycles),
                f"{name}: wrong overlap or cycle count")
        traces = [(parent / name / "progress.log").read_text() for parent in (BASELINE, RUN)]
        require(re.sub(r" cycle=\d+$", "", traces[0], flags=re.M)
                == re.sub(r" cycle=\d+$", "", traces[1], flags=re.M),
                f"{name}: ordered command trace differs")
        evidence.update(BASELINE / name / file for file in ("xrun.log", "exit_status", "progress.log"))
        result[name] = {"baseline_cycles": old_cycles, "prefetch_cycles": new_cycles,
                        "exact_outputs": 504, "activation_prefetch": activity}

    fault, _ = native_case("prefetch_fault")
    fault_activity = summary(fault, "CHIP_ACTIVATION_PREFETCH")
    require(summary(fault, "BATCH408_FAULT_DRAINED") == {"fault": 17, "output_prefix_packets": 0}
            and summary(fault, "BATCH408_PASS")["exact_outputs"] == 504
            and summary(fault, "UNIFIED_CHIP_FEEDFORWARD_PASS")["responses"] == 2
            and fault_activity["windows"] == 5 and fault_activity["retired"] == 4,
            "prefetch fault did not drain and allow a clean retry")
    result["prefetch_fault"] = {"exact_retry_outputs": 504, "output_prefix_packets": 0,
                                "activation_prefetch": fault_activity}
    evidence.add(source / "prefetch_fault_bench.sv")
    hashes = {}
    for path in sorted(evidence):
        with path.open("rb") as stream:
            hashes[str(path.relative_to(ROOT))] = hashlib.file_digest(stream, "sha256").hexdigest()
    return {
        "state": "integrated_activation_tile_prefetch_verified",
        "scope": ("Chip packet interface exercises packed multi-tile gate/up and down projections, plus a failed "
                  "activation burst and clean retry. Activation and weight memory timing checks use the typical "
                  "vendor models. Accumulator operations keep their reference order. Weight loading starts once "
                  "the previous projection retires. Whole-chip synthesis and placement remain pending."),
        "cases": result,
        "evidence_sha256": hashes,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", type=Path)
    args = parser.parse_args()
    report = verify()
    if args.record:
        args.record.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print("Verified single-tile, multi-tile gate/up and down projections, and prefetch fault recovery.")
