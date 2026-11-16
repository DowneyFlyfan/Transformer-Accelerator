"""Link the verified Booth arrays and gated receiver into the serialized chip."""

import argparse
from bisect import bisect_right
from collections import Counter
from contextlib import ExitStack
from functools import lru_cache
from hashlib import sha256
import json
import mmap
from pathlib import Path
import re

from audit_tri_oracle_packed_weight_path import PIN
from audit_tri_oracle_mapped_redundancy import MODULE
from link_tri_oracle_indexed_whole_chip import module_at, signature, spans
from link_tri_oracle_narrow_host import width
from verify_tri_oracle_gated_compute_array import ROOT, digest, read
from verify_tri_oracle_host_control import outer_ports
from verify_tri_oracle_serialized_placement_transfer import (
    INSTANCE,
    WRAPPED,
    catalog,
    dimensions,
)

BASE = Path(".cache/physical/whole_chip_xcelium_speed")
WORK = BASE / "booth_joined_chip"
TRANSFER = Path("records/tri_oracle_serialized_placement_transfer.json")
PAD = Path("records/tri_oracle_497_pad_floorplan.json")
FIT = Path("records/tri_oracle_booth_fence_capacity.json")
ARRAY = Path("records/tri_oracle_booth_control_buffers.json")
RECEIVER = Path("records/tri_oracle_gated_receive_storage.json")
LINK = Path("records/tri_oracle_credited_request_link.json")
COMPOSITION = Path("records/tri_oracle_hot_timed_array_twenty_core_composition.json")
TOP = WRAPPED.decode()
INCLUDE = re.compile(r'(?m)^`include "([^"\n]+)"$')
OLD_ARRAY = re.compile(r"tri_oracle_pe_array_verified_bank[0-4](?:_[1-3])?")
ARRAY_TYPE = "tri_booth_array_mapped"
RECEIVER_TYPE = "tri_oracle_credit_metadata_ingress"
SHADOW_RESET = re.compile(
    rb"(?m)(\\shadow_valid_reg\[([0-3])\]\s*\(\s*\.CDN\s*\(\s*)"
    rb"(rst_n|p[1-2])(?=\s*\))"
)


def ports_match(old, new):
    left, right = signature(old), signature(new)
    assert left == right
    return left


def named_bindings(fields):
    parsed = PIN.findall(fields)
    result = {
        name.decode().removeprefix("\\"): b"".join(value.split())
        for name, value in parsed
    }
    assert len(result) == len(parsed) and not PIN.sub(b"", fields).strip(b" \t\n\r,")
    return result


def namespaced(source, top, target, prefix, library):
    definitions = spans(source)
    assert top in definitions
    aliases = {
        name.encode(): (target if name == top else prefix + name).encode()
        for name in definitions
    }
    patches = [(*item.span(1), aliases[item[1]]) for item in MODULE.finditer(source)]
    for item in INSTANCE.finditer(source):
        original = item[1]
        if original in aliases:
            patches.append((*item.span(1), aliases[original]))
        else:
            assert original.decode() in library, original
    output = b"".join(pieces(source, patches))
    assert set(spans(output)) == {name.decode() for name in aliases.values()}
    return output


def pieces(source, edits):
    start = 0
    for left, right, replacement in sorted(edits):
        assert start <= left < right <= len(source)
        for offset in range(start, left, 4 * 1024**2):
            yield source[offset : min(offset + 4 * 1024**2, left)]
        if replacement:
            yield replacement
        start = right
    for offset in range(start, len(source), 4 * 1024**2):
        yield source[offset : offset + 4 * 1024**2]


def shadow_resets(module):
    bindings = {
        int(index): reset.decode() for _, index, reset in SHADOW_RESET.findall(module)
    }
    assert sorted(bindings) == list(range(4))
    return [bindings[i] for i in range(4)]


def bind_array(old, replacement, reset_map):
    old_ports, new_ports = signature(old), signature(replacement)
    assert new_ports.items() <= old_ports.items()
    extra = old_ports.keys() - new_ports.keys()
    assert extra == set(reset_map) - {"rst_n"}
    assert all(old_ports[name] == (b"input", b"") for name in extra)
    assert shadow_resets(old) == reset_map
    assert shadow_resets(replacement) == ["rst_n"] * 4
    header, _, _ = old.partition(b");")
    _, _, body = replacement.partition(b");")
    body, changes = SHADOW_RESET.subn(
        lambda match: match[1] + reset_map[int(match[2])].encode(), body
    )
    assert changes == 4
    inputs = b"".join(b"\n  input " + name.encode() + b";" for name in sorted(extra))
    bound = header + b");" + inputs + body
    assert signature(bound) == old_ports and shadow_resets(bound) == reset_map
    return bound


def array_calls(source, definitions, array, expected, reset_maps):
    obsolete = {
        name: bounds
        for name, bounds in definitions.items()
        if OLD_ARRAY.fullmatch(name)
    }
    assert (
        len(obsolete) == expected["fences"] == expected["exact_width_assignments"] == 20
    )
    assert len(signature(array)) == 10 and obsolete.keys() == reset_maps.keys()
    member = rb"|".join(re.escape(name.encode()) for name in sorted(obsolete))
    pattern = re.compile(
        rb"(?m)^[ \t]*(" + member + rb")\s+(\\\S+|[\w$]+)\s*\(([^;]+)\);"
    )
    roots = sorted((start, end, name) for name, (start, end) in definitions.items())
    points = [item[0] for item in roots]
    edits = []
    old_ports = {}
    for name, (start, stop) in obsolete.items():
        old = source[start:stop]
        old_ports[name] = signature(old)
        edits.append((start, stop, bind_array(old, array, reset_maps[name])))
    bindings = []
    for item in pattern.finditer(source):
        index = bisect_right(points, item.start()) - 1
        _, stop, owner = roots[index]
        assert item.end() < stop and owner not in obsolete
        ports = named_bindings(item[3])
        master = item[1].decode()
        assert ports.keys() == old_ports[master].keys()
        bindings.append(
            dict(
                owner=owner,
                instance=item[2].decode(),
                predecessor=item[1].decode(),
                shadow_reset_nets=reset_maps[master],
                associations_sha256=sha256(item[3]).hexdigest(),
            )
        )
    assert Counter(item["predecessor"] for item in bindings) == Counter(obsolete.keys())
    assert len({(item["owner"], item["instance"]) for item in bindings}) == 20
    return edits, bindings


def inputs():
    transfer = read(TRANSFER)
    board = read(FIT)
    assert board["state"] == "buffered_booth_chip_geometry_assigned"
    evidence = {
        str(path): digest(path)
        for path in (TRANSFER, PAD, FIT, ARRAY, RECEIVER, LINK, COMPOSITION)
    }

    def pinned(path, expected):
        actual = digest(path)
        assert actual == expected, path
        evidence[str(path)] = actual
        return path

    (reset,) = [
        pinned(Path(key), value)
        for key, value in read(COMPOSITION)["evidence_sha256"].items()
        if key.endswith("/twenty_core_fit/verified_reset_replays.json")
    ]
    cases = read(reset)["cases"]
    reset_maps = {
        name: case["shadow_reset_signals"] for case in cases for name in case["arrays"]
    }
    assert len(reset_maps) == 20

    sources = transfer["evidence_sha256"]
    (bundle,) = [
        pinned(Path(key), value)
        for key, value in sources.items()
        if key.endswith("/credit_request_link/chip_bundle.sv")
    ]
    design, models = [], []
    for filename in INCLUDE.findall(bundle.read_text()):
        relative = Path(filename).relative_to(ROOT)
        path = pinned(relative, sources.get(str(relative), sources.get(filename)))
        if path.parent.name == "VERILOG" or path.name == "tcbn28hpcplusbwp12t40p140.v":
            models.append(path)
        else:
            design.append(path)
    assert len(models) == 7
    assert len(models) + len(design) == read(LINK)["structural_bundle_source_files"]
    pad = read(PAD)["evidence_sha256"]
    lefs = [
        pinned(Path(path), checksum)
        for path, checksum in pad.items()
        if path.endswith(".lef")
    ]
    array = BASE / "booth_multiplier/array/native_placement/control_buffers/netlist.v"
    receive = BASE / "gated_receive_storage/netlist.v"
    pinned(array, read(ARRAY)["evidence_sha256"][str(array)])
    pinned(receive, read(RECEIVER)["evidence_sha256"][str(receive)])
    return (
        board,
        tuple(design),
        tuple(models),
        array,
        receive,
        dimensions(lefs, 2000),
        reset_maps,
        evidence,
    )


def stream_chip(design, array_path, receiver_path, library, board, reset_maps):
    old_array_parent = BASE / "host_results/cold_results.v"
    receiver_path_old = BASE / "shared_edge_metadata/genus/netlist.v"
    new_array = array_path.read_bytes()
    receiver = receiver_path.read_bytes()
    old_receiver = receiver_path_old.read_bytes()
    ports_match(
        module_at(old_receiver, spans(old_receiver), RECEIVER_TYPE),
        module_at(receiver, spans(receiver), RECEIVER_TYPE),
    )
    replacement_array = namespaced(
        new_array, "tri_oracle_pe_array", ARRAY_TYPE, "tri_booth_i_", library
    )
    array_defs = spans(replacement_array)
    array = module_at(replacement_array, array_defs, ARRAY_TYPE)
    replacement_rx = namespaced(
        receiver, RECEIVER_TYPE, RECEIVER_TYPE, "tri_gated_rx_i_", library
    )
    bindings = []
    used = set()
    for path in design:
        with (
            path.open("rb") as handle,
            mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as source,
        ):
            defs = spans(source)
            assert not used.intersection(defs)
            used.update(defs)
            if path == old_array_parent:
                edits, bindings = array_calls(source, defs, array, board, reset_maps)
                yield from pieces(source, edits)
            elif path == receiver_path_old:
                yield replacement_rx
            else:
                yield from pieces(source, ())
        yield b"\n"
    assert bindings and not used.intersection(spans(replacement_array))
    assert not (
        {name for name in spans(replacement_rx) if name != RECEIVER_TYPE} & used
    )
    yield from pieces(replacement_array, [(*array_defs[ARRAY_TYPE], b"")])
    yield b"\n"
    yield bindings


def check_hierarchy(netlist, library):
    with ExitStack() as stack:
        modules = catalog(stack, [netlist])
        assert len([name for name in modules if OLD_ARRAY.fullmatch(name)]) == 20

        @lru_cache(maxsize=None)
        def by_master(name):
            if name not in modules:
                assert name in library, name
                return Counter({name: 1})
            source, begin, end = modules[name]
            local = Counter(
                instance[1].decode()
                for instance in INSTANCE.finditer(source, begin, end)
            )
            result = (
                Counter({name: 1})
                if OLD_ARRAY.fullmatch(name) or name == RECEIVER_TYPE
                else Counter()
            )
            for child, multiplier in local.items():
                for master, quantity in by_master(child).items():
                    result[master] += multiplier * quantity
            return result

        counts = by_master(TOP).copy()
        array_instances = [
            counts.pop(name) for name in modules if OLD_ARRAY.fullmatch(name)
        ]
        assert array_instances == [1] * 20
        arrays, receivers = sum(array_instances), counts.pop(RECEIVER_TYPE)
        assert arrays == 20 and receivers == 1
        assert not counts.keys() - library.keys()
        macros = sum(
            value
            for name, value in counts.items()
            if name.upper().startswith(("TS5N28", "TS6N28"))
        )
        sites = 0
        for name, value in counts.items():
            if not name.upper().startswith(("TS5N28", "TS6N28")):
                site_width, height = library[name]
                assert site_width % 280 == 0 and height == 2400, name
                sites += site_width // 280 * value
        source, start, end = modules[TOP]
        pins = width(outer_ports(source[start:end].decode()))
        return (
            arrays,
            receivers,
            macros,
            sites,
            sum(counts.values()),
            len(modules),
            pins,
        )


def run(action):
    board, design, models, array, receiver, library, reset_maps, evidence = inputs()
    WORK.mkdir(exist_ok=True)
    netlist = WORK / "linked.v"
    bundle = WORK / "simulation.sv"
    generated = stream_chip(design, array, receiver, library, board, reset_maps)
    produced = sha256()
    bindings = None
    if action == "prepare":
        temporary = netlist.with_suffix(".partial")
        with temporary.open("wb") as output:
            for part in generated:
                if isinstance(part, list):
                    bindings = part
                else:
                    output.write(part)
                    produced.update(part)
        assert bindings is not None
        temporary.replace(netlist)
    else:
        for part in generated:
            if isinstance(part, list):
                bindings = part
            else:
                produced.update(part)
    assert bindings is not None and produced.hexdigest() == digest(netlist)
    simulation = "`define UNIT_DELAY\n" + "".join(
        f'`include "{path.resolve()}"\n' for path in (*models, netlist)
    )
    if action == "prepare":
        bundle.write_text(simulation)
    assert bundle.read_text() == simulation
    arrays, receivers, macros, sites, leaves, module_count, signals = check_hierarchy(
        netlist, library
    )
    assert (
        sites == board["geometric_capacity"] - board["projected_remaining_global_sites"]
    )
    assert macros == 631
    assert (
        signals
        == read(LINK)["candidate_signal_pins_if_link_replaces_ready_and_adds_clock"]
    )
    assert signals + 13 == read(PAD)["pad_reservations"]
    for path in (netlist, bundle, Path(__file__).resolve().relative_to(ROOT)):
        evidence[str(path)] = digest(path)
    return dict(
        state="buffered_booth_serialized_chip_structurally_linked",
        top=TOP,
        mapped_arrays=arrays,
        gated_receivers=receivers,
        fixed_memory_macros=macros,
        mapped_standard_cell_row_sites=sites,
        reachable_leaves_including_memories=leaves,
        defined_modules=module_count,
        boundary_signal_pins=signals,
        unchanged_array_associations=bindings,
        scope="The mapped chip substitutes two already tested components and proves the twenty original "
        "array pin bindings and reachable leaf inventory. Native elaboration, timed placement and routing are separate.",
        evidence_sha256=evidence,
    )


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("action", choices=("prepare", "verify"))
    print(json.dumps(run(cli.parse_args().action), indent=2, sort_keys=True))
