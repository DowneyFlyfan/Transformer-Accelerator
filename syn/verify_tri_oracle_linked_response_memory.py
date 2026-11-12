"""Bind the compiled-memory accounting to the response-address layer replay."""

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import resource
import sys

from verify_tri_oracle_shared_memory import PHYSICAL, ROOT, check_native_census, require, sha


BENCH = "tri_oracle_attention430_tb"
INCLUDE = re.compile(r'(?m)^\s*`include "([^"]+)"\s*$')


def check_snapshot(build, replay, bundle, snapshot, end_ns):
    """Check that elaboration and simulation used the same snapshot."""
    build_lines, replay_lines = Counter(build.splitlines()), Counter(replay.splitlines())
    selected = f"\t-xmlibdirname {snapshot}"
    name = f"worklib.{BENCH}:sv"
    build_options = [line for line in build.splitlines() if line.startswith("\t-xmlibdirname ")]
    replay_options = [line for line in replay.splitlines() if line.startswith("\t-xmlibdirname ")]
    require(build_options == [selected] and all(build_lines[line] == 1 for line in (
        selected, f"\t{bundle}", f"file: {bundle}", f"\tWriting initial simulation snapshot: {name}",
    )), "Unexpected native elaboration bundle or snapshot")
    require(replay_options == [selected] and replay_lines["\t-R"] == 1
            and sum(count for line, count in replay_lines.items()
                    if line.startswith(f"Loading snapshot {name} ")) == 1,
            "Unexpected native replay snapshot")
    require(replay_lines[f"Simulation complete via $finish(1) at time {end_ns} NS + 0"] == 1
            and replay.count("Simulation complete via $finish") == 1
            and "Exiting on " in build.splitlines()[-1] and "Exiting on " in replay.splitlines()[-1],
            "Elaboration or replay did not complete")
    require(not re.search(r"\*[EF],|Simulation terminated via \$fatal", build + replay),
            "Native error during elaboration or replay")


def check_build_console(build, console, bundle):
    """Match the invocation log's compiler body to the native worker's capture."""
    first_line = f"file: {bundle}"
    tool, native = build.splitlines(), console.splitlines()
    require(first_line in tool and first_line in native, "Missing elaboration compiler output")
    native_body = [line for line in native[native.index(first_line):] if not line.startswith("mcgfe_cg(64): ")]
    require(tool[tool.index(first_line):] == native_body, "Elaboration log differs from the native capture")


def audit(candidate):
    from audit_linked_layer_memory import inventory
    from verify_tri_oracle_mapped_paper_topology import audit_memory, paper_reference

    require(__debug__, "Run the verifier with assertions enabled")
    evidence = {}

    def pin(path, expected=None):
        digest = sha(path)
        require(expected is None or digest == expected, f"Changed evidence: {path}")
        require(evidence.setdefault(str(path), digest) == digest, f"Evidence changed during audit: {path}")
        return digest

    def read(path):
        pin(path)
        return json.loads(path.read_text())

    work = candidate / "integrated_attention"
    linked, replay = map(read, (candidate / "receipt.json", work / "receipt.json"))
    require(linked["state"] == "mapped_response_address_logic_linked_with_buffered_fabric_preserved"
            and replay["state"] == "response_address_linked_netlist_preserved_archived_attention",
            "The linked candidate has no successful attention replay")
    pins = replay["input_sha256"]
    netlist = candidate / "candidate.v"
    digest = pin(netlist, pins[str(netlist)])
    require(digest == linked["candidate_sha256"] == replay["candidate_sha256"],
            "Linked netlist and replay identify different candidates")
    require(pins[str(candidate / "receipt.json")] == evidence[str(candidate / "receipt.json")],
            "The replay did not bind the selected linking receipt")

    bundle = work / "bundle.sv"
    pin(bundle, pins[str(bundle)])
    included = tuple(Path(name) for name in INCLUDE.findall(bundle.read_text()))
    require(included.count(netlist) == 1, "The native bundle must include the selected netlist once")
    for path in included:
        pin(path, pins[str(path)])

    build, run = work / "elaborate", work / "positive"
    build_status, run_status = (read(path / "native_receipt.json") for path in (build, run))
    require(build_status == replay["elaboration"] and build_status["native_exit_status"] == 0,
            "Missing successful native elaboration")
    require(run_status["native_exit_status"] == 0 and replay["replay"]["native_exit_status"] == 0,
            "Missing successful native replay")
    for folder, status in ((build, build_status), (run, run_status)):
        pin(folder / "console.log", status["log_sha256"])
    native = replay["replay"]
    for name, field in (("native_receipt.json", "raw_native_receipt"), ("console.log", "raw_console"),
                        ("xrun.log", "simulator_log")):
        path = run / name
        require(native[f"{field}_path"] == str(path), f"Wrong native replay path: {path}")
        pin(path, pins[str(path)])
    require(native["log_sha256"] == evidence[str(run / "xrun.log")]
            and native["raw_console_sha256"] == evidence[str(run / "console.log")]
            and native["raw_native_receipt_sha256"] == evidence[str(run / "native_receipt.json")],
            "Native replay receipt digests disagree")
    pin(build / "xrun.log")
    build_text = (build / "xrun.log").read_text()
    replay_text = (run / "xrun.log").read_text()
    check_snapshot(build_text, replay_text, bundle, work / "xcelium.d", replay["simulation_end_ns"])
    check_build_console(build_text, (build / "console.log").read_text(), bundle)

    reference, targets = paper_reference(pin)
    mapped = inventory(netlist.read_text(), linked["top"])
    require(len(mapped) == replay["compiled_memory_macros"], "Unexpected reachable memory count")
    check_native_census(replay_text.splitlines(), f"{BENCH}.dut.", mapped)
    memory = audit_memory({f"layer.{name}": master for name, master in mapped.items()}, included, reference, pin)
    total, label = memory["compiled_bytes"], targets["silicon"]["sram_published_KB"]
    for helper in (inventory, audit_memory, check_native_census):
        pin(Path(helper.__code__.co_filename).resolve())
    pin(Path(__file__).resolve())
    require(all(sha(path) == expected for path, expected in evidence.items()), "Evidence changed during audit")
    return {
        "state": "linked_response_address_layer_memory_independently_verified",
        "candidate_sha256": digest, "mapped_top": linked["top"], **memory,
        "paper_sram_label_kb": label, "compiled_kibibytes": total / 1024,
        "difference_from_binary_label_bytes": total - label * 1024,
        "difference_from_decimal_label_bytes": total - label * 1000,
        "scope": "Reachable compiled memory in the linked decoder layer and its native attention replay. "
                 "The paper's byte convention and memory in the complete placed chip require separate evidence.",
        "input_sha256": {str(Path(path).relative_to(ROOT)): value for path, value in evidence.items()},
    }


if __name__ == "__main__":
    resource.setrlimit(resource.RLIMIT_AS, (2**31, 2**31))
    for directory in ("wac_budgeted_parent_boundary", "shared_memory_layer_boundary",
                      "wac_core_local_outlier_v2", "shared437/aggregator_local_merge/cluster_native",
                      "wac_budgeted_parent_boundary/compact_load_transport", "wide_weight_loader"):
        sys.path.append(str(PHYSICAL / directory))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=lambda path: Path(path).resolve())
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = audit(args.candidate)
    with args.output.open("x") as stream:
        stream.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(result["state"], result["compiled_instances"], result["compiled_bytes"], flush=True)
