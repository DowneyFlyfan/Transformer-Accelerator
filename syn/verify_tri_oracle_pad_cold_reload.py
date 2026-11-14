"""Verify the pad-ring placement survives a fresh Innovus session."""

import argparse
from collections import Counter
import json
from pathlib import Path
import re
from sys import intern

from audit_tri_oracle_pad_ring_clearance import POSE
COMPONENTS = re.compile(r"COMPONENTS (\d+) ;\n")
SECTION = re.compile(r"(PINS|BLOCKAGES) (\d+) ;\n")
BLOCK_RECT = re.compile(r"\s*- PLACEMENT RECT \( (-?\d+) (-?\d+) \) \( (-?\d+) (-?\d+) \) ;\n")
HALO = re.compile(r"\s*\+ HALO (\d+) (\d+) (\d+) (\d+)\s*\n")


def components(path):
    with path.open() as stream:
        for line in stream:
            if count := COMPONENTS.fullmatch(line):
                count = int(count[1])
                break
        else:
            raise ValueError(f"Missing components in {path}")
        observed = 0
        for line in stream:
            if line == "END COMPONENTS\n":
                assert observed == count, (observed, count)
                return
            if not line.startswith("- "):
                continue
            match = POSE.match(line)
            assert match, line
            name, master, status, x, y, rotation = match.groups()
            halo = ()
            if status == "FIXED":
                distances = HALO.fullmatch(next(stream))
                assert distances, name
                halo = tuple(map(int, distances.groups()))
            observed += 1
            yield name.encode(), (intern(master), intern(status), int(x), int(y), intern(rotation), halo)
        raise ValueError(f"Missing end of components in {path}")


def boundary_sections(path):
    sections = {}
    with path.open() as stream:
        for line in stream:
            if match := SECTION.fullmatch(line):
                kind, count = match[1], int(match[2])
                assert kind not in sections
                rows = []
                for line in stream:
                    if line == f"END {kind}\n":
                        break
                    if kind == "PINS":
                        rows.append(line)
                    else:
                        rect = BLOCK_RECT.fullmatch(line)
                        assert rect, line
                        rows.append(tuple(map(int, rect.groups())))
                else:
                    raise ValueError(f"Missing end of {kind} in {path}")
                if kind == "BLOCKAGES":
                    assert len(rows) == count and len(set(rows)) == count
                sections[kind] = count, tuple(rows)
    assert sections.keys() == {"PINS", "BLOCKAGES"}
    return sections


def compare(placed, cold):
    original = {}
    for name, pose in components(placed):
        assert name not in original, name
        original[name] = pose
    counts = Counter()
    for name, pose in components(cold):
        assert original.pop(name) == pose, name
        counts[pose[1]] += 1
    assert not original
    before, after = boundary_sections(placed), boundary_sections(cold)
    assert before["PINS"] == after["PINS"], "Boundary pins changed"
    assert Counter(before["BLOCKAGES"][1]) == Counter(after["BLOCKAGES"][1]), "Pad blockages changed"
    return dict(standard_cells=counts["PLACED"], fixed_memories=counts["FIXED"],
                pins=before["PINS"][0], hard_place_blockages=before["BLOCKAGES"][0])


if __name__ == "__main__":
    assert __debug__ and Path("/.dockerenv").is_file()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("placed", type=Path)
    parser.add_argument("cold", type=Path)
    print(json.dumps(compare(**vars(parser.parse_args())), indent=2, sort_keys=True))
