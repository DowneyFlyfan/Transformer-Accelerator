"""Measure compiled memory in the exact Booth placement candidate."""

from collections import Counter
from contextlib import ExitStack
from functools import cache
import json
from pathlib import Path
import re

from build_tri_oracle_booth_chip_seed import canonical, hierarchy
from check_tri_oracle_paper300_gate import PAPER_RELATIVE, PAPER_SHA256
from verify_tri_oracle_booth_chip_link import TOP, WORK
from verify_tri_oracle_gated_compute_array import ROOT, digest, read
from verify_tri_oracle_serialized_placement_transfer import catalog
from verify_tri_oracle_shared_memory import CORNERS, MEMORY_PREFIXES, memory_shape

INPUTS = Path("records/tri_oracle_booth_chip_native_inputs.json")
GLUE = Path("records/tri_oracle_booth_native_glue.json")
LINK = Path("records/tri_oracle_linked_booth_chip.json")
TARGETS = Path("records/paper_result_targets.json")
RETRY = WORK / "native_glue/retry"
PREFIX = tuple(name.encode() for name in MEMORY_PREFIXES)
FIXED = re.compile(rb"^- (\S+) (TS[56]N28\w+) \+ FIXED \( (-?\d+) (-?\d+) \) (\w+)\s*$")
HALO = re.compile(rb"^  \+ HALO (\d+) (\d+) (\d+) (\d+)\s*$")
INCLUDE = re.compile(r'(?m)^`include "([^"]+)"$')


def unique(items):
    result = {}
    for name, value in items:
        assert name not in result, name
        result[name] = value
    return result


def logical_memories(netlist):
    with ExitStack() as stack:
        modules = catalog(stack, [netlist])
        children, _ = hierarchy(modules)

        @cache
        def within(master):
            if master.startswith(PREFIX):
                return ((b"", master),)
            if master.decode() not in modules:
                return ()
            found = []
            for name, child in children(master).items():
                for suffix, cell in within(child):
                    found.append((name + b"/" + suffix if suffix else name, cell))
            return tuple(found)

        return unique(
            (canonical(name), master) for name, master in within(TOP.encode())
        )


def memory_poses(seed):
    with seed.open("rb") as stream:
        for line in stream:
            if line == b"END COMPONENTS\n":
                return
            if not line.startswith(b"- ") or not any(
                b" " + prefix in line for prefix in PREFIX
            ):
                continue
            match = FIXED.fullmatch(line)
            assert match, (seed, line)
            halo = HALO.fullmatch(next(stream))
            assert halo, (seed, match[1])
            yield canonical(match[1]), (match[2], *match.group(3, 4, 5), *halo.groups())
    raise ValueError(f"Component section is incomplete in {seed}")


def dims_by_master(masters, bundle, sources, mark):
    models = [
        Path(name).relative_to(ROOT)
        for name in INCLUDE.findall(bundle.read_text())
        if Path(name).name.upper().startswith(MEMORY_PREFIXES)
    ]
    models = unique(
        (
            re.search(r"(?m)^module\s+(TS[56]N28\w+)\b", path.read_text())[1],
            path,
        )
        for path in models
    )
    assert set(models) == {name.decode() for name in masters}
    sizes = {}
    for master, count in sorted(masters.items()):
        name = master.decode()
        model = models[name]
        mark(model)
        geometries = set()
        for corner in CORNERS:
            (lib,) = [
                Path(path)
                for path in sources
                if Path(path).name
                == f"{model.stem.removesuffix('_tt1v25c')}_{corner}.lib"
            ]
            mark(lib, sources[str(lib)])
            geometries.add(memory_shape(model.read_text(), lib.read_text(), name))
        ((depth, width),) = geometries
        sizes[name] = dict(
            macros=count,
            words=depth,
            bits_per_word=width,
            bytes=count * depth * width // 8,
        )
    return sizes


def verify():
    evidence = {}

    def mark(path, expected=None):
        checksum = digest(path)
        if expected is not None:
            assert checksum == expected, path
        evidence[str(path)] = checksum
        return path

    base = read(mark(INPUTS))
    patched = read(mark(GLUE))
    assert (
        patched["state"]
        == "booth_chip_mapped_boundary_control_passed_innovus_netlist_read"
    )
    standard = base["evidence_sha256"]
    corrected = patched["evidence_sha256"]
    first_net, first_seed = WORK / "linked.v", WORK / "placement_with_terminal_seed.def"
    new_net, new_seed = RETRY / "linked.v", RETRY / "seed.def"
    old = logical_memories(mark(first_net, standard[str(first_net)]))
    latest = logical_memories(mark(new_net, corrected[str(new_net)]))
    assert old == latest
    old_poses = unique(memory_poses(mark(first_seed, standard[str(first_seed)])))
    poses = unique(memory_poses(mark(new_seed, corrected[str(new_seed)])))
    assert old_poses == poses
    assert latest == {name: pose[0] for name, pose in poses.items()}
    assert len(latest) == patched["fixed_macros"] == 631

    link = read(mark(LINK))
    bundle = WORK / "simulation.sv"
    mark(bundle, link["evidence_sha256"][str(bundle)])
    models = dims_by_master(Counter(latest.values()), bundle, standard, mark)
    memory_bytes = sum(model["bytes"] for model in models.values())
    mark(Path(PAPER_RELATIVE), PAPER_SHA256)
    paper = read(mark(TARGETS))
    label = paper["silicon"]["sram_published_KB"]
    mark(Path(__file__).resolve().relative_to(ROOT))
    return dict(
        state="booth_candidate_compiled_memory_bound_to_netlist_and_seed",
        macro_count=len(latest),
        master_count=len(models),
        by_master=models,
        installed_bytes=memory_bytes,
        published_label_kb=label,
        binary_kib=memory_bytes / 1024,
        rounded_binary_kib=round(memory_bytes / 1024),
        matches_published_label_if_rounded_binary=round(memory_bytes / 1024) == label,
        bytes_above_exact_binary_label=memory_bytes - label * 1024,
        bytes_above_exact_decimal_label=memory_bytes - label * 1000,
        scope=(
            "Every logical memory instance and its fixed seed placement match the "
            "predecessor through the control mapping. Capacities use the compiler "
            "models and all three timing views. The paper gives a single rounded label. "
            "Native reload, benchmark and architectural qualification are separate."
        ),
        evidence_sha256=evidence,
    )


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    print(json.dumps(verify(), indent=2, sort_keys=True))
