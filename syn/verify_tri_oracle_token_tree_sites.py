"""Check token-count buffer sites directly in native Innovus layout exports."""

import argparse
import csv
import json
from pathlib import Path
import re

from audit_tri_oracle_pad_ring_clearance import get_units
from verify_tri_oracle_pad_cold_reload import components
from verify_tri_oracle_partial_pad_ring_geometry import scaled


ORIENTATIONS = {"r0": "N", "mx": "FS"}
BUFFER_NAME = re.compile(r"TRI_TOKEN_COUNT_([0-9])_(\d+)")


def rows(path):
    with path.open() as stream:
        yield from csv.DictReader(stream, delimiter="\t")


def expected_sites(inputs, units):
    buffers = {}
    for bit in range(10):
        nodes = list(rows(inputs / f"bit_{bit}.tsv"))
        if [int(node["id"]) for node in nodes] != list(range(288)):
            raise ValueError(f"Incomplete token tree for bit {bit}")
        for node in nodes:
            name = f"TRI_TOKEN_COUNT_{bit}_{node['id']}"
            buffers[name] = (node["master"], scaled(node["x_um"], units), scaled(node["y_um"], units))

    sites = {}
    for row in rows(inputs / "coordinates.tsv"):
        name = row["id"]
        master, x, y = buffers[name]
        if name in sites or (x, y) != (scaled(row["x_um"], units), scaled(row["y_um"], units)):
            raise ValueError(f"Repeated or inconsistent buffer coordinates for {name}")
        sites[name] = (master, "PLACED", x, y, ORIENTATIONS[row["orient"]], ())
    if sites.keys() != buffers.keys():
        raise ValueError("Incomplete buffer coordinate table")

    moves = list(rows(inputs / "moves.tsv"))
    if len(moves) != 4 or len({row["instance"] for row in moves}) != len(moves):
        raise ValueError("Expected four distinct relocated cells")
    for row in moves:
        sites[row["instance"]] = (row["master"], "PLACED", scaled(row["new_x_um"], units),
                                  scaled(row["new_y_um"], units), ORIENTATIONS[row["orient"]], ())
    return sites


def verify(layout, inputs):
    with layout.open() as stream:
        units = get_units(stream)
    sites = expected_sites(inputs, units)
    pending = set(sites)
    for raw_name, pose in components(layout):
        name = raw_name.decode().replace("\\", "")
        leaf = name.rsplit("/", 1)[-1]
        if BUFFER_NAME.fullmatch(leaf):
            name = leaf
        elif name not in sites:
            continue
        if name not in pending:
            raise ValueError(f"{layout}: unexpected or repeated instance {name}")
        expected = sites[name]
        if pose != expected:
            raise ValueError(f"{layout}: {name} is at {pose}, expected {expected}")
        pending.remove(name)
    if pending:
        raise ValueError(f"{layout}: {len(pending)} expected sites missing, including {min(pending)}")
    return {"inserted_buffer_sites": 2880, "relocated_cell_sites": 4, "units_per_micron": units}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", type=Path)
    parser.add_argument("layouts", type=Path, nargs="+")
    args = parser.parse_args()
    print(json.dumps({str(layout): verify(layout, args.inputs) for layout in args.layouts}, indent=2))
