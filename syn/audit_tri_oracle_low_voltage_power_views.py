"""Verify a common low-voltage power library set for the joined chip."""

import argparse
from decimal import Decimal
from hashlib import file_digest
import json
from pathlib import Path
import re
import shutil
import tarfile


ROOT = Path(__file__).resolve().parents[1]
CORNER = "ssg0p81v125c"
REFERENCE = "ssg0p9v125c"
FAMILY = "tcbn28hpcplusbwp12t40p140"
CELL = re.compile(r"^\s*cell\s*\(\s*\"?(\w+)\"?\s*\)")
INTERNAL = re.compile(r"^\s*internal_power\s*\(")
LEAKAGE = re.compile(r"^\s*(?:leakage_power\s*\(|cell_leakage_power\s*:)")
SINGLE_SUPPLY = re.compile(rf"{FAMILY}((?:ssg|tt|ffg)(\d+(?:p\d+)?)vm?\d+c)\.lib")


def sha(path):
    with path.open("rb") as source:
        return file_digest(source, "sha256").hexdigest()


def extract_standard(archive, target):
    partial = target.with_suffix(".partial")
    try:
        with tarfile.open(archive, "r|gz") as package:
            for item in package:
                if Path(item.name).name != target.name:
                    continue
                assert item.isfile() and 10_000_000 < item.size < 200_000_000
                with package.extractfile(item) as source, partial.open("xb") as stream:
                    shutil.copyfileobj(source, stream, 1024 * 1024)
                assert partial.stat().st_size == item.size
                partial.rename(target)
                return item.name
        raise ValueError(f"Missing standard-cell model {target.name}")
    finally:
        partial.unlink(missing_ok=True)


def liberty(path, voltage, temperature):
    header_pattern = r"(?m)^\s*{}\s*:\s*([^;]+);"
    with path.open() as stream:
        header = stream.read(32768)
        for key, expected in (("nom_voltage", voltage), ("nom_temperature", temperature)):
            value, = re.findall(header_pattern.format(key), header)
            assert Decimal(value) == expected, (path, key, value)
        supply = {Decimal(value) for value in re.findall(
            r"(?m)^\s*voltage_map\s*\(\s*\w+\s*,\s*(\d+(?:\.\d+)?)\s*\)", header
        )}
        assert supply == {Decimal(0), voltage}, (path, supply)
        stream.seek(0)
        cells, internal, leakage = set(), set(), set()
        name = None
        for line in stream:
            if match := CELL.match(line):
                name = match[1]
                assert name not in cells, (path, name)
                cells.add(name)
            elif name and INTERNAL.match(line):
                internal.add(name)
            elif name and LEAKAGE.match(line):
                leakage.add(name)
    assert cells and internal and leakage, path
    return cells, internal, leakage


def run(output):
    folder = ROOT / ".cache/physical/wac_budgeted_parent_boundary"
    reference = folder / "tsmc_layer_liberty_corner_inventory.json"
    archive_record = ROOT / "records/nldm_corner_inventory.json"
    targets = ROOT / "records/paper_result_targets.json"
    archive_data = json.loads(archive_record.read_text())
    reference_data = json.loads(reference.read_text())
    inputs = reference_data["timing_views"][REFERENCE]["library_sha256"]
    selected = [ROOT / name for name in inputs]
    standard, = (path for path in selected if path.name == FAMILY + REFERENCE + ".lib")
    memories = [path for path in selected if path != standard]
    assert len(memories) == 6 and all(path.parent.name == "NLDM" for path in memories)
    assert all(sha(ROOT / name) == digest for name, digest in inputs.items())

    low = output / f"{FAMILY}{CORNER}.lib"
    assert low.name in archive_data["members"]
    assert shutil.disk_usage(output.parent).free >= 12 * 2**30
    output.mkdir()
    archive = Path(archive_data["archive"])
    member = extract_standard(archive, low)
    library_pairs = [(standard, low)] + [(path, path.with_name(path.name.replace(REFERENCE, CORNER)))
                                        for path in memories]
    profiles = {}
    catalog = {match[1]: Decimal(match[2].replace("p", ".")) for name in archive_data["members"]
               if (match := SINGLE_SUPPLY.fullmatch(name))}
    common = set(catalog)
    for original, candidate in library_pairs:
        old = liberty(original, Decimal("0.9"), Decimal(125))
        new = liberty(candidate, Decimal("0.81"), Decimal(125))
        assert old == new, candidate
        name = FAMILY if original == standard else candidate.parent.parent.name.removesuffix("_130a").upper()
        assert original == standard or new == ({name}, {name}, {name})
        profiles[name] = {"cell_masters": len(new[0]), "with_internal_power": len(new[1]),
                          "with_leakage_power": len(new[2]), "liberty": str(candidate.relative_to(ROOT)),
                          "sha256": sha(candidate)}
        if original != standard:
            prefix = candidate.parent.parent.name + "_"
            common &= {path.name.removeprefix(prefix).removesuffix(".lib")
                       for path in candidate.parent.glob(prefix + "*.lib")}

    paper = json.loads(targets.read_text())
    points = paper["silicon"]["reported_system_power_watts"]
    assert [(point["volts"], point["clock_megahertz"]) for point in points] == [(0.75, 65), (1.1, 580)]
    voltages = {catalog[corner] for corner in common}
    assert voltages.isdisjoint(Decimal(str(point["volts"])) for point in points)
    assert CORNER in common and min(voltages) == Decimal("0.81")
    result = {"state": "joined_chip_common_low_voltage_power_views_verified",
              "corner": CORNER, "volts": 0.81, "temperature_c": 125, "libraries": profiles,
              "archived_standard_member": member, "common_corner_names": sorted(common),
              "paper_power_points": points,
              "input_sha256": {str(path.relative_to(ROOT)): sha(path) for path in (reference, archive_record, targets)},
              "scope": "Complete library set at one local voltage and temperature. Power measurement requires switching activity."}
    (output / "receipt.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(result["state"], CORNER, len(profiles), len(common), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=lambda path: Path(path).resolve())
    run(parser.parse_args().output)
