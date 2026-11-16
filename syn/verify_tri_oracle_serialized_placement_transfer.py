"""Audit which placed leaf coordinates can transfer by identity into the serialized hierarchy."""
from collections import Counter
from contextlib import ExitStack
from functools import lru_cache
import json
from mmap import ACCESS_READ, mmap
from pathlib import Path
import re

from audit_tri_oracle_placed_chip_boundary import TOP, digest
from audit_tri_oracle_pad_ring_clearance import dimensions, get_units
from link_tri_oracle_indexed_whole_chip import spans
from verify_tri_oracle_pad_cold_reload import components


ROOT = Path(__file__).resolve().parents[1]
RECORDS = Path("records")
WRAPPED = b"tri_oracle_chip_credited_request"
BASE = TOP.encode()
INSTANCE = re.compile(rb"(?m)^[ \t]+([\w$]+)\s+(\\\S+|[\w$]+)\s*\(\s*\.")
MEMORIES = (b"TS5N28", b"TS6N28")


def catalog(stack, paths):
    modules = {}
    for path in paths:
        stream = stack.enter_context(path.open("rb"))
        source = stack.enter_context(mmap(stream.fileno(), 0, access=ACCESS_READ))
        definitions = spans(source)
        assert definitions and not (modules.keys() & definitions.keys()), path
        modules.update({name: (source, start, stop) for name, (start, stop) in definitions.items()})
    return modules


def audit(modules, sizes, site, placement):
    """Resolve placed names in the wrapped core and count every reachable physical leaf."""
    @lru_cache(maxsize=None)
    def children(master):
        source, start, end = modules[master.decode()]
        instances = {}
        for item in INSTANCE.finditer(source, start, end):
            child, name = item.groups()
            name = name.removeprefix(b"\\")
            assert name not in instances and b"/" not in name, (master, name)
            instances[name] = child
        return instances

    defined = {name.encode() for name in modules}

    @lru_cache(maxsize=None)
    def census(master):
        if master not in defined:
            assert master in sizes, master
            return Counter({master: 1})
        counts = Counter()
        for child, multiplier in Counter(children(master).values()).items():
            counts.update({cell: count * multiplier for cell, count in census(child).items()})
        return counts

    def sites(counts):
        site_width, site_height = site
        total = 0
        for master, count in counts.items():
            if not master.startswith(MEMORIES):
                width, height = sizes[master]
                assert height == site_height and width % site_width == 0, master
                total += count * (width // site_width)
        return total

    def core_paths(master, path=()):
        if master == BASE:
            yield path
        elif master in defined:
            for name, child in children(master).items():
                if child in defined:
                    yield from core_paths(child, (*path, name))

    (prefix,) = core_paths(WRAPPED)
    assert prefix
    wrapped = census(WRAPPED)
    core = census(BASE)
    added_blocks = []
    master = WRAPPED
    path = []
    for next_level in prefix:
        for name, sibling in children(master).items():
            if name == next_level:
                continue
            counts = census(sibling)
            added_blocks.append({
                "instance": b"/".join([*path, name]).decode(), "master": sibling.decode(),
                "leaf_instances": counts.total(), "standard_cell_sites": sites(counts),
            })
        master = children(master)[next_level]
        path.append(next_level)
    assert master == BASE
    assert sum(row["leaf_instances"] for row in added_blocks) == wrapped.total() - core.total()
    assert sum(row["standard_cell_sites"] for row in added_blocks) == sites(wrapped) - sites(core)

    @lru_cache(maxsize=16384)
    def parent_master(parent):
        if not parent:
            return BASE
        grandparent, _, name = parent.rpartition(b"/")
        master = parent_master(grandparent)
        return children(master).get(name) if master in defined else None

    transferred = Counter()
    previous = Counter()
    exceptions = []
    seen = set()
    for name, (master, status, *_) in components(placement):
        normalized = name.replace(b"\\", b"")
        assert normalized not in seen, name
        seen.add(normalized)
        previous[master.encode()] += 1
        parent, _, item = normalized.rpartition(b"/")
        owner = parent_master(parent)
        observed = children(owner).get(item) if owner in defined else None
        if observed == master.encode() and observed not in defined:
            assert (status == "FIXED") == observed.startswith(MEMORIES), (name, master)
            transferred[status] += 1
        else:
            exceptions.append({"placed_instance": name.decode(), "placed_master": master,
                               "wrapped_master": None if observed is None else observed.decode()})
            assert status != "FIXED", (name, master, observed)
    assert len(seen) == len(exceptions) + transferred.total()
    memories = {name: count for name, count in wrapped.items() if name.startswith(MEMORIES)}
    assert memories == {name: count for name, count in previous.items() if name.startswith(MEMORIES)}
    return {
        "path_prefix": "/".join(part.decode() for part in prefix) + "/",
        "placed_component_count": len(seen),
        "verified_transferable_standard_cells": transferred["PLACED"],
        "verified_transferable_fixed_memories": transferred["FIXED"],
        "reachable_new_leaf_instances_outside_core": wrapped.total() - core.total(),
        "reachable_core_leaves_without_placement_match": core.total() - transferred.total(),
        "reachable_wrapped_leaves": wrapped.total(),
        "old_standard_cell_sites": sites(previous),
        "wrapped_standard_cell_sites": sites(wrapped),
        "added_blocks": sorted(added_blocks, key=lambda row: (-row["standard_cell_sites"], row["instance"])),
        "unmatched_original_components": exceptions,
    }


def verify():
    evidence = {}

    def pin(path, expected=None):
        checksum = digest(path)
        assert expected is None or checksum == expected, path
        name = str(path.relative_to(ROOT)) if path.is_absolute() and path.is_relative_to(ROOT) else str(path)
        assert evidence.setdefault(name, checksum) == checksum, path
        return path

    def record(name):
        return json.loads(pin(RECORDS / f"{name}.json").read_text())

    system = record("tri_oracle_bonded_system_budget")
    cold = record("tri_oracle_repacked_whole_chip_cold_reload")
    geometry = record("tri_oracle_bonded_pad_recovery")
    layout_sha = system["placed"]["layout_sha256"]
    (layout,) = (Path(name) for name, sha in geometry["evidence_sha256"].items() if sha == layout_sha)
    pin(layout, layout_sha)
    tx = record("tri_oracle_credited_request_link")
    (name,) = (name for name in tx["evidence_sha256"] if name.endswith("/chip_bundle.sv"))
    bundle = pin(Path(name), tx["evidence_sha256"][name])
    includes = [Path(name) for name in re.findall(r'(?m)^`include "([^"]+)"$', bundle.read_text())]
    assert len(includes) == len(set(includes)) == tx["structural_bundle_source_files"]
    design = []
    for path in includes:
        name = str(path.relative_to(ROOT))
        pin(path, tx["evidence_sha256"].get(name, tx["evidence_sha256"].get(str(path))))
        if path.parent.name != "VERILOG" and path.name != "tcbn28hpcplusbwp12t40p140.v":
            design.append(path)
    lefs = [pin(Path(name), sha) for name, sha in geometry["evidence_sha256"].items() if name.endswith(".lef")]
    with layout.open() as stream:
        units = get_units(stream)
        rows = []
        for line in stream:
            if line.startswith("COMPONENTS "):
                break
            if row := re.match(r"^ROW \S+ \S+ \d+ (\d+) \w+ DO \d+ BY 1 STEP (\d+) 0\b", line):
                rows.append((int(row[1]), int(row[2])))
    assert len(rows) >= 2 and len({pitch for _, pitch in rows}) == 1
    row_origins = sorted({y for y, _ in rows})
    assert len(row_origins) == len(rows) and len(set(b - a for a, b in zip(row_origins, row_origins[1:]))) == 1
    site = rows[0][1], row_origins[1] - row_origins[0]
    sizes = {name.encode(): size for name, size in dimensions(lefs, units).items()}

    with ExitStack() as stack:
        result = audit(catalog(stack, design), sizes, site, layout)
    assert result["verified_transferable_fixed_memories"] == cold["fixed_compiled_memory_macros"]
    assert result["placed_component_count"] == cold["physical_components"]
    assert result["old_standard_cell_sites"] == geometry["required_standard_cell_sites"]
    assert system["separate_wrapper"]["digital_signal_bits"] + system["separate_wrapper"]["supply_and_ground_reservations"] == geometry["required_sites"] - 6
    available = (geometry["required_standard_cell_sites"] + geometry["mapped_control_sites_required"]
                 + geometry["site_margin_after_control_logic_by_additional_pads_released"]["6"])
    for helper in (verify, components, spans, dimensions):
        pin(Path(helper.__code__.co_filename).resolve())
    return {
        "state": "serialized_hierarchy_resolved_against_exact_native_placed_leaf_inventory",
        **result,
        "input_layout_sha256": layout_sha,
        "geometric_sites_after_497_pad_reservations": available,
        "remaining_sites_after_all_reachable_wrapper_logic": available - result["wrapped_standard_cell_sites"],
        "scope": "Identity and master checks for transferring existing coordinates into the new hierarchy. "
                 "Component matches do not qualify physical positions under the new pad and memory reservations. "
                 "New logic and pad cells still require placement, connectivity and native timing checks.",
        "evidence_sha256": evidence,
    }


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    with Path("/proc/meminfo").open() as info:
        assert next(int(line.split()[1]) for line in info if line.startswith("MemAvailable:")) >= 8 * 1024**2
    print(json.dumps(verify(), indent=2, sort_keys=True))
