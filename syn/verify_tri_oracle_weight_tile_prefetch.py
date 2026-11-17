"""Qualify early packed weight requests, reservation stalls, and fault recovery."""

import argparse
import hashlib
import json
import re
from pathlib import Path

from prepare_tri_oracle_weight_tile_prefetch import bind_weight_guards, schedule_weight_prefetch
from verify_tri_oracle_cluster_weight_phase import ROOT, require
from verify_tri_oracle_phase_chip import summary, verify_case


RUN = ROOT / ".cache/phase_chip_weight_prefetch"
BASELINE = ROOT / ".cache/phase_chip_prefetch"


def verify_attention(evidence):
    physical = ROOT / ".cache/physical"
    fixture = physical / "shared437/fixture"
    archive_path = physical / "wide_weight_loader/parallel_chip_weight_handoff/full_native/attention_receipt.json"
    archive = json.loads(archive_path.read_text())
    archived_log = archive_path.parent / "attention/xrun.log"
    require(archive["native"]["native_exit_status"] == 0
            and hashlib.sha256(archived_log.read_bytes()).hexdigest() == archive["native"]["log_sha256"],
            "archived attention run changed")
    evidence.update((archive_path, archived_log, Path(__file__).resolve()))
    files = list(fixture.iterdir())
    require(len(files) == 13, "attention fixture inventory changed")
    for path in files:
        require(hashlib.sha256(path.read_bytes()).hexdigest()
                == archive["input_sha256"][str(path.relative_to(ROOT))], f"attention fixture changed: {path.name}")
        evidence.add(path)

    control, old_phase = verify_case(BASELINE, "attention")
    output, phase = verify_case(RUN, "attention")
    require(old_phase == phase, "attention physical phase counters changed")
    for directory, text in ((BASELINE, control), (RUN, output)):
        bundle, bench = (directory / "source" / name for name in ("bundle.sv", "attention_bench.sv"))
        require(all(f"\t{item}\n" in text for item in (bundle, bench, f"+FIXTURE={fixture}")),
                "attention used different simulator inputs")
        evidence.update((bundle, bench, directory / "attention/xrun.log", directory / "attention/exit_status"))
    require((BASELINE / "source/attention_bench.sv").read_bytes()
            == (RUN / "source/attention_bench.sv").read_bytes(), "attention check changed")
    for marker in ("CHIP_COMMAND_COUNTS", "DECODER_CONTEXT_SHARED_PORT_PASS",
                   "COMPOSE430_SHARED_WRITE_PASS", "COMPOSE430_SHARED_READ_PASS", "COMPOSE430_PASS"):
        require(summary(control, marker) == summary(output, marker), f"attention changed {marker}")
    command = summary(output, "COMPOSE430_PASS")
    require({key: value for key, value in command.items() if key != "stalls"} ==
            {key: value for key, value in archive["counters"].items() if key != "stalls"},
            "attention changed the archived workload result")
    require(command["rows"] == 4 and command["values"] == 1023 and command["maps"] == 576,
            "attention replay incomplete")
    return {"command": command, "physical_phase": phase}


def verify(include_attention=False):
    source = RUN / "source"
    evidence = {
        source / "bundle.sv", source / "bench.sv", source / "guarded_weight_probe.sv",
        source / "tri_oracle_phase_weight_ingress.sv", source / "weight_prefetch_stress_bench.sv",
        source / "tri_oracle_backpressured_raw_weight_loader.sv",
        ROOT / "syn/prepare_tri_oracle_phase_chip.py", ROOT / "syn/prepare_tri_oracle_weight_tile_prefetch.py",
        ROOT / "syn/run_tri_oracle_phase_chip.sh", ROOT / "verilog/tri_oracle_projection_weight_reuse.sv",
        ROOT / "verilog/tri_oracle_weight_tile_prefetch_probe.sv",
    }
    for name, transform in (("tri_oracle_batched_tensor390.sv", schedule_weight_prefetch),
                            ("tri_oracle_compute_fabric.sv", bind_weight_guards)):
        original = BASELINE / "source" / name
        changed = source / name
        require(changed.read_text() == transform(original.read_text()), f"candidate used a different {name}")
        evidence.update((original, changed))

    def pin_case(directory, prefix):
        evidence.update(directory / prefix / item for item in ("xrun.log", "progress.log", "exit_status"))

    def native(name):
        output, phases = verify_case(RUN, name)
        pin_case(RUN, name)
        require(summary(output, "BATCH408_PASS")["exact_outputs"] == 504,
                f"{name}: arithmetic verification incomplete")
        timing = re.search(r"^\s*Timing checks:\s+([\d,]+)", output, re.M)
        require(timing and int(timing[1].replace(",", "")) >= 440140, f"{name}: missing compiled memory timing checks")
        return output, phases

    result = {}
    for name in ("commanded", "scalar", "early_gate", "multitile_gate", "multitile_down"):
        control, old_phase = verify_case(BASELINE, name)
        output, new_phase = native(name)
        pin_case(BASELINE, name)
        for marker in ("BATCH408_PASS", "BATCH408_ACTIVATION_PASS", "UNIFIED_CHIP_FEEDFORWARD_PASS"):
            require(summary(control, marker) == summary(output, marker), f"{name}: changed {marker}")
        require(all(new_phase[key] == old_phase[key] for key in
                    ("packed", "scalar", "reads", "writes", "read_clusters", "write_clusters")),
                f"{name}: physical operation count changed")
        first, second = (summary(log, "PACKED_DECODER_PASS") for log in (control, output))
        before, after = first.pop("cycles"), second.pop("cycles")
        overlap = summary(output, "CHIP_WEIGHT_PREFETCH")
        if name in {"commanded", "scalar"}:
            require(before == after and not any(overlap.values()), f"{name}: non-prefetch schedule changed")
        else:
            require(after < before and overlap["requests"] > 0 and overlap["loads"] > 0,
                    f"{name}: no verified weight overlap benefit")
            if name == "early_gate":
                require(overlap["alongside_reads"] > 0, "short tail did not share cycles with projection reads")
        require(first == second, f"{name}: changed packet traffic")
        traces = [(folder / name / "progress.log").read_text() for folder in (BASELINE, RUN)]
        require(re.sub(r" cycle=\d+$", "", traces[0], flags=re.M)
                == re.sub(r" cycle=\d+$", "", traces[1], flags=re.M), f"{name}: changed output order")
        result[name] = {"control_cycles": before, "prefetch_cycles": after, "exact_outputs": 504,
                        "overlap": overlap}

    stall, _ = native("weight_stall")
    protected = summary(stall, "CHIP_WEIGHT_GUARD")["blocked"]
    require(protected > 0 and "+STALL_FIRST_PROJECTION" in stall, "stalled projection never blocked a reserved write")
    result["weight_stall"] = {"protected_cycles": protected, "exact_outputs": 504}

    for lane in range(2):
        name = f"weight_prefetch_fault_lane{lane}"
        output, _ = native(name)
        require(summary(output, "BATCH408_FAULT_DRAINED") == {"fault": 18, "output_prefix_packets": 0}
                and summary(output, "UNIFIED_CHIP_FEEDFORWARD_PASS")["responses"] == 2,
                f"{name}: lane fault did not drain and retry")
        result[name] = {"exact_retry_outputs": 504, "output_prefix_packets": 0}

    negative = RUN / "weight_guard_disabled"
    text = (negative / "xrun.log").read_text()
    overwritten = re.findall(r"^CHIP_WEIGHT_PREFETCH_OVERWRITE cluster=(\d+) word=(\d+)$", text, re.M)
    require(int((negative / "exit_status").read_text()) == 2 and len(overwritten) == 1
            and "+IGNORE_WEIGHT_REUSE" in text and "BATCH408_PASS" not in text,
            "disabling the guard did not reject an overwrite of an unread weight")
    pin_case(RUN, "weight_guard_disabled")
    cluster, word = map(int, overwritten[0])
    if include_attention:
        result["attention"] = verify_attention(evidence)
    hashes = {}
    for path in sorted(evidence):
        with path.open("rb") as stream:
            hashes[str(path.relative_to(ROOT))] = hashlib.file_digest(stream, "sha256").hexdigest()
    return {
        "state": "integrated_packed_weight_prefetch_and_reservation_verified",
        "scope": ("Chip command cases at the typical memory corner. Backpressured weight lanes stage the "
                  "next tile while the current projection runs. Independent monitors check each physical commit "
                  "against unread words. Whole-chip synthesis, physical timing, and model validation remain open."),
        "cases": result,
        "unguarded_overwrite": {"cluster": cluster, "word": word, "native_exit_status": 2},
        "evidence_sha256": hashes,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", type=Path)
    parser.add_argument("--include-attention", action="store_true")
    args = parser.parse_args()
    report = verify(args.include_attention)
    if args.record:
        args.record.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print("Verified chip weight overlap, reservation stalls, lane fault recovery, and overwrite rejection.")
