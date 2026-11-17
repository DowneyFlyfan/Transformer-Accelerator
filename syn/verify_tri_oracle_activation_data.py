"""Verify activation broadcast and independent activation-bank access."""

import argparse
import hashlib
import json
import re
from pathlib import Path

from prepare_tri_oracle_activation_bank_overlap import (
    broadcast_chip_activation, prepare_activation_cluster, prepare_activation_core,
)
from verify_tri_oracle_cluster_weight_phase import ROOT, RUNS, require
from verify_tri_oracle_mapped_weight_prefetch import invocation
from verify_tri_oracle_phase_chip import CASES, summary, verify_case


BASE = ROOT / ".cache/phase_chip_clock"
CANDIDATE = ROOT / ".cache/phase_chip_activation"
MACRO_CASES = ("typical", "slow", "fast", "serial")


def verify_broadcast(evidence, include_trained=False):
    paths = ("tri_oracle_batched_tensor390.sv", "tri_oracle_compute_fabric.sv",
             "tri_oracle_sram_memory_compute.sv", "tri_oracle_sram_compute_cluster.sv")
    before = [(BASE / "source" / name).read_text() for name in paths]
    expected = (*broadcast_chip_activation(*before[:2]),
                prepare_activation_core(before[2]), prepare_activation_cluster(before[3]))
    for name, contents in zip(paths, expected, strict=True):
        original, changed = (folder / "source" / name for folder in (BASE, CANDIDATE))
        require(changed.read_text() == contents, f"changed logic outside the activation boundary: {name}")
        evidence.update((original, changed))
    results = {}
    names = (*CASES, "scalar", "trained") if include_trained else (*CASES, "scalar")
    for name in names:
        reference, reference_phase = verify_case(BASE, name)
        output, phase = verify_case(CANDIDATE, name)
        for marker in ("BATCH408_PASS", "BATCH408_ACTIVATION_PASS", "UNIFIED_CHIP_FEEDFORWARD_PASS"):
            require(summary(reference, marker) == summary(output, marker), f"{name}: changed {marker}")
        if name != "scalar":
            sign_control, sign_candidate = (summary(log, "DUAL_LANE_PACKED_SIGN_PASS") for log in (reference, output))
            if name == "trained":
                require(invocation(reference) == invocation(output.replace(str(CANDIDATE / "source"),
                                                                            str(BASE / "source"))),
                        "trained replays used different workload arguments")
                require(all(sign_control[key] == sign_candidate[key] for key in ("requests", "responses")),
                        "trained replay changed predictor sign traffic")
                require(summary(output, "BATCH408_PASS")["exact_outputs"] == 32768
                        and summary(reference, "PACKED_PAIR_BRANCHES") == summary(output, "PACKED_PAIR_BRANCHES"),
                        "trained replay changed packed weight traffic or lacked full output coverage")
                evidence.update(folder / "source" / file for folder in (BASE, CANDIDATE)
                                for file in ("trained_bench.sv", "bundle.sv"))
            else:
                require(sign_control == sign_candidate, f"{name}: changed sign data traffic")
            if name in CASES and CASES[name][1]:
                require(summary(reference, "BATCH408_FAULT_DRAINED") == summary(output, "BATCH408_FAULT_DRAINED"),
                        f"{name}: changed fault recovery")
        require({k: v for k, v in phase.items() if k != "double"} ==
                {k: v for k, v in reference_phase.items() if k != "double"}, f"{name}: changed observed memory operations")
        baseline, broadcast = (summary(log, "PACKED_DECODER_PASS") for log in (reference, output))
        baseline_cycles, broadcast_cycles = baseline.pop("cycles"), broadcast.pop("cycles")
        require(baseline == broadcast and broadcast_cycles < baseline_cycles, f"{name}: no cycle savings")
        trace = []
        for folder in (BASE, CANDIDATE):
            path = folder / name
            trace.append(re.sub(r" cycle=\d+$", "", (path / "progress.log").read_text(), flags=re.M))
            evidence.update(path / item for item in ("xrun.log", "exit_status", "progress.log"))
        require(trace[0] == trace[1], f"{name}: changed the ordered command trace")
        results[name] = {"baseline_cycles": baseline_cycles, "broadcast_cycles": broadcast_cycles,
                         "saved_cycles": baseline_cycles - broadcast_cycles, "outputs": broadcast["outputs"]}
    return results


def verify_early_write(evidence):
    results = {}
    for corner in MACRO_CASES:
        path = RUNS / f"activation_timed_{corner}"
        log = path / "xrun.log"
        text = log.read_text()
        require(int((path / "exit_status").read_text()) == 0 and "Simulation complete via $finish(1)" in text
                and not re.search(r"\*[EF],|timing violation|-nospecify|-notimingchecks", text, re.I),
                f"{corner}: timed memory replay failed")
        timing = re.search(r"^\s*Timing checks:\s+([\d,]+)", text, re.M)
        require(timing and int(timing[1].replace(",", "")) > 342986
                and str(path / "activation_timed.v") in text, f"{corner}: native activation timing was disabled")
        require(summary(text, "COMPILED_CLUSTER_WEIGHT_VALUES") == {"exact": 163840, "published": 2560},
                f"{corner}: changed arithmetic")
        cycles = summary(text, "COMPILED_CLUSTER_WEIGHT_PASS")
        weights = summary(text, "COMPILED_CLUSTER_WEIGHT_PHASE")
        require(cycles["serial"] == 0 and cycles["reads"] == 1024 and
                weights["physical_writes"] == 1280 and weights["physical_reads"] == 5120,
                f"{corner}: changed projection or weight overlap workload")
        activity = summary(text, "ACTIVATION_PREFETCH_PASS")
        require(activity == {"writes": 10240, "concurrent": 0 if corner == "serial" else 511,
                             "same_bank_stalls": 0 if corner == "serial" else 1},
                f"{corner}: incomplete activation bank arbitration coverage")
        files = ("xrun.log", "exit_status", "core.sv", "cluster.sv", "bench.sv", "activation_timed.v", "weight_timed.v")
        evidence.update(path / file for file in files)
        results[corner] = {"cycles": cycles["cycles"], "activation_bank_activity": activity}
    negative = RUNS / "activation_typical/xrun.log"
    require("Timing violation" in negative.read_text() and "$setuphold<hold>" in negative.read_text()
            and "CLUSTER_WEIGHT_ACCUMULATOR" in negative.read_text(), "unstaged activation pins did not reproduce the failure")
    evidence.add(negative)
    require(results["serial"]["cycles"] > results["typical"]["cycles"], "activation overlap saved no cycles")
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", type=Path)
    parser.add_argument("--include-trained", action="store_true")
    args = parser.parse_args()
    evidence = {ROOT / "syn/prepare_tri_oracle_activation_bank_overlap.py",
                ROOT / "syn/prepare_tri_oracle_phase_chip.py",
                ROOT / "syn/prepare_tri_oracle_cluster_weight_phase.py"}
    broadcast, prefetch = verify_broadcast(evidence, args.include_trained), verify_early_write(evidence)
    hashes = {}
    for path in sorted(evidence):
        with path.open("rb") as stream:
            hashes[str(path.relative_to(ROOT))] = hashlib.file_digest(stream, "sha256").hexdigest()
    record = {
        "state": "activation_broadcast_and_timed_bank_prefetch_verified",
        "scope": ("Chip command tests use the broadcast path with functional activation memory delays. "
                  "Separate arithmetic tests exercise timed activation and weight banks at three corners using a staged "
                  "activation interface and simultaneous next-tile writes. The full chip scheduler still requires prefetch integration."),
        "command_replays": broadcast,
        "trained_arithmetic_replays": prefetch,
        "typical_prefetch_saved_cycles": prefetch["serial"]["cycles"] - prefetch["typical"]["cycles"],
        "evidence_sha256": hashes,
    }
    if args.record:
        args.record.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(f"Verified {len(broadcast)} chip broadcast cases and four timed activation-bank replays.")


if __name__ == "__main__":
    main()
