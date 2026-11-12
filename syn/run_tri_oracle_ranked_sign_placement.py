"""Place the verified ranked predictor and reload its estimated interconnect."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import time

from check_tri_oracle_paper300_gate import dimensions
from prepare_tri_oracle_packed_sign_predictor import ROOT, sha
from tri_oracle_artifact_fingerprint import artifact_fingerprint
from tri_oracle_native_diagnostics import require_clean_native
from tri_oracle_process_guard import terminate_process_group


GIB = 2**30
PHYSICAL = ROOT / ".cache/physical"
MAPPING = PHYSICAL / "ranked_sign_slots/mapped_predictor_32"
TOP = "tri_oracle_packed_outlier_replay_CORE_STRIP_PREDICTOR1"
RECIPE = ROOT / "syn/tri_oracle_place_ranked_sign_predictor.tcl"
CHECKER = ROOT / "syn/tri_oracle_require_clean_placement.tcl"
CORNERS = (
    ("setup_slow", "slow", "ssg0p9v125c", "rcworst", 125),
    ("setup_typ", "typ", "tt1v25c", "typical", 25),
    ("hold_fast", "fast", "ffg1p05vm40c", "rcbest", -40),
)
COMPILERS = (
    ("core_weights_masks_01", "ts5n28hpcpsvta32x128m2fw_130a"),
    ("activation_cache_banks_01", "ts5n28hpcpsvta512x64m4f_130a"),
)


def read(path):
    return json.loads(path.read_text())


def word(path):
    return "{" + str(path) + "}"


def prepare_text(path, text):
    if path.exists():
        assert path.read_text() == text, path
    else:
        path.write_text(text)


def prepare(output, pin):
    libraries = PHYSICAL / "library"
    compilers = [PHYSICAL / "sram" / family / name for family, name in COMPILERS]
    technology = (PHYSICAL / "routing_kit/N28_PRTF_Cad_v1d5a/PR_tech/Cadence/LefHeader/VHV"
                  / "tsmcn28_10lm5X2Y2ZUTRDL.tlef")
    lefs = [technology, libraries / "tcbn28hpcplusbwp12t40p140.lef"]
    lefs += [path / "LEF" / f"{path.name}.lef" for path in compilers]
    constraint, netlist = (MAPPING / name for name in ("constraints.sdc", "netlist.v"))
    mmmc = output / "timing.tcl"
    lines = []
    for view, corner, library, rc_file, temperature in CORNERS:
        models = [libraries / f"tcbn28hpcplusbwp12t40p140{library}.lib"]
        models += [path / "NLDM" / f"{path.name}_{library}.lib" for path in compilers]
        rc = PHYSICAL / "rc" / f"qrc_{rc_file}"
        for path in (*models, rc):
            pin(path)
        lines.extend((
            f"create_library_set -name ls_{corner} -timing [list {' '.join(map(word, models))}]",
            f"create_rc_corner -name rc_{corner} -qrc_tech {word(rc)} -temperature {temperature}",
            f"create_timing_condition -name tc_{corner} -library_sets {{ls_{corner}}}",
            f"create_delay_corner -name dc_{corner} -timing_condition tc_{corner} -rc_corner rc_{corner}",
        ))
    lines.append(f"create_constraint_mode -name functional -sdc_files [list {word(constraint)}]")
    lines.extend(f"create_analysis_view -name {view} -constraint_mode functional -delay_corner dc_{corner}"
                 for view, corner, *_ in CORNERS)
    lines.append("set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}")
    prepare_text(mmmc, "\n".join(lines) + "\n")
    manifest = output / "inputs.tcl"
    prepare_text(manifest, f"""return [dict create \
    top {TOP} out {word(output)} checker {word(CHECKER)} \
    netlist {word(netlist)} mmmc {word(mmmc)} lefs [list {' '.join(map(word, lefs))}]]
""")
    for path in (RECIPE, CHECKER, manifest, mmmc, netlist, constraint, *lefs):
        pin(path)
    return manifest


def completed_native(folder, pin):
    console, status = (folder / name for name in ("console.log", "native_receipt.json"))
    native = read(status)
    assert native["native_exit_status"] == 0 and native["guard_stop"] is None, (folder, native)
    log = console.read_text()
    require_clean_native(log)
    for path in (console, status, folder / "macro_poses.tsv", folder / "placement.rpt"):
        pin(path)
    return log


def native(output, stage, manifest, pin):
    from run_tri_oracle_parallel_chip_synthesis import memory

    available, anonymous = memory()
    assert available >= 16 * GIB and anonymous <= 3 * GIB, (available, anonymous)
    assert os.environ.get("CDS_LIC_FILE") and os.environ.get("USER")
    folder = output / stage
    folder.mkdir()
    stem = folder / "native"
    address_space = (16 if stage == "report" else 8) * GIB
    argv = ["/usr/bin/prlimit", f"--as={address_space}", "--", "/opt/cadence/INNOVUS251/bin/innovus",
            "-stylus", "-no_gui", "-batch", "-log", str(stem), "-files", str(RECIPE)]
    env = os.environ | {"TRI_RANKED_PHYSICAL_INPUTS": str(manifest), "TRI_RANKED_PHYSICAL_STAGE": stage}
    start = time.monotonic()
    console = folder / "console.log"
    stop = None
    with console.open("x") as stream:
        proc = subprocess.Popen(argv, cwd=folder, env=env, stdout=stream, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, start_new_session=True)
        print("RANKED_PREDICTOR_INNOVUS", stage, proc.pid, flush=True)
        try:
            while proc.poll() is None:
                available, anonymous = memory()
                if available < 14 * GIB or anonymous > 6 * GIB or time.monotonic() - start > 1200:
                    stop = (available, anonymous)
                    break
                time.sleep(0.5)
        finally:
            terminate_process_group(proc, log_argument=str(stem))
    stats = {"argv": argv, "pid": proc.pid, "elapsed_seconds": time.monotonic() - start,
             "native_exit_status": proc.returncode, "guard_stop": stop}
    status = folder / "native_receipt.json"
    status.write_text(json.dumps(stats, indent=2) + "\n")
    return completed_native(folder, pin)


def timing_summary(path, view):
    text = path.read_text()
    checks = re.findall(r"(?m)^Path (\d+): (MET|VIOLATED) \((-?\d+\.\d+) ns\)", text)
    assert len(checks) == 15 and [int(item[0]) for item in checks] == list(range(1, 16))
    assert re.findall(r"(?m)^\s*View: (\w+)\s*$", text) == [view] * 15
    slacks = [float(slack) for _, _, slack in checks]
    assert all((slack >= 0) == (state == "MET") for (_, state, _), slack in zip(checks, slacks, strict=True))
    assert sorted(slacks) == slacks
    start, end = (re.search(rf"(?m)^\s*{field}: \([RF]\) (\S+)", text)[1]
                  for field in ("Startpoint", "Endpoint"))
    return {"worst_slack_ns": slacks[0], "reported_paths": len(checks),
            "violating_paths": sum(slack < 0 for slack in slacks), "startpoint": start, "endpoint": end}


def run(output, resume_report):
    from check_linked_tsmc_split_extraction import count_nets
    from measure_compact_placed_timing import annotated_nets
    from verify_linked_bank_buffer_export import verify as verify_topology

    record_path = ROOT / "records/wac_ranked_sign_predictor_mapped_result.json"
    record = read(record_path)
    assert record["state"] == "ranked_sign_predictor_mapped_timing_and_gate_replay_verified"
    pins = record["evidence_sha256"].copy()

    def pin(path):
        name, digest = str(path.relative_to(ROOT)), sha(path)
        assert pins.setdefault(name, digest) == digest, name

    assert all(sha(ROOT / name) == digest for name, digest in pins.items())
    for path in (record_path, Path(__file__).resolve(), Path(verify_topology.__code__.co_filename).resolve(),
                 Path(count_nets.__code__.co_filename).resolve(), Path(annotated_nets.__code__.co_filename).resolve()):
        pin(path)
    if resume_report:
        assert output.is_dir() and not (output / "receipt.json").exists() and not (output / "report").exists()
    else:
        output.mkdir()
    manifest = prepare(output, pin)
    log = completed_native(output / "place", pin) if resume_report else native(output, "place", manifest, pin)
    assert log.splitlines().count("RANKED_PREDICTOR_PLACED") == 1
    placed = output / "place"
    topological = verify_topology((MAPPING / "netlist.v").read_text(), (placed / "placed.v").read_text(), TOP)
    count, density = re.search(r"(?m)^RANKED_PREDICTOR_PLACEMENT (\d+) ([0-9.]+)$", log).groups()
    assert topological[2] == int(count) == record["mapped_cell_count"]
    assert dimensions(placed / "placed.def") == (0.41, 0.32)
    poses = set((placed / "macro_poses.tsv").read_text().splitlines())
    assert len(poses) == 6
    for path in (placed / "placed.v", placed / "placed.def", placed / "area.rpt"):
        pin(path)
    checkpoint = artifact_fingerprint(placed / "placed.db")
    reports = {}
    for stage in ("extract", "report"):
        log = (completed_native(output / stage, pin) if resume_report and stage == "extract"
               else native(output, stage, manifest, pin))
        assert log.splitlines().count("RANKED_PREDICTOR_TIMING_MODE single false") == 1
        assert set((output / stage / "macro_poses.tsv").read_text().splitlines()) == poses
        assert artifact_fingerprint(placed / "placed.db") == checkpoint
        if stage == "extract":
            assert "PreRoute RC Extraction DONE" in log
        for view, *_ in CORNERS:
            assert log.splitlines().count(f"RANKED_PREDICTOR_{'EXTRACTED' if stage == 'extract' else 'REPORTED'} {view}") == 1
    for view, *_ in CORNERS:
        timing, annotation = (output / "report" / name for name in (f"{view}.rpt", f"{view}_annotation.rpt"))
        spef = output / "extract" / f"{view}.spef"
        for path in (timing, annotation, spef):
            pin(path)
        nets = count_nets(spef, TOP)
        assert annotated_nets(annotation) == nets, view
        reports[view] = timing_summary(timing, view) | {"estimated_annotated_nets": nets}
    assert all(sha(ROOT / name) == digest for name, digest in pins.items())
    result = {
        "state": "ranked_predictor_geometric_placement_and_preroute_timing_verified",
        "die_millimeters": [0.41, 0.32], "fixed_compiled_memories": len(poses), "placed_instances": int(count),
        "placement_density_percent": float(density), "clock_target_megahertz": 580, "estimated_timing": reports,
        "placed_database": checkpoint, "input_sha256": pins,
        "scope": "Native placement and cold reloaded interconnect estimates for a predictor block with an ideal clock.",
    }
    (output / "receipt.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(result["state"], reports, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=lambda path: Path(path).resolve())
    parser.add_argument("--resume-report", action="store_true")
    args = parser.parse_args()
    run(args.output, args.resume_report)
