"""Check the paper's compute geometry in the exact corrected Booth candidate."""

from collections import Counter
from contextlib import ExitStack
from functools import cache
import json
from pathlib import Path
import re

from build_tri_oracle_booth_chip_seed import canonical
from check_tri_oracle_paper300_gate import PAPER_RELATIVE, PAPER_SHA256
from link_tri_oracle_indexed_whole_chip import signature
from verify_tri_oracle_booth_chip_geometry import geometry
from verify_tri_oracle_booth_chip_link import OLD_ARRAY, TOP, WORK, named_bindings
from verify_tri_oracle_gated_compute_array import ROOT, digest, read
from verify_tri_oracle_serialized_placement_transfer import INSTANCE, catalog

RETRY = WORK / "native_glue/retry"
GLUE = Path("records/tri_oracle_booth_native_glue.json")
LINK = Path("records/tri_oracle_linked_booth_chip.json")
REPLAY = Path("records/tri_oracle_linked_booth_resets.json")
TARGET = Path("records/paper_result_targets.json")
CLUSTER_PATH = re.compile(
    rb"(.*/fabric)/clusters\[(\d+)\]\.unit/selected_bank(\d+)\.block_instance"
    rb"/source_cluster/implementation/cores\[(\d+)\]/compute/compute"
)
MULTIPLIER = re.compile(
    rb"(?m)^[ \t]+(tri_booth_i_tri_oracle_booth8(?:_\d+)?)"
    rb"\s+\\product\[(\d+)\]\.recoded\.signed_multiplier\s*\(([^;]+)\);"
)
ROW_RESULT = re.compile(
    rb"(?m)^[ \t]+\w+\s+\\carry_save\.row\[(\d+)\]\.value_reg\[(\d+)\]\s*\("
)


def compute_paths(modules):
    @cache
    def below(master):
        if OLD_ARRAY.fullmatch(master):
            return ((b"", master),)
        if master not in modules:
            return ()
        code, lo, hi = modules[master]
        found = []
        for inst in INSTANCE.finditer(code, lo, hi):
            child, local = inst.groups()
            for suffix, array_master in below(child.decode()):
                name = canonical(local)
                assert name and b"/" not in name
                found.append((name + b"/" + suffix if suffix else name, array_master))
        return tuple(found)

    return below(TOP)


def module_text(modules, master):
    code, start, end = modules[master]
    return code[start:end]


def connected_cluster_members(members, clusters, cores):
    result = {}
    fabric_paths = set()
    for path, _ in members:
        item = CLUSTER_PATH.fullmatch(path)
        assert item, path
        fabric, group, bank, index = item.groups()
        cluster, core = int(group), int(index)
        assert int(bank) == cluster
        assert (cluster, core) not in result
        fabric_paths.add(fabric)
        result[cluster, core] = path
    assert len(fabric_paths) == 1
    assert set(result) == {
        (cluster, core) for cluster in range(clusters) for core in range(cores)
    }
    return result


def verify_array(body, rows, lanes, width):
    count = rows * lanes
    sum_width = width * 2 + (lanes - 1).bit_length()
    ports = signature(body)
    encoded = {
        "operand_a": (b"input", b"[%d:0]" % (count * width - 1)),
        "operand_b": (b"input", b"[%d:0]" % (count * width - 1)),
        "lane_enable": (b"input", b"[%d:0]" % (count - 1)),
        "out_sums": (b"output", b"[%d:0]" % (rows * sum_width - 1)),
    }
    assert all(ports.get(name) == spec for name, spec in encoded.items())
    instances = list(MULTIPLIER.finditer(body))
    assert sorted(int(item[2]) for item in instances) == list(range(count))
    seen = set()
    for cell, group, fields in (item.groups() for item in instances):
        lane = int(group)
        low = lane * width
        bounds = b"[%d:%d]" % (low + width - 1, low)
        pins = {
            "a": b"operand_a" + bounds,
            "b": b"operand_b" + bounds,
            "p": rb"\product[%d].multiplied" % lane,
        }
        assert named_bindings(fields) == pins, lane
        seen.add(cell.decode())
    outputs = Counter(tuple(map(int, entry)) for entry in ROW_RESULT.findall(body))
    assert outputs == Counter((r, b) for r in range(rows) for b in range(sum_width))
    return seen


def verify():
    evidence = {}

    def pin(path, expected=None):
        calculated = digest(path)
        assert expected is None or calculated == expected, path
        evidence[str(path)] = calculated
        return path

    pin(Path(PAPER_RELATIVE), PAPER_SHA256)
    target = read(pin(TARGET))
    silicon = target["silicon"]
    clusters, cores = silicon["clusters"], silicon["cores_per_cluster"]
    rows, lanes = silicon["processing_element_array_per_core"]
    assert silicon["processing_element_precision"] == "signed INT8"
    width = 8
    linked = read(pin(LINK))
    repaired = read(pin(GLUE))
    replay = read(pin(REPLAY))
    assert replay["state"] == "all_linked_booth_array_reset_bindings_verified"
    predecessor, candidate, seed = (
        WORK / "linked.v",
        RETRY / "linked.v",
        RETRY / "seed.def",
    )
    pin(predecessor, linked["evidence_sha256"][str(predecessor)])
    for path in (candidate, seed):
        pin(path, repaired["evidence_sha256"][str(path)])
    for path, key in replay["evidence_sha256"].items():
        pin(Path(path), key)
    legacy = read(WORK / "link_proof.json")
    assert legacy["evidence_sha256"][str(predecessor)] == evidence[str(predecessor)]

    with ExitStack() as stack:
        old, new = (catalog(stack, [netlist]) for netlist in (predecessor, candidate))
        old_members = dict(compute_paths(old))
        members = compute_paths(new)
        assert len(members) == len(dict(members)) and dict(members) == old_members
        assert (
            len({master for _, master in members})
            == len(members)
            == replay["arrays_replayed"]
        )
        cluster_core = connected_cluster_members(members, clusters, cores)
        multiplier_modules = set()
        for _, master in members:
            body = module_text(new, master)
            assert body == module_text(old, master)
            multiplier_modules.update(verify_array(body, rows, lanes, width))
        helpers = {name for name in new if name.startswith("tri_booth_i_")}
        assert multiplier_modules <= helpers
        assert helpers == {name for name in old if name.startswith("tri_booth_i_")}
        for name in helpers:
            assert module_text(new, name) == module_text(old, name)

    die, units, _, regions, groups, _ = geometry(seed, verify_top=True)
    dimensions = [(hi - lo) / (1000 * units) for lo, hi in zip(die[:2], die[2:])]
    assert dimensions == silicon["die_dimensions_mm"]
    assert len(groups) == len(regions) == clusters * cores
    assert {canonical(name).removesuffix(b"/") for name in groups} == set(
        cluster_core.values()
    )
    frequency = target["peak"]["clock_megahertz"]
    multipliers = len(members) * rows * lanes
    peak = 2 * multipliers * frequency / 1_000_000
    assert round(peak, 2) == target["peak"]["trillion_operations_per_second"]
    pin(Path(__file__).resolve().relative_to(ROOT))
    return dict(
        state="corrected_full_chip_compute_geometry_bound_to_mapped_replay",
        clusters=clusters,
        arrays_per_cluster=cores,
        processing_element_geometry=[rows, lanes],
        signed_operand_bits=width,
        multipliers=multipliers,
        multiplier_modules_verified=len(multiplier_modules),
        die_dimensions_mm=dimensions,
        ideal_peak_trillion_operations_per_second=peak,
        ideal_peak_clock_megahertz=frequency,
        inherited_array_lockstep_transactions=replay[
            "delivered_lockstep_transactions_per_array"
        ],
        scope=(
            "Compute hierarchy, multiplier lane slices, result register shape, placement "
            "group membership and the unchanged mapped array replay are bound to the "
            "corrected netlist. Ideal peak assumes one multiply and one add per lane per "
            "cycle at the target frequency. Whole-chip timing and measured throughput remain pending."
        ),
        evidence_sha256=evidence,
    )


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    print(json.dumps(verify(), indent=2, sort_keys=True))
