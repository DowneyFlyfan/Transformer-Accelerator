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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", type=Path)
    parser.add_argument("--all-clusters", action="store_true")
    args = parser.parse_args()
    report = verify(args.all_clusters)
    if args.record:
        args.record.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"Verified {len(report['native_cases'])} Xcelium passes and one overwrite rejection. "
          f"Saved {report['typical_cycles_saved_vs_serial']} typical-corner core cycles.")
