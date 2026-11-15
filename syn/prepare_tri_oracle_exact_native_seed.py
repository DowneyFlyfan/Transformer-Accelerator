"""Bind the localized whole-chip coordinates to the native timing deck."""

import argparse
import json
import mmap
from pathlib import Path
import subprocess

from audit_tri_oracle_placed_chip_boundary import digest
from check_tri_oracle_paper300_gate import dimensions
from link_tri_oracle_indexed_whole_chip import TOP, module_at, spans
from prepare_tri_oracle_dual_group_placement_seed import check_boundary, top_ports
from scan_tri_oracle_dual_group_halos import read
from verify_tri_oracle_joined_placed_constraints import parse_sdc


SEED_RECORD = Path("records/tri_oracle_bounded_decoder_localized_seed.json")
NATIVE_RECIPE = Path("syn/tri_oracle_import_exact_seed.tcl")
CHECK_PLACEMENT = Path("syn/tri_oracle_require_clean_placement.tcl")
VIEWS = ("setup_slow", "setup_typ", "hold_fast")


def tcl_literal(value):
    value = str(value)
    if any(mark in value for mark in "{}\\\r\n"):
        raise ValueError(f"Unsafe Tcl plan value: {value!r}")
    return "{" + value + "}"


def write_plan(output, values, abstracts):
    fields = " ".join(f"{key} {tcl_literal(value)}" for key, value in values.items())
    lefs = " ".join(tcl_literal(path) for path in abstracts)
    with output.open("x") as stream:
        stream.write(f"return [dict create {fields} abstracts [list {lefs}]]\n")


def prepare(candidate, seed, deck, output):
    seed_record = read(SEED_RECORD)
    deck_record_path = deck / "verified.json"
    inherited = read(deck_record_path)
    inherited_timing = deck / "views.tcl"
    deck_check = deck / "check_views.tcl"
    inputs = {name: digest(Path(name)) for name in inherited["evidence_sha256"]}
    assert inputs == inherited["evidence_sha256"]
    files = [Path(name).resolve() for name in inputs]
    abstracts = sorted((path for path in files if path.suffix == ".tlef"))
    abstracts += sorted(path for path in files if path.suffix == ".lef")
    assert len(abstracts) == inherited["physical_abstracts"] == 8
    assert sum(path.suffix == ".lib" for path in files) == inherited["libraries"] == 21
    assert inherited["extraction_models"] == 3
    old_sdc, = (path for path in files if path.suffix == ".sdc")
    assert old_sdc.name == "candidate.sdc"
    reference_views = {path.stem: path for name, expected in seed_record["evidence_sha256"].items()
                       if (path := Path(name)).suffix == ".sdc" and digest(path) == expected}
    assert reference_views.keys() == set(VIEWS)
    # The inherited native deck uses one common constraint mode. Use its
    # verified expanded constraints so the port and edge values can be audited.
    common_sdc = reference_views["setup_typ"].resolve()
    text = {view: path.read_text().replace("-name core ", "-name core_clock ").replace(
        "[get_clocks {core}]", "[get_clocks {core_clock}]") for view, path in reference_views.items()}
    parsed = parse_sdc(text["setup_typ"])
    assert all(parse_sdc(raw) == parsed for raw in text.values())
    evidence = {str(path): digest(path) for path in (candidate, seed, SEED_RECORD, NATIVE_RECIPE, CHECK_PLACEMENT,
                                                     deck_record_path, deck_check, Path(__file__), *reference_views.values())}
    assert evidence[str(candidate)] == seed_record["candidate_sha256"]
    assert evidence[str(seed)] == seed_record["coordinate_seed_sha256"]
    assert dimensions(seed) == tuple(seed_record["die_mm"]) == (3.6, 3.6)
    with candidate.open("rb") as file, mmap.mmap(file.fileno(), 0, access=mmap.ACCESS_READ) as contents:
        ports = top_ports(module_at(contents, spans(contents), TOP))
    boundary, count_by_view = check_boundary(seed, reference_views, ports)
    assert count_by_view == seed_record["boundary_timing_constraints_by_view"]
    assert boundary["PINS"][0] == seed_record["untouched_boundary_pins"] == len(ports)
    assert boundary["BLOCKAGES"][0] == seed_record["unchanged_boundary_blockages"] == 4
    output.mkdir()
    contents = inherited_timing.read_text()
    original_reference = "${::IMEX::libVar}/mmmc/candidate.sdc"
    assert contents.count(original_reference) == 1
    timing = output / "views.tcl"
    with timing.open("x") as stream:
        stream.write(contents.replace(original_reference, tcl_literal(common_sdc)))
    assert subprocess.run(["tclsh", str(deck_check), str(timing)], check=True, capture_output=True, text=True
                          ).stdout.strip() == "WIDENED_TIMING_DECK_REFERENCES_VERIFIED"
    evidence[str(timing)] = digest(timing)
    plan = output / "plan.tcl"
    write_plan(plan, {
        "top": TOP, "views": timing.resolve(), "netlist": candidate.resolve(), "seed": seed.resolve(),
        "database": (output / "import/placed.db").resolve(), "placement_checker": CHECK_PLACEMENT.resolve(),
        "memories": seed_record["unchanged_fixed_macros"], "ports": len(ports),
        "blockages": boundary["BLOCKAGES"][0], "components": seed_record["physical_component_count"],
    }, abstracts)
    result = {
        "state": "exact_seed_native_input_plan_prepared",
        "candidate_sha256": evidence[str(candidate)],
        "seed_sha256": evidence[str(seed)],
        "die_mm": seed_record["die_mm"], "components": seed_record["physical_component_count"],
        "placement_plan_sha256": digest(plan), "constraint_entries_by_view": count_by_view,
        "physical_abstracts": len(abstracts), "timing_libraries": 21, "extraction_models": 3,
        "evidence_sha256": evidence | inputs,
        "scope": "Exact native import inputs. The candidate-bound whole-chip replay, native placement and timing "
                 "evidence are required before judging the corresponding design stages.",
    }
    with (output / "prepared.json").open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print("TRI_ORACLE_EXACT_SEED_NATIVE_PLAN_PREPARED", result["candidate_sha256"], result["components"], flush=True)


def main():
    assert __debug__ and Path("/.dockerenv").is_file()
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("candidate", "seed", "deck", "output"):
        parser.add_argument(arg, type=Path)
    args = parser.parse_args()
    prepare(args.candidate, args.seed, args.deck, args.output)


if __name__ == "__main__":
    main()
