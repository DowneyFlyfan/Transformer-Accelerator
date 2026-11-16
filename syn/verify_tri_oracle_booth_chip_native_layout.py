"""Compare the placement seed with Innovus' initial and cold-reload exports."""

import argparse
from collections import Counter
from hashlib import sha256
import json
from mmap import ACCESS_READ, mmap
from pathlib import Path
import re
import struct

from plan_tri_oracle_bonded_pad_recovery import section
from prepare_tri_oracle_booth_chip_native import NATIVE
from verify_tri_oracle_booth_chip_link import TOP, WORK
from verify_tri_oracle_gated_compute_array import ROOT, digest, read
from verify_tri_oracle_pad_cold_reload import components

PREVIOUS = Path("records/tri_oracle_repacked_whole_chip_cold_reload.json")
INPUTS = Path("records/tri_oracle_booth_chip_native_inputs.json")
RELOAD_VIEWS = ("setup_slow", "setup_typ", "hold_fast")
POSE = struct.Struct("<ii4i")
ZERO_HALO = (0, 0, 0, 0)


def pose_fingerprint(path):
    """Compare each name, master, status, coordinate, orientation, and halo."""
    checksum = 0
    counts = Counter()
    for name, (master, status, x, y, rotation, halo) in components(path):
        fields = (
            name.replace(b"\\", b""),
            master.encode(),
            status.encode(),
            rotation.encode(),
            POSE.pack(x, y, *(halo or ZERO_HALO)),
        )
        checksum += int.from_bytes(sha256(b"\0".join(fields)).digest(), "big")
        counts[status] += 1
    assert counts["PLACED"] > 0 and counts.total() > counts["PLACED"]
    return counts, f"{checksum % (1 << 256):064x}"


def metadata_sections(path):
    with (
        path.open("rb") as stream,
        mmap(stream.fileno(), 0, access=ACCESS_READ) as data,
    ):
        end = data.find(b"\nCOMPONENTS ")
        assert end > 0
        head = data[:end]
        shape = re.findall(rb"(?m)^(?:DESIGN|UNITS|DIEAREA) [^;]+;", head)
        assert len(shape) == 3
        rows = re.findall(rb"(?m)^ROW\s+[^;]+;", head)
        assert rows

        result = {}
        for key in (b"PINS", b"BLOCKAGES", b"REGIONS", b"GROUPS"):
            text = section(data, key)
            records = tuple(
                sorted(
                    " ".join(item.split()) for item in re.split(r"(?m)^\s*- ", text)[1:]
                )
            )
            count = re.search(rb"\n" + key + rb" (\d+) ;", data)
            assert (
                count
                and int(count[1]) == len(records)
                and len(records) == len(set(records))
            ), key
            result[key.decode()] = records
    return (
        tuple(b" ".join(statement.split()) for statement in shape),
        tuple(sorted(b" ".join(row.split()) for row in rows)),
        result,
    )


def compare_layouts(seed, original_import, cold_export):
    wanted_poses, wanted_hash = pose_fingerprint(seed)
    header, rows, sections = metadata_sections(seed)
    for layout in (original_import, cold_export):
        assert pose_fingerprint(layout) == (wanted_poses, wanted_hash), (
            layout,
            "Instance positions",
        )
        observed_header, observed_rows, observed_sections = metadata_sections(layout)
        assert observed_header == header and observed_rows == rows, (
            layout,
            "Die or row grid",
        )
        for key, value in observed_sections.items():
            assert value == sections[key], (layout, key, len(value), len(sections[key]))
    return {
        "pose_sha256_sum": wanted_hash,
        "standard_cells": wanted_poses["PLACED"],
        "fixed_memory_macros": wanted_poses["FIXED"],
        "placement_rows": len(rows),
        "signal_terminals": len(sections["PINS"]),
        "placement_blockages": len(sections["BLOCKAGES"]),
        "regions": len(sections["REGIONS"]),
        "groups": len(sections["GROUPS"]),
    }


def fixture_paths():
    record = read(PREVIOUS)
    (view,) = (
        Path(name)
        for name in record["evidence_sha256"]
        if name.endswith("/viewDefinition.tcl")
    )
    directory = view.parents[2]
    assert digest(view) == record["evidence_sha256"][str(view)]
    seed = directory.parent / "seed.def"
    assert digest(seed) == record["seed_sha256"]
    return seed, directory


def verify(previous=False):
    if previous:
        seed, output = fixture_paths()
        expected = (3859878, 631, 7945, 4)
        top = "tri_oracle_chip_command_layer_parallel_chip"
    else:
        seed, output = WORK / "placement_with_terminal_seed.def", NATIVE
        inputs = read(INPUTS)
        assert digest(seed) == inputs["evidence_sha256"][str(seed)]
        expected = (
            inputs["physical_components"],
            631,
            inputs["ports"],
            inputs["placement_blockages"],
        )
        top = TOP
    layout = output / "import/layout.def"
    cold = output / "cold/layout.def"
    facts = compare_layouts(seed, layout, cold)
    cells, macros, pins, blockages = expected
    assert (
        facts["standard_cells"] == cells - macros
        and facts["fixed_memory_macros"] == macros
    )
    assert (
        facts["signal_terminals"] == pins and facts["placement_blockages"] == blockages
    )
    assert facts["placement_rows"] == 2966 and facts["regions"] == facts["groups"] == 20
    for stage in ("import", "cold"):
        status = read(output / stage / "status.json")
        assert status["exit_status"] == 0 and status["stop_reason"] is None
        console = (output / stage / "console.log").read_text()
        assert re.search(
            rf"(?m)^TRI_ORACLE_EXACT_SEED_NATIVE_PASS {stage} {cells} {macros} {pins} [\d.]+$",
            console,
        )
        assert not re.search(r"(?m)^\*\*?ERROR:|Started Early Global Route", console)
    return {
        **facts,
        "top": top,
        "state": "native_import_and_cold_reload_match_placement_seed",
        "scope": "Die, rows, component positions, memory halos, signal terminals, blockages, and groups agree across both exports. Connectivity and static timing are checked separately.",
        "evidence_sha256": {
            str(path): digest(path)
            for path in (seed, layout, cold, Path(__file__).resolve().relative_to(ROOT))
        },
    }


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predecessor", action="store_true")
    print(json.dumps(verify(parser.parse_args().predecessor), indent=2, sort_keys=True))
