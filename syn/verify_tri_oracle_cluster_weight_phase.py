"""Check the timed Xcelium replay evidence and record the matched controls."""

import argparse
import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / ".cache/cluster_weight_phase"
CASES = {
    "typical_reset": ("tt1v25c", 0, 0),
    "slow": ("ssg0p9v125c", 0, 0),
    "fast": ("ffg1p05vm40c", 0, 0),
    "serial": ("tt1v25c", 1, 0),
    "stalled_issue": ("tt1v25c", 0, 64),
}
METRICS = {
    "PASS": "serial cycles reads",
    "PHASE": "hold_issue physical_reads physical_writes",
    "VALUES": "exact published",
    "TRAFFIC": "write_beats overlap blocked",
    "FLOW": "out_stall requests",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify(all_clusters=False):
    hashes = {}
    clusters = 5 if all_clusters else 1
    case_names = {
        "typical_reset": "five_typical",
        "slow": "five_slow",
        "fast": "five_fast",
        "serial": "five_serial",
        "stalled_issue": "five_stall",
        "no_guard": "five_no_guard",
    } if all_clusters else {}

    def remember(path):
        with path.open("rb") as handle:
            hashes[str(path.relative_to(ROOT))] = hashlib.file_digest(handle, "sha256").hexdigest()

    def native_log(name, expected_status):
        directory = RUNS / case_names.get(name, name)
        log = directory / "xrun.log"
        exit_status = directory / "exit_status"
        require(int(exit_status.read_text()) == expected_status, f"{name}: wrong exit status")
        output = log.read_text()
        require("TOOL:\txrun(64)\t25.03" in output and ": Exiting on " in output, f"{name}: incomplete log")
        require(not re.search(r"timing violation|-notimingchecks|-nospecify|TRI_ORACLE_WEIGHT_UNIT_DELAY", output, re.I),
                f"{name}: timing checks disabled or violated")
        timing_count = re.search(r"^\s*Timing checks:\s+([\d,]+)", output, re.M)
        require(timing_count and int(timing_count[1].replace(",", "")) == clusters*67520,
                f"{name}: expected checks for all {clusters*64} weight banks")
        for path in (log, exit_status):
            remember(path)
        for path in re.findall(r"^\t(/[^\n]+\.(?:sv|v))$", output, re.M):
            remember(Path(path))
        return output

    cases = {}
    for name, (corner, serial, hold_issue) in CASES.items():
        output = native_log(name, 0)
        require(f"ts5n28hpcpsvta32x128m2fw_130a_{corner}.v" in output, f"{name}: wrong model corner")
        require(not re.search(r"\*[EF],", output), f"{name}: native simulation error")
        for arg, value in (("SERIAL", serial), ("HOLD_ISSUE", hold_issue)):
            require(f"+{arg}={value}" in output if value else f"+{arg}=" not in output,
                    f"{name}: wrong configuration")
        result = {"weight_memory_corner": corner}
        for marker, fields in METRICS.items():
            pattern = " ".join(f"{item}=([0-9,]+)" for item in fields.split())
            matches = re.findall(rf"^COMPILED_CLUSTER_WEIGHT_{marker} {pattern}$", output, re.M)
            require(len(matches) == 1, f"{name}: expected one {marker} summary")
            for field, value in zip(fields.split(), matches[0], strict=True):
                result[field] = [int(part) for part in value.split(",")] if "," in value else int(value)
        expected = {"serial": serial, "hold_issue": hold_issue, "exact": clusters*32768, "published": clusters*512,
                    "reads": 1024, "physical_reads": clusters*1024, "physical_writes": clusters*256,
                    "write_beats": clusters*256}
        if all_clusters:
            summary = re.findall(r"^COMPILED_CLUSTER_WEIGHT_FABRIC clusters=5 cores=20 dual_cluster_writes=(\d+)$",
                                 output, re.M)
            require(len(summary) == 1 and int(summary[0]) > 0, f"{name}: no concurrent writes to different clusters")
            result["dual_cluster_writes"] = int(summary[0])
            require(all(count > 6 for count in result["requests"]), f"{name}: no whole-fabric loader traffic")
        else:
            expected["requests"] = [6, 6]
        require(all(result[key] == value for key, value in expected.items()), f"{name}: incomplete replay")
        require(result["out_stall"] > 0 and (result["overlap"] > 0) == (not serial)
                and (result["blocked"] > 0) == (not serial), f"{name}: missing flow-control coverage")
        cases[name] = result

    negative = native_log("no_guard", 2)
    prefix = r"cluster=[0-4] " if all_clusters else ""
    require("+IGNORE_RESERVATION=1" in negative and "+HOLD_ISSUE=64" in negative
            and re.search(rf"^CLUSTER_WEIGHT_PHYSICAL_OVERWRITE {prefix}word=0$", negative, re.M)
            and "COMPILED_CLUSTER_WEIGHT_PASS" not in negative, "negative control missed the first overwrite")
    reference_directory = (RUNS / "five_cluster_reference" if all_clusters
                           else ROOT / ".cache/compiled_cluster_weight_overlap/reference")
    reference = reference_directory / "reference.json"
    remember(reference)
    expected_hashes = json.loads(reference.read_text())["evidence_sha256"]
    for name in ("accumulators.hex", "activations.hex", "initial_weights.hex", "masks.hex"):
        path = reference.parent / name
        remember(path)
        key = str(path.relative_to(ROOT))
        require(hashes[key] == expected_hashes[key], f"independent reference changed: {name}")
    for name in ("down_index.bin", "down_payload.bin"):
        remember((RUNS / case_names.get("serial", "serial") / name).resolve(strict=True))
    saved = cases["serial"]["cycles"] - cases["typical_reset"]["cycles"]
    require(saved > 0, "overlap did not improve throughput")
    result = {
        "state": "timed_single_port_weight_overlap_verified_with_four_core_trained_arithmetic",
        "scope": "One four-core cluster and two trained layer-zero feature tiles. Weight memory models use native timing at three corners. Other memories use functional delays. Core and memory clocks are ideal; full-chip integration and timing are pending.",
        "clock_periods_ps": {"weight_memory": 862, "core": 1724},
        "native_cases": cases,
        "typical_cycles_saved_vs_serial": saved,
        "negative_control": {"exit_status": 2, "expected_first_overwrite_word": 0},
        "evidence_sha256": hashes,
    }
    if all_clusters:
        result["state"] = "timed_single_port_weight_overlap_verified_on_five_cluster_compute_fabric"
        result["scope"] = ("All five compute clusters, 20 arithmetic cores and 320 compiled weight banks. "
                           "Two trained layer-zero feature tiles with signed reference inputs and output stalls. "
                           "Other memories use functional delays. Core and memory clocks are ideal. "
                           "Chip boundary integration and placed timing remain pending.")
        result["compute_geometry"] = {"clusters": clusters, "cores": 4*clusters, "weight_banks": 64*clusters}
    return result


def verify_mapped():
    baseline = verify(all_clusters=True)
    map_directory = RUNS / "fabric_mapping"
    netlist = map_directory / "mapped.v"
    masters = re.findall(r"^module (\w+)\s*\(", netlist.read_text(), re.M)
    require(masters == ["tri_oracle_weight_phase_fabric"], "expected one flattened mapped controller")
    area_report = (map_directory / "area.rpt").read_text()
    area = re.search(r"^tri_oracle_weight_phase_fabric\s+NA\s+(\d+)\s+([\d.]+)", area_report, re.M)
    require(area and int(area[1]) > 0 and float(area[2]) > 0, "mapped cell count or area missing")
    mapping_log = (map_directory / "console.log").read_text()
    require(re.search(r"^TRI_ORACLE_WEIGHT_PHASE_FABRIC_MAPPED$", mapping_log, re.M),
            "Genus did not finish mapping")
    require("No unresolved references" in (map_directory / "unresolved.rpt").read_text(),
            "mapped controller has unresolved references")

    def worst_slack(report_name):
        report = (map_directory / report_name).read_text()
        path = re.search(r"^Path 1: (?:MET|VIOLATED) \(([+-]?[\d.]+) ps\)", report, re.M)
        require(path, f"missing first timing path in {report_name}")
        return float(path[1])

    evidence = [netlist, map_directory / "timing.sdc", map_directory / "area.rpt",
                map_directory / "setup.rpt", map_directory / "retirement.rpt",
                map_directory / "unresolved.rpt", map_directory / "console.log",
                ROOT / "syn/tri_oracle_map_weight_phase_fabric.tcl"]
    native_cases = {}
    for corner, source_case in (("typical", "typical_reset"), ("slow", "slow"), ("fast", "fast")):
        work = RUNS / f"mapped_{corner}"
        rtl_run = RUNS / f"five_{corner}"
        for name in ("core.sv", "cluster.sv", "weight_timed.v"):
            require((work / name).read_bytes() == (rtl_run / name).read_bytes(),
                    f"{corner}: logic or weight model outside the mapped controller changed")
        require((work / "bench.sv").read_text() == (rtl_run / "bench.sv").read_text().replace(
            "tri_oracle_weight_phase_fabric weight_port (", "tri_oracle_weight_phase_fabric_adapter weight_port ("),
            f"{corner}: mapped replay used a different test bench")
        for name in ("initial_weights.hex", "activations.hex", "masks.hex", "accumulators.hex",
                     "down_index.bin", "down_payload.bin"):
            require((work / name).resolve(strict=True) == (rtl_run / name).resolve(strict=True),
                    f"{corner}: replay used a different trained fixture")
        log = work / "xrun.log"
        status = work / "exit_status"
        output = log.read_text()
        require(int(status.read_text()) == 0 and ": Exiting on " in output, f"{corner}: incomplete mapped replay")
        require(f"\t{netlist}\n" in output and f"\t{work / 'mapped_fabric_adapter.sv'}\n" in output
                and "tri_oracle_weight_phase_fabric.sv\n" not in output,
                f"{corner}: mapped controller was not selected")
        require(not re.search(r"\*[EF],|timing violation|-notimingchecks|-nospecify", output, re.I),
                f"{corner}: mapped replay error or timing violation")
        timing_count = re.search(r"^\s*Timing checks:\s+([\d,]+)", output, re.M)
        require(timing_count and int(timing_count[1].replace(",", "")) >= 337600,
                f"{corner}: weight memory timing checks are missing")
        original = rtl_run / "xrun.log"
        summary = r"^COMPILED_CLUSTER_WEIGHT_.*$"
        require(re.findall(summary, output, re.M) == re.findall(summary, original.read_text(), re.M)
                and len(re.findall(summary, output, re.M)) == len(METRICS)+1,
                f"{corner}: mapped replay disagrees with the matching register-transfer-level run")
        evidence.extend((log, status, original))
        for path in re.findall(r"^\t(/[^\n]+\.(?:sv|v))$", output, re.M):
            evidence.append(Path(path))
        native_cases[corner] = baseline["native_cases"][source_case]
    hashes = {}
    for path in sorted(set(evidence)):
        with path.open("rb") as handle:
            hashes[str(path.relative_to(ROOT))] = hashlib.file_digest(handle, "sha256").hexdigest()
    return {
        "state": "five_cluster_weight_controller_mapped_and_replayed",
        "scope": ("Genus-mapped weight control and data selection across five clusters. "
                  "Xcelium tests the mapped gates with 320 timed weight-bank models, using unannotated standard-cell models "
                  "and ideal clocks. Timing estimates use a single slow library and boundary delays with zero wire load."),
        "mapped_cells": int(area[1]),
        "mapped_cell_area_square_um": float(area[2]),
        "genus_slow_boundary_slack_ps": {"setup": worst_slack("setup.rpt"),
                                        "retirement_setup": worst_slack("retirement.rpt")},
        "native_cases": native_cases,
        "trained_fixture_sha256": {
            path: digest for path, digest in baseline["evidence_sha256"].items()
            if path.startswith(".cache/cluster_weight_phase/five_cluster_reference/")
            or path.endswith(("down_index.bin", "down_payload.bin"))
        },
        "evidence_sha256": hashes,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", type=Path)
    parser.add_argument("--all-clusters", action="store_true")
    parser.add_argument("--mapped", action="store_true")
    args = parser.parse_args()
    report = verify_mapped() if args.mapped else verify(args.all_clusters)
    if args.record:
        args.record.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    if args.mapped:
        print(f"Verified {len(report['native_cases'])} mapped Xcelium passes and "
              f"{report['mapped_cells']} standard cells through Genus.")
    else:
        print(f"Verified {len(report['native_cases'])} Xcelium passes and one overwrite rejection. "
              f"Saved {report['typical_cycles_saved_vs_serial']} typical-corner core cycles.")
