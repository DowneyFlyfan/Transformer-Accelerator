"""Verify the two-phase SRAM path using chip command and recovery replays."""

import argparse
import hashlib
import json
import re
from pathlib import Path

from prepare_tri_oracle_cluster_weight_phase import distribute_weight_macro_inputs
from prepare_tri_oracle_phase_chip import INCLUDE, JOINED, ROOT
from prepare_tri_oracle_phase_macro_boundary import REPAIRED_CLOCK_BOUNDARY


RUN = ROOT / ".cache/phase_chip"
CASES = {
    "commanded": ("positive", 0),
    "sign_fault": ("sign_fault", 4),
    "weight_fault_lane0": ("weight_fault_lane0", 2),
    "weight_fault_lane1": ("weight_fault_lane1", 2),
}
MARKERS = ("BATCH408_PASS", "PACKED_DECODER_PASS", "DUAL_LANE_PACKED_SIGN_PASS",
           "UNIFIED_CHIP_FEEDFORWARD_PASS")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def summary(output, marker):
    matches = re.findall(rf"^{marker} (.+)$", output, re.M)
    require(len(matches) == 1, f"expected one {marker} summary")
    return {key: int(value) for item in matches[0].split() for key, value in [item.split("=")]}


def verify_case(run, name):
    work = run / name
    output = (work / "xrun.log").read_text()
    require((work / "exit_status").read_text().strip() == "0"
            and "Simulation complete via $finish(1)" in output,
            f"{name}: Xcelium replay incomplete")
    require(not re.search(r"\*[EF],|timing violation|-nospecify|-notimingchecks|"
                          r"TRI_ORACLE_WEIGHT_UNIT_DELAY", output, re.I),
            f"{name}: simulator or weight-model timing error")
    timing = re.search(r"^\s*Timing checks:\s+([\d,]+)", output, re.M)
    require(timing and int(timing[1].replace(",", "")) >= 337600,
            f"{name}: missing timing checks for the 320 weight models")
    path_metrics = summary(output, "PHASE_CHIP_PASS")
    require(path_metrics["read_clusters"] == 5
            and path_metrics["write_clusters"] == 5 and path_metrics["reads"] > 0
            and path_metrics["writes"] > 0
            and path_metrics["commits"] == path_metrics["writes"] == path_metrics["scalar"] + path_metrics["packed"],
            f"{name}: incomplete output or physical write inventory")
    return output, path_metrics


def verify(include_scalar, include_trained, buffered=False, include_attention=False, derived_clock=False):
    results = {}
    run = RUN.with_name("phase_chip_clock" if derived_clock else "phase_chip_buffered") if buffered else RUN
    source = run / "source"
    bundle = source / "bundle.sv"
    includes = {Path(name) for name in INCLUDE.findall(bundle.read_text())}
    if buffered:
        controller = (REPAIRED_CLOCK_BOUNDARY / "controller.v" if derived_clock else
                      ROOT / ".cache/cluster_weight_phase/macro_boundary_distributed/controller.v")
        require(controller in includes and ROOT / "verilog/tri_oracle_weight_phase_fabric.sv" not in includes,
                "buffered timing controller was not selected")
        core = "tri_oracle_sram_memory_compute.sv"
        require((source / core).read_text() ==
                distribute_weight_macro_inputs((RUN / "source" / core).read_text()),
                "buffered memory drivers were not selected")
    if derived_clock:
        top = (source / "tri_oracle_chip_command_layer.sv").read_text()
        require(REPAIRED_CLOCK_BOUNDARY / "clock.v" in includes
                and "input logic weight_memory_clk," in top and "input logic clk" not in top
                and "tri_oracle_phase_chip_clock clock_source" in top
                and top.count(".clk(core_clk)") == top.count(".rst_n(core_rst_n)") == 2,
                "chip bypassed the mapped internal clock or reset")
    files = {bundle, source / "bench.sv", ROOT / "verilog/tri_oracle_phase_chip_probe.sv",
             ROOT / "syn/prepare_tri_oracle_phase_chip.py", ROOT / "syn/run_tri_oracle_phase_chip.sh",
             *includes}
    for name, (reference, fault) in CASES.items():
        output, path_metrics = verify_case(run, name)
        require(summary(output, "BATCH408_PASS")["exact_outputs"] == 504, f"{name}: incomplete replay")
        work = run / name
        previous = JOINED / reference
        original = (previous / "xrun.log").read_text()
        for marker in MARKERS:
            require(summary(output, marker) == summary(original, marker), f"{name}: changed {marker} result")
        require((work / "progress.log").read_bytes() == (previous / "progress.log").read_bytes(),
                f"{name}: changed the ordered command trace")
        if fault:
            require(summary(output, "BATCH408_FAULT_DRAINED") == {"fault": fault, "output_prefix_packets": 0},
                    f"{name}: injected fault did not drain safely")
        require(path_metrics["packed"] > 0 and path_metrics["double"] > 0, f"{name}: missing packed write coverage")
        results[name] = {"command": summary(output, "BATCH408_PASS"),
                         "transport": summary(output, "PACKED_DECODER_PASS"), "physical_phase": path_metrics}
        for directory in (work, previous):
            files.update(directory / log for log in ("xrun.log", "progress.log"))
        files.add(work / "exit_status")

    if include_scalar:
        output, path_metrics = verify_case(run, "scalar")
        require(summary(output, "BATCH408_PASS")["exact_outputs"] == 504
                and path_metrics["scalar"] > 0 and path_metrics["packed"] == 0,
                "scalar command did not use scalar weight writes")
        results["scalar"] = {"command": summary(output, "BATCH408_PASS"),
                             "transport": summary(output, "PACKED_DECODER_PASS"), "physical_phase": path_metrics}
        files.add(source / "scalar_bench.sv")
        files.update(run / "scalar" / log for log in ("xrun.log", "progress.log", "exit_status"))

    if include_trained:
        output, path_metrics = verify_case(run, "trained")
        require(summary(output, "BATCH408_PASS")["exact_outputs"] == 32768, "incomplete trained replay")
        trained_reference = JOINED / "full_native/trained"
        require((run / "trained/progress.log").read_bytes() == (trained_reference / "progress.log").read_bytes(),
                "trained layer changed the ordered command trace")
        for marker in MARKERS:
            require(summary(output, marker) == summary((trained_reference / "xrun.log").read_text(), marker),
                    f"trained layer changed {marker}")
        results["trained"] = {"command": summary(output, "BATCH408_PASS"),
                              "transport": summary(output, "PACKED_DECODER_PASS"), "physical_phase": path_metrics}
        files.add(source / "trained_bench.sv")
        files.update(run / "trained" / log for log in ("xrun.log", "progress.log", "exit_status"))
        files.update(trained_reference / log for log in ("xrun.log", "progress.log"))

    if include_attention:
        output, path_metrics = verify_case(run, "attention")
        original = JOINED / "full_native/attention/xrun.log"
        required_markers = ("COMPOSE430_PASS", "COMPOSE430_SHARED_WRITE_PASS", "COMPOSE430_SHARED_READ_PASS",
                            "DECODER_CONTEXT_SHARED_PORT_PASS", "CHIP_COMMAND_COUNTS")
        expected = original.read_text()
        for marker in required_markers:
            require(summary(output, marker) == summary(expected, marker), f"attention changed {marker}")
        metrics = summary(output, "COMPOSE430_PASS")
        require(metrics["rows"] == 4 and metrics["values"] == 1023 and metrics["maps"] == 576,
                "incomplete attention replay")
        results["attention"] = {"command": metrics, "physical_phase": path_metrics}
        files.update((source / "attention_bench.sv", original))
        files.update(run / "attention" / log for log in ("xrun.log", "exit_status"))

    hashes = {}
    for path in sorted(files):
        with path.open("rb") as stream:
            hashes[str(path.relative_to(ROOT))] = hashlib.file_digest(stream, "sha256").hexdigest()
    return {
        "state": "two_phase_weight_storage_verified_through_chip_command_interface",
        "scope": ("The joined register-transfer-level source with packet commands, narrow and packed memory responses, "
                  "and 20 Booth arithmetic cores. The existing chip scheduler still loads weights between projections. "
                  "An additional boundary clock drives the weight memory and the test bench derives the core clock. "
                  "Native weight timing checks are enabled for the typical library. Chip placement and routing remain pending."),
        "clock_periods_ps": {"weight": 862, "core": 1724},
        "buffered_weight_boundary": buffered,
        "derived_core_clock": derived_clock,
        "cases": results,
        "evidence_sha256": hashes,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", type=Path)
    parser.add_argument("--include-scalar", action="store_true")
    parser.add_argument("--include-trained", action="store_true")
    parser.add_argument("--buffered-boundary", action="store_true")
    parser.add_argument("--include-attention", action="store_true")
    parser.add_argument("--derived-clock", action="store_true")
    args = parser.parse_args()
    if args.derived_clock and not args.buffered_boundary:
        parser.error("the derived clock uses the buffered weight boundary")
    report = verify(args.include_scalar, args.include_trained, args.buffered_boundary, args.include_attention,
                    args.derived_clock)
    if args.record:
        args.record.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"Verified {len(report['cases'])} chip-command Xcelium replays.")
