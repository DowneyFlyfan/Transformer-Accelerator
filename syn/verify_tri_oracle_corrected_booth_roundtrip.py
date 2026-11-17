"""Verify the corrected Booth chip after Innovus finishes both reload stages."""

from argparse import ArgumentParser
from collections import Counter
import json
from pathlib import Path
import re
from hashlib import file_digest, sha256

from tri_oracle_artifact_fingerprint import artifact_fingerprint

ROOT = Path(__file__).resolve().parents[1]
WORK = Path(
    ".cache/physical/whole_chip_xcelium_speed/booth_joined_chip/native_glue/retry"
)
NATIVE = WORK.parents[1] / "native_reload"
TOP = "tri_oracle_chip_credited_request"
RECORD = Path("records/tri_oracle_booth_native_glue.json")
INPUTS = Path("records/tri_oracle_booth_chip_native_inputs.json")
SDC = re.compile(
    r"^(set_(?:input_delay|output_delay|load|input_transition)|create_(?:generated_)?clock)\s"
)


def digest(path):
    with path.open("rb") as source:
        return file_digest(source, "sha256").hexdigest()


def read(path):
    return json.loads(path.read_text())


def constraints(path):
    lines = path.read_text().splitlines()
    assert lines.count(f"current_design {TOP}") == 1
    statements = Counter(" ".join(line.split()) for line in lines if SDC.match(line))
    kinds = Counter()
    for statement, count in statements.items():
        kinds[statement.split()[0]] += count
    assert kinds["create_clock"] == kinds["create_generated_clock"] == 1
    assert kinds["set_input_delay"] + kinds["set_output_delay"] == 937
    return statements


def preflight():
    from verify_tri_oracle_booth_chip_native_layout import metadata_sections

    record = read(RECORD)
    base = read(INPUTS)
    source = WORK / "linked.v"
    seed = WORK / "seed.def"
    for path in (source, seed, WORK / "plan.tcl"):
        assert digest(path) == record["evidence_sha256"][str(path)]
    header, rows, sections = metadata_sections(seed)
    assert b"DIEAREA ( 0 0 ) ( 7200000 7200000 ) ;" in header
    assert len(rows) == 2966
    assert {key: len(value) for key, value in sections.items()} == {
        "PINS": base["ports"],
        "BLOCKAGES": base["placement_blockages"],
        "REGIONS": 20,
        "GROUPS": 20,
    }
    for view in base["analysis_views"]:
        fixture = NATIVE / "timing_fixture" / f"{view}.sdc"
        assert digest(fixture) == base["evidence_sha256"][str(fixture)]
        constraints(fixture)
    return source, seed, base, record


def inspect(stage, count, macros, pins):
    log = stage / "console.log"
    status = stage / "status.json"
    result = read(status)
    assert result["exit_status"] == 0 and result["stop_reason"] is None, result
    text = log.read_text()
    assert re.search(
        rf"(?m)^TRI_ORACLE_EXACT_SEED_NATIVE_PASS {stage.name} {count} {macros} {pins} [\d.]+$",
        text,
    )
    assert not re.search(r"(?m)^\*\*?ERROR:|Started Early Global Route", text)
    report = stage / "placement.rpt"
    placement = report.read_text()
    assert re.search(r"(?m)^\*info: Unplaced = 0\s*$", placement)
    (density,) = re.findall(r"(?m)^Placement Density:([\d.]+)%", placement)
    return (log, status, report), {
        "density_percent": float(density),
        "wall_seconds": result["wall_seconds"],
    }


def verify():
    from verify_tri_oracle_booth_chip_native_connectivity import compare_netlists
    from verify_tri_oracle_booth_chip_native_layout import compare_layouts

    source, seed, base, record = preflight()
    paths = [
        RECORD,
        INPUTS,
        source,
        seed,
        WORK / "plan.tcl",
        Path(__file__).resolve().relative_to(ROOT),
    ]
    assert record["logical_top"] == TOP
    metrics = {}
    count = record["placement_leaves"]
    macros = record["fixed_macros"]
    imports, cold = WORK / "import", WORK / "cold"
    for stage in (imports, cold):
        files, timing = inspect(stage, count, macros, base["ports"])
        paths.extend(files)
        metrics[stage.name] = timing
        for view in base["analysis_views"]:
            expected = NATIVE / "timing_fixture" / f"{view}.sdc"
            observed = stage / f"{view}.sdc"
            assert constraints(observed) == constraints(expected), (stage, view)
            paths.extend((expected, observed))
    placed, reloaded = imports / "layout.def", cold / "layout.def"
    paths.extend((placed, reloaded))
    geometry = compare_layouts(seed, placed, reloaded)
    assert geometry["standard_cells"] + geometry["fixed_memory_macros"] == count
    assert geometry["fixed_memory_macros"] == macros
    assert geometry["signal_terminals"] == base["ports"]
    netlist = cold / "cold.v"
    paths.append(netlist)
    connectivity = compare_netlists(source, netlist, TOP, WORK)
    assert connectivity["physical_leaf_instances"] == count
    database = imports / "placed.db"
    fingerprint = artifact_fingerprint(database)
    assert fingerprint["type"] == "directory"
    database_hash = sha256(
        json.dumps(fingerprint, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return dict(
        state="corrected_booth_placement_reload_and_connectivity_verified",
        top=TOP,
        native_stages=metrics,
        port_delay_constraints_per_view=base[
            "native_fixture_delay_constraints_per_view"
        ],
        die_dimensions_mm=[3.6, 3.6],
        database=str(database),
        database_fingerprint_sha256=database_hash,
        geometry=geometry,
        connectivity=connectivity,
        views=base["analysis_views"],
        scope="Placement export, cold reload, connectivity, and boundary constraints. Post-placement timing and routing are separate.",
        evidence_sha256={str(path): digest(path) for path in paths},
    )


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--preflight", action="store_true")
    if parser.parse_args().preflight:
        preflight()
        print("CORRECTED_CHIP_ROUNDTRIP_VERIFICATION_INPUTS_PASS")
    else:
        print(json.dumps(verify(), sort_keys=True, indent=2))
