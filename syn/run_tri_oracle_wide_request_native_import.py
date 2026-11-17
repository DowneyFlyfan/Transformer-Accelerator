"""Validate the wide request import and run it when memory is available."""

import argparse
from collections import Counter
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

from audit_tri_oracle_placed_fanout import GIB, TOOL, memory
from tri_oracle_process_guard import terminate_process_group
from verify_tri_oracle_corrected_booth_roundtrip import ROOT, TOP, digest


SEED = Path("records/tri_oracle_wide_request_placement_seed.json")
DRIVER = Path("syn/tri_oracle_import_exact_seed.tcl")
CHECKER = Path("syn/tri_oracle_require_clean_placement.tcl")
LOCK = ROOT / ".cache/physical/carry_lookahead_comparison/placed_drive_strength/native_lane.lock"
START_BYTES = 17 * GIB


def sdc_commands(text):
    """Confirm all outgoing flit pins use the same forwarded-clock constraint."""
    lines = [line for line in text.splitlines() if line and not line.startswith("#")]
    commands = {int(bit): [] for bit in range(22)}
    for line in lines:
        match = re.search(r"\{memory_tx_data\[(\d+)\]\}", line)
        if match:
            commands[int(match[1])].append(line.replace(match[0], "{request_bit}"))
    assert set(map(len, commands.values())) == {3}, "Each of the 22 request bits needs three constraints"
    for rows in commands.values():
        assert rows == commands[0]
        assert any(line.startswith("set_load -pin_load -max") for line in rows)
        assert any(line.startswith("set_load -pin_load -min") for line in rows)
        assert any("set_output_delay -add_delay 0.2 -clock [get_clocks {pad_sample_clock}]" in line for line in rows)
    assert "create_clock [get_ports {clk}]  -name core_clock -period 1.724140 -waveform {0.000000 0.862070}" in lines
    assert "create_generated_clock -name pad_sample_clock -source [get_ports {clk}] -edges {2 3 4} [get_ports {memory_tx_clock}]" in lines
    return lines


def map_pad_sites(placements, seed):
    from prepare_tri_oracle_wide_request_placement_seed import COORDINATES, PIN
    from verify_tri_oracle_pad_cold_reload import boundary_sections

    slots = placements["pad_slots"]
    assert len(slots) == 511
    sections = boundary_sections(seed)
    count, ports = sections["PINS"]
    assert count == 498 and len(ports) == 3 * count
    assert sections["BLOCKAGES"][0] == 515
    assert {tuple(box) for _, box, _ in slots} <= set(sections["BLOCKAGES"][1])
    assigned, used = {}, set()
    for header, _, location in zip(ports[::3], ports[1::3], ports[2::3], strict=True):
        name, direction = PIN.fullmatch(header).groups()
        x, y = map(int, COORDINATES.fullmatch(location).groups()[:2])
        matches = [index for index, (_, box, _) in enumerate(slots)
                   if box[0] <= x < box[2] and box[1] <= y < box[3]]
        assert len(matches) == 1, (name, matches)
        index, = matches
        assert index not in used and name not in assigned
        used.add(index)
        edge, reservation, body = slots[index]
        axis = int(edge in ("left", "right"))
        along = (x, y)[axis]
        assert body[axis] <= along < body[axis + 2], (name, body, along)
        assigned[name] = {"edge": edge, "direction": direction, "anchor": [x, y],
                          "reservation": reservation, "pad_body": body, "slot_index": index}
    assert len(assigned) == len(used) == 498
    assert {name for name in assigned if name.startswith("memory_tx_data[")} == {
        f"memory_tx_data[{bit}]" for bit in range(22)}
    assert all(assigned[f"memory_tx_data[{bit}]"]["direction"] == "OUTPUT" for bit in range(22))
    return assigned, [index for index in range(len(slots)) if index not in used]


def binding():
    seed = json.loads(SEED.read_text())
    assert seed["state"] == "wide_request_whole_chip_placement_seed_checked"
    netlist, = (ROOT / path for path in seed["evidence_sha256"] if path.endswith("/placement_seed/candidate.v"))
    return netlist.parent / "native_import", netlist, seed


def prepare():
    from prepare_tri_oracle_booth_packet_replay import replace_once
    from prepare_tri_oracle_wide_request_placement_seed import FLOORPLAN, VIEWS
    from verify_tri_oracle_wide_request_timing import MODELS, PLACEMENT

    out, candidate, seed = binding()
    evidence = {}

    def pin(path, expected=None):
        key = str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path)
        checksum = digest(path)
        assert expected is None or checksum == expected, path
        evidence[key] = checksum
        return path

    def read(path):
        return json.loads(pin(path).read_text())

    placement, models, floorplan = (read(record) for record in (PLACEMENT, MODELS, FLOORPLAN))
    pin(SEED)
    assert floorplan["cold_netlist_sha256"] == models["cold_netlist_sha256"]
    database = ROOT / placement["database"]
    defs = pin(candidate.with_name("seed.def"), seed["evidence_sha256"][str(candidate.with_name("seed.def").relative_to(ROOT))])
    pin(candidate, seed["candidate_sha256"])
    layouts, = (ROOT / path for path in floorplan["evidence_sha256"] if path.endswith("/screened_floorplan.json"))
    pin(layouts, floorplan["evidence_sha256"][str(layouts.relative_to(ROOT))])
    mapping, supplies = map_pad_sites(json.loads(layouts.read_text()), defs)
    assert len(supplies) == 13
    std = {}
    for view in VIEWS:
        path = candidate.with_name(f"{view}.sdc")
        std[view] = sdc_commands(pin(path, seed["evidence_sha256"][str(path.relative_to(ROOT))]).read_text())
    assert std["setup_slow"] == std["setup_typ"] == std["hold_fast"]
    seed_view = candidate.with_name("setup_slow.sdc")
    defs_path = database / "viewDefinition.tcl"
    view_source = pin(defs_path, models["evidence_sha256"][str(defs_path.relative_to(ROOT))]).read_text()
    view_source = replace_once(view_source, "[file dirname [file normalize [info script]]]", f"{{{database}}}")
    view_source = replace_once(view_source, "${::IMEX::libVar}/mmmc/boundary.sdc", f"{{{seed_view}}}")
    assert all(f"-name {name} -constraint_mode functional" in view_source for name in VIEWS)
    lef = tuple(sorted((database / "libs/lef").glob("*lef")))
    assert len(lef) == 8
    for path in (*lef, DRIVER, CHECKER, LOCK):
        expected = models["evidence_sha256"][str(path.relative_to(ROOT))] if path in lef else None
        pin(path, expected)
    out.mkdir()
    views = out / "views.tcl"
    views.write_text(view_source)
    summary = {
        "top": TOP, "views": str(views), "netlist": str(candidate), "seed": str(defs),
        "database": str(out / "import/placed.db"), "placement_checker": str(ROOT / CHECKER),
        "memories": 631, "ports": 498, "blockages": 515, "components": seed["matched_component_names_and_masters"],
    }
    plan = out / "plan.tcl"
    plan.write_text("return [dict create " + " ".join(f"{key} {{{value}}}" for key, value in summary.items())
                    + " abstracts [list " + " ".join(f"{{{path}}}" for path in lef) + "]]\n")
    assignment = out / "pad_assignment.json"
    assignment.write_text(json.dumps({"signals": mapping, "unassigned_supply_slots": supplies}, indent=2, sort_keys=True) + "\n")
    for path in (plan, views, assignment, Path(__file__).resolve()):
        pin(path)
    return {
        "state": "wide_request_native_import_inputs_verified",
        "candidate_sha256": seed["candidate_sha256"], **summary,
        "signal_pads_matched_by_edge": dict(Counter(entry["edge"] for entry in mapping.values())),
        "geometric_supply_slots": len(supplies),
        "request_pin_constraints_matched_per_view": 66,
        "scope": "Every terminal anchor maps to a distinct pad reservation. Supply reservations do not assign power "
                 "or ground pad cells. All three timing views share the verified constraint body. Native import "
                 "and a fresh database reload are separate verification steps.",
        "evidence_sha256": evidence,
    }


def worker():
    assert Path("/.dockerenv").is_file() and os.environ.get("CDS_LIC_FILE")
    out, _, _ = binding()
    proof = json.loads((out / "prepared.json").read_text())
    assert proof["state"] == "wide_request_native_import_inputs_verified"
    for path in (out / "plan.tcl", out / "views.tcl", ROOT / DRIVER, ROOT / CHECKER):
        assert digest(path) == proof["evidence_sha256"][str(path.relative_to(ROOT))]
    deadline = time.monotonic() + 72 * 3600

    def ready():
        available, anonymous = memory()
        return available >= START_BYTES and anonymous <= 5 * GIB and shutil.disk_usage(out).free >= 12 * GIB

    for stage in ("import", "cold"):
        print(f"WIDE_REQUEST_NATIVE_WAIT {stage} observed={memory()} required={START_BYTES}", flush=True)
        while time.monotonic() < deadline:
            if ready():
                with LOCK.open("r") as lane:
                    try:
                        fcntl.flock(lane, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        pass
                    else:
                        if ready():
                            run_native(out, stage, proof)
                            break
            time.sleep(20)
        else:
            raise TimeoutError(f"Native start conditions remained unavailable for {stage}")


def run_native(out, stage, proof):
    folder = out / stage
    folder.mkdir()
    log = folder / "console.log"
    stem = str(folder / "innovus")
    argv = ["/usr/bin/prlimit", f"--as={22 * GIB}", "--", TOOL, "-stylus", "-no_gui", "-batch",
            "-log", stem, "-files", str(ROOT / DRIVER)]
    environment = os.environ | {"TRI_ORACLE_EXACT_SEED_PLAN": str(out / "plan.tcl"),
                                "TRI_ORACLE_EXACT_SEED_STAGE": stage}
    low, peak = memory()
    start = time.monotonic()
    stop_reason = None
    with log.open("x") as stream:
        child = subprocess.Popen(argv, cwd=folder, stdin=subprocess.DEVNULL, stdout=stream,
                                 stderr=subprocess.STDOUT, env=environment, start_new_session=True)
        print(f"WIDE_REQUEST_NATIVE_STARTED {stage} {child.pid}", flush=True)
        try:
            while child.poll() is None:
                available, anonymous = memory()
                low, peak = min(low, available), max(peak, anonymous)
                if available < 5 * GIB or anonymous >= 18 * GIB or shutil.disk_usage(out).free < 8 * GIB:
                    stop_reason = "Resource reserve reached"
                    break
                if time.monotonic() - start > 900:
                    stop_reason = "Run exceeded 900 seconds"
                    break
                time.sleep(0.5)
        finally:
            terminate_process_group(child, log_argument=stem)
    status = {"exit_status": child.returncode, "stop_reason": stop_reason, "wall_seconds": time.monotonic() - start,
              "minimum_host_available_bytes": low, "peak_container_anonymous_bytes": peak}
    (folder / "status.json").write_text(json.dumps(status, indent=2) + "\n")
    assert child.returncode == 0 and stop_reason is None, status
    assert re.search(rf"(?m)^TRI_ORACLE_EXACT_SEED_NATIVE_PASS {stage} {proof['components']} 631 498 [\d.]+$",
                     log.read_text())
    print(f"WIDE_REQUEST_NATIVE_TERMINAL {stage} {status}", flush=True)


def verify():
    from tri_oracle_artifact_fingerprint import artifact_fingerprint
    from verify_tri_oracle_booth_chip_native_connectivity import compare_netlists
    from verify_tri_oracle_booth_chip_native_layout import compare_layouts
    from verify_tri_oracle_corrected_booth_roundtrip import inspect

    out, candidate, seed = binding()
    receipt_path = out / "prepared.json"
    receipt = json.loads(receipt_path.read_text())
    assert receipt["candidate_sha256"] == seed["candidate_sha256"]
    planned_def = Path(receipt["seed"])
    for path in (candidate, planned_def, out / "plan.tcl", out / "views.tcl"):
        assert digest(path) == receipt["evidence_sha256"][str(path.relative_to(ROOT))]
    expected = Counter(" ".join(line.split()) for line in sdc_commands(candidate.with_name("setup_slow.sdc").read_text()))
    evidence, metrics = [receipt_path, candidate, planned_def], {}
    for stage in (out / "import", out / "cold"):
        files, metrics[stage.name] = inspect(stage, receipt["components"], 631, 498)
        evidence.extend((*files, stage / "layout.def"))
        for name in ("setup_slow", "setup_typ", "hold_fast"):
            sdc = stage / f"{name}.sdc"
            assert expected == Counter(" ".join(line.split()) for line in sdc_commands(sdc.read_text()))
            evidence.append(sdc)
    geometry = compare_layouts(planned_def, out / "import/layout.def", out / "cold/layout.def")
    exported = out / "cold/cold.v"
    connectivity = compare_netlists(candidate, exported, TOP, out)
    assert connectivity["physical_leaf_instances"] == receipt["components"]
    assert geometry["standard_cells"] + geometry["fixed_memory_macros"] == receipt["components"]
    fingerprint = artifact_fingerprint(Path(receipt["database"]))
    assert fingerprint["type"] == "directory"
    evidence.append(exported)
    return {
        "state": "wide_request_native_placement_and_cold_reload_verified",
        "candidate_sha256": receipt["candidate_sha256"],
        "database": receipt["database"],
        "database_fingerprint_sha256": sha256(json.dumps(fingerprint, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "native_stages": metrics, "geometry": geometry, "connectivity": connectivity,
        "scope": "Native import and independent cold reload with placement, connectivity and constraint checks.",
        "evidence_sha256": {str(path.relative_to(ROOT)): digest(path) for path in evidence},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "worker", "verify"))
    args = parser.parse_args()
    assert __debug__ and Path.cwd() == ROOT
    if args.phase == "prepare":
        assert not Path("/.dockerenv").is_file()
        receipt = prepare()
        output, _, _ = binding()
        (output / "prepared.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        print(output)
    elif args.phase == "worker":
        worker()
    else:
        assert not Path("/.dockerenv").is_file()
        print(json.dumps(verify(), indent=2, sort_keys=True))
