"""Recheck the full production models used to import and reload the Booth placement."""

from collections import Counter
from hashlib import file_digest, sha256
import json
from pathlib import Path
import re

from tri_oracle_artifact_fingerprint import artifact_fingerprint

ROOT = Path(__file__).resolve().parents[1]
PLACEMENT = Path("records/tri_oracle_corrected_booth_placement_roundtrip.json")
INPUTS = Path("records/tri_oracle_booth_chip_native_inputs.json")
MEMORY = Path("records/tri_oracle_booth_compiled_memory.json")
CORNERS = {
    "slow": ("ssg0p9v125c", "setup_slow", "qrc_rcworst", 125),
    "typ": ("tt1v25c", "setup_typ", "qrc_typical", 25),
    "fast": ("ffg1p05vm40c", "hold_fast", "qrc_rcbest", -40),
}
PREFIX = "${::IMEX::libVar}/mmmc/"


def digest(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def source_inventory(native_input):
    expected = {}
    for path, checksum in native_input["evidence_sha256"].items():
        file = Path(path)
        if file.suffix in {".lib", ".lef", ".tlef"} or file.name.startswith("qrc_"):
            assert file.name not in expected, file
            expected[file.name] = (file, checksum)
    counts = Counter(Path(name).suffix for name in expected)
    assert counts == Counter({".lib": 21, ".lef": 7, ".tlef": 1, "": 3})
    return expected


def view_inventory(view, expected):
    text = view.read_text().replace("\\\n", " ")
    lines = [" ".join(line.split()) for line in text.splitlines()]
    observed = {}
    for kind, (suffix, name, rcfile, temperature) in CORNERS.items():
        (packet,) = [
            line
            for line in lines
            if line.startswith(f"create_library_set -name ls_{kind} ")
        ]
        assert packet.startswith(f"create_library_set -name ls_{kind} -timing [list ")
        assert packet.endswith("]")
        assembled = packet.split("[list ", 1)[1].removesuffix("]").split()
        assert all(
            entry.startswith(PREFIX) and "/" not in entry.removeprefix(PREFIX)
            for entry in assembled
        )
        wanted = {key for key in expected if key.endswith(f"{suffix}.lib")}
        assert len(assembled) == len(wanted) == 7
        assert {entry.removeprefix(PREFIX) for entry in assembled} == wanted
        assert (
            f"create_timing_condition -name tc_{kind} -library_sets [list ls_{kind}]"
            in lines
        )
        assert (
            f"create_delay_corner -name dc_{kind} -timing_condition {{tc_{kind}}} -rc_corner rc_{kind}"
            in lines
        )
        assert (
            f"create_analysis_view -name {name} -constraint_mode functional -delay_corner dc_{kind}"
            in lines
        )
        (rc,) = [
            line
            for line in lines
            if line.startswith(f"create_rc_corner -name rc_{kind} ")
        ]
        assert rc.endswith(
            f"-temperature {temperature} -qrc_tech {PREFIX}rc_{kind}/{rcfile}"
        )
        observed[kind] = sorted(wanted)
    assert (
        lines.count(
            "set_analysis_view -setup [list setup_slow setup_typ] -hold [list hold_fast]"
        )
        == 1
    )
    return observed


def check_load(log, libs, lefs):
    text = log.read_text()
    if re.search(r"(?m)^\*\*?ERROR:", text):
        raise ValueError(f"Native model loading reported an error in {log}")
    actual_libs = [
        (kind, Path(file).name)
        for kind, file in re.findall(
            r"(?m)^Reading ls_(\w+) timing library (.+\.lib)\.\s*$", text
        )
    ]
    assert set(actual_libs) == {
        (kind, lib) for kind, names in libs.items() for lib in names
    }
    actual_abstracts = {
        Path(file).name
        for file in re.findall(
            r"(?m)^Loading LEF file (.+?\.(?:tlef|lef))\s+\.\.\.", text
        )
    }
    assert actual_abstracts == lefs


def verify():
    evidence = {}

    def pin(path, expected=None):
        key = digest(path)
        assert expected is None or key == expected, path
        evidence[str(path)] = key

    pin(PLACEMENT)
    placed = json.loads(PLACEMENT.read_text())
    assert (
        placed["state"] == "corrected_booth_placement_reload_and_connectivity_verified"
    )
    pin(INPUTS, placed["evidence_sha256"][str(INPUTS)])
    native_input = json.loads(INPUTS.read_text())
    pin(MEMORY)
    memory = json.loads(MEMORY.read_text())
    database = Path(placed["database"])
    fingerprint = artifact_fingerprint(database)
    encoded = json.dumps(fingerprint, sort_keys=True, separators=(",", ":")).encode()
    database_hash = sha256(encoded).hexdigest()
    assert database_hash == placed["database_fingerprint_sha256"]
    expected = source_inventory(native_input)
    paths = {}
    for file in (database / "libs").rglob("*"):
        if file.is_dir() or file.suffix == ".sdc":
            continue
        assert file.is_file() and file.name not in paths, file
        paths[file.name] = file
    assert paths.keys() == expected.keys()
    for name, (file, key) in expected.items():
        pin(file, key)
        pin(paths[name], key)

    view = database / "viewDefinition.tcl"
    pin(view)
    libs = view_inventory(view, expected)
    lefs = {name for name in expected if name.endswith((".lef", ".tlef"))}
    stage = database.parents[1]
    for phase in ("import", "cold"):
        log = stage / phase / "console.log"
        pin(log, placed["evidence_sha256"][str(log)])
        check_load(log, libs, lefs)
    linked = str(stage / "linked.v")
    assert memory["evidence_sha256"][linked] == placed["evidence_sha256"][linked]
    assert memory["macro_count"] == placed["geometry"]["fixed_memory_macros"] == 631
    pin(Path(__file__).resolve().relative_to(ROOT))
    return {
        "state": "corrected_booth_full_models_loaded_from_pinned_sources",
        "database_fingerprint_sha256": database_hash,
        "cold_netlist_sha256": placed["evidence_sha256"][str(stage / "cold/cold.v")],
        "linked_netlist_sha256": placed["evidence_sha256"][linked],
        "compiled_memory_instances": memory["macro_count"],
        "liberty_models_by_corner": libs,
        "physical_abstracts": sorted(lefs),
        "resistance_capacitance_technology_files": [
            fields[2] for fields in CORNERS.values()
        ],
        "scope": "Import and cold-reload logs and database model bytes match the selected full TSMC libraries for all three corners. This verifies model identity and loading. Timing slack remains a separate measurement.",
        "evidence_sha256": evidence,
    }


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    print(json.dumps(verify(), indent=2, sort_keys=True))
