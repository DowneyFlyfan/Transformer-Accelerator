"""Compare complete native core-cell inventories with bounded sorting memory."""
import argparse
import filecmp
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


HEADER = "instance\tmaster\tlocation\torientation\n"
MEMORIES_PER_CORE = {
    "TS5N28HPCPSVTA32X128M2FW": 18,
    "TS5N28HPCPSVTA512X64M4F": 2,
    "TS6N28HPCPSVTA16X128M2F": 8,
}


def digest(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def verify_core_snapshots(before, after, core_prefixes):
    """Require all94471 original cells and18/2/8 memories per declared core.

    Record order may change. Names, masters and reported geometry may not.
    External sorting reserves64MiB; Python retains only the current row and
    per-core counters, rather than a dictionary of1.89million cell records.
    """
    before, after = Path(before), Path(after)
    prefixes = list(core_prefixes)
    if (not prefixes or len(set(prefixes)) != len(prefixes)
            or any(not isinstance(p, str) or not p or p.endswith("/")
                   or any(c in p for c in "\t\r\n") for p in prefixes)):
        raise ValueError("Expected a nonempty unique core-prefix list")
    expression = re.compile("^("+"|".join(re.escape(p) for p in prefixes)+")/")
    environment = dict(os.environ, LC_ALL="C")

    def check(sorted_path):
        cells = dict.fromkeys(prefixes, 0)
        memories = {p: dict.fromkeys(MEMORIES_PER_CORE, 0) for p in prefixes}
        previous_name = None
        headers = 0
        with sorted_path.open() as source:
            for line in source:
                if line == HEADER:
                    headers += 1
                    continue
                fields = line.rstrip("\n").split("\t")
                if len(fields) != 4 or any(not value for value in fields):
                    raise ValueError("Malformed native core-cell inventory row")
                name, master, _, _ = fields
                if name == previous_name:
                    raise ValueError("Duplicate original cell: "+name)
                previous_name = name
                match = expression.match(name)
                if match is None:
                    raise ValueError("Unexpected core-cell prefix: "+name)
                prefix = match[1]
                cells[prefix] += 1
                if master in MEMORIES_PER_CORE:
                    memories[prefix][master] += 1
        if headers != 1:
            raise ValueError("Expected one native inventory header")
        for prefix in prefixes:
            if cells[prefix] != 94471:
                raise ValueError(f"Expected94471 original cells in {prefix}; observed{cells[prefix]}")
            if memories[prefix] != MEMORIES_PER_CORE:
                raise ValueError("Wrong original memory inventory in "+prefix)
        return cells, memories

    with tempfile.TemporaryDirectory(prefix="core_compare_", dir=before.parent) as directory:
        temporary = Path(directory)
        sorted_files = []
        counts = []
        for index, source in enumerate([before, after]):
            with source.open() as stream:
                if stream.readline() != HEADER:
                    raise ValueError("Missing native core inventory header")
            ordered = temporary/f"snapshot{index}.tsv"
            subprocess.run(["sort", "-S", "64M", "-T", str(temporary),
                            "-o", str(ordered), str(source)], check=True,
                           env=environment, timeout=600)
            counts.append(check(ordered))
            sorted_files.append(ordered)
        if not filecmp.cmp(*sorted_files, shallow=False):
            raise ValueError("Original core-cell names, masters or reported geometry changed")
        return {
            "cells_per_core": counts[0][0],
            "memory_macros_per_core": counts[0][1],
            "total_original_cells": sum(counts[0][0].values()),
            "all_original_cell_names_masters_and_geometry_preserved": True,
            "canonical_inventory_sha256": digest(sorted_files[0]),
            "input_sha256": {str(p): digest(p) for p in [before, after]},
            "sorting_memory_limit_bytes": 64*1024**2,
            "scope": "Names, cell masters and reported placement geometry only; no connectivity, timing or routed signoff claim.",
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("core_prefixes", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify_core_snapshots(args.before, args.after,
          args.core_prefixes.read_text().splitlines()), indent=2))


if __name__ == "__main__":
    main()
