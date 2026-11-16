"""Measure operand wire spans from the mapped parent outputs to the placed array."""

from collections import Counter, defaultdict
from contextlib import ExitStack
import json
from pathlib import Path
import re
from statistics import median

from build_tri_oracle_booth_chip_seed import hierarchy
from verify_tri_oracle_booth_chip_link import TOP, WORK, named_bindings
from verify_tri_oracle_booth_fence_capacity import PAD, TRANSFER
from verify_tri_oracle_gated_array_placement import section
from verify_tri_oracle_gated_compute_array import ROOT, digest, read
from verify_tri_oracle_pad_cold_reload import components
from verify_tri_oracle_serialized_placement_transfer import catalog, dimensions

LINK = Path("records/tri_oracle_linked_booth_chip.json")
SEED = Path("records/tri_oracle_booth_chip_seed.json")
TIMING = Path("records/tri_oracle_booth_timing_swaps.json")
BUFFER = Path("records/tri_oracle_booth_operand_buffers.json")
CELL = re.compile(rb"(?m)^[ \t]+([\w$]+)\s+(\\\S+|[\w$]+)\s*\(\s*(\.[^;]*)\);")
RANGE = re.compile(rb"(\w+)\[(\d+):(\d+)\]")
SINGLE = re.compile(rb"\w+(?:\[\d+\])?")
START = re.compile(r"(?m)^\s+Startpoint: \([RF]\) (operand_[ab]\[\d+\])$")


def bits(value, count=None):
    fields = value[1:-1].split(b",") if value.startswith(b"{") else [value]
    result = []
    for field in fields:
        if match := RANGE.fullmatch(field):
            name, hi, lo = match.groups()
            assert int(hi) >= int(lo)
            result.extend(
                name + b"[%d]" % bit for bit in range(int(hi), int(lo) - 1, -1)
            )
        else:
            assert SINGLE.fullmatch(field) or re.fullmatch(rb"\d+'b[01xz]+", field), (
                field
            )
            result.append(field)
    if count:
        if SINGLE.fullmatch(value) and b"[" not in value and count > 1:
            result = [value + b"[%d]" % bit for bit in range(count - 1, -1, -1)]
        assert len(result) == count, value
    return result


def lef_ports(paths):
    result = {}
    coords = re.compile(
        r"(?m)^[ \t]+RECT[ \t]+([\d.-]+) +([\d.-]+) +([\d.-]+) +([\d.-]+)\s*;"
    )
    for path in paths:
        for name, body in re.findall(
            r"(?ms)^MACRO (\S+)\s*\n(.*?)^END \1\s*$", path.read_text()
        ):
            pins = {}
            for pin, block in re.findall(
                r"(?ms)^[ \t]+PIN (\S+)[ \t]*\n(.*?)^[ \t]+END \1[ \t]*$", body
            ):
                direction = re.search(
                    r"(?m)^[ \t]+DIRECTION (INPUT|OUTPUT|INOUT|FEEDTHRU).*?;", block
                )
                if not direction:
                    continue
                boxes = [
                    tuple(float(value) * 2000 for value in match)
                    for match in coords.findall(block)
                ]
                if boxes:
                    # Pin access can have several shapes. Use the largest rectangle.
                    x1, y1, x2, y2 = max(
                        boxes, key=lambda p: (p[2] - p[0]) * (p[3] - p[1])
                    )
                    pins[pin.replace("\\", "")] = (
                        direction[1],
                        (x1 + x2) / 2,
                        (y1 + y2) / 2,
                    )
            result[name] = pins
    return result


def locate(pose, pin, shapes, sizes, direction):
    master, _, x, y, orient, _ = pose
    direction_seen, px, py = shapes[master][pin]
    assert direction_seen == direction, (master, pin)
    width, height = sizes[master]
    dx, dy = {
        "N": (px, py),
        "S": (width - px, height - py),
        "FN": (width - px, py),
        "FS": (px, height - py),
        "E": (py, width - px),
        "W": (height - py, px),
        "FE": (py, px),
        "FW": (height - py, width - px),
    }[orient]
    return x + dx, y + dy


def array_parent(modules, children, enclosing, operand_names):
    module = TOP.encode()
    for piece in enclosing.split(b"/"):
        module = children(module)[piece]
    data, start, end = modules[module.decode()]
    text = data[start:end]
    (array,) = [m for m in CELL.finditer(text) if m[2] == b"compute"]
    assert array[1].startswith(b"tri_oracle_pe_array_verified_")
    associated = named_bindings(array[3])
    operands = {}
    for name in operand_names:
        group, bit = name[:-1].split("[")
        value = associated[group]
        if b"[" not in value and not value.startswith(b"{"):
            assert re.search(
                rb"\bwire\s+\[2047:0\]\s+" + re.escape(value) + rb"\s*;", text
            )
        operands[name] = bits(value, 2048)[2047 - int(bit)]
    assert all(SINGLE.fullmatch(bit) for bit in operands.values())
    return text, operands


def output_drivers(text, signals, shapes):
    drivers = {}
    for item in CELL.finditer(text):
        master, name = (item[key].decode() for key in (1, 2))
        if master not in shapes:
            continue
        outs = [port for port, info in shapes[master].items() if info[0] == "OUTPUT"]
        for key, value in named_bindings(item[3]).items():
            if key in outs and value in signals:
                assert value not in drivers, value
                drivers[value] = (name.removeprefix("\\"), key)
            elif value.startswith(b"{") and any(
                port.startswith(key + "[") for port in outs
            ):
                atoms = bits(value)
                for offset, net in enumerate(reversed(atoms)):
                    if net in signals:
                        pin = f"{key}[{offset}]"
                        assert pin in outs and net not in drivers, (master, pin)
                        drivers[net] = (name.removeprefix("\\"), pin)
    assert set(drivers) == signals, sorted(signals - drivers.keys())
    return drivers


def summary(delays):
    sorted_values = sorted(delays)
    return dict(
        count=len(sorted_values),
        min_um=round(sorted_values[0], 2),
        median_um=round(median(sorted_values), 2),
        p90_um=round(sorted_values[(len(sorted_values) - 1) * 9 // 10], 2),
        max_um=round(sorted_values[-1], 2),
    )


def distance(first, second):
    return sum(abs(a - b) for a, b in zip(first, second, strict=True)) / 2000


def report():
    evidence = {}

    def pin(path, proof=None):
        checksum = digest(path)
        if proof is not None:
            assert checksum == proof["evidence_sha256"][str(path)], path
        evidence[str(path)] = checksum
        return path

    link, seed, timing, buffers, pad, old = (
        read(pin(path)) for path in (LINK, SEED, TIMING, BUFFER, PAD, TRANSFER)
    )
    linked = pin(WORK / "linked.v", link)
    board = pin(WORK / "placement_seed.def", seed)
    packing = read(pin(WORK / "packing_proof.json", seed))
    scopes = pin(WORK / "packing/fences.tsv", packing)
    moved = pin(WORK / "packing/displaced.tsv", packing)
    displaced = {}
    for line in moved.read_bytes().splitlines():
        instance, master, x, y = line.split(b"\t")
        full_name = old["path_prefix"].encode() + instance.replace(b"\\", b"")
        assert full_name not in displaced
        displaced[full_name] = (master.decode(), int(x), int(y))
    lefs = [pin(Path(k), pad) for k in pad["evidence_sha256"] if k.endswith(".lef")]
    sizes = dimensions(lefs, 2000)
    shapes = lef_ports(lefs)
    assert set(sizes) == set(shapes)
    (physical,) = (
        pin(Path(k), timing)
        for k in timing["evidence_sha256"]
        if k.endswith("/timing_swaps/placed.def")
    )
    (old_paths,) = (
        pin(Path(k), timing)
        for k in timing["evidence_sha256"]
        if k.endswith("/timing_swaps/native_setup.rpt")
    )
    (new_paths,) = (
        pin(Path(k), buffers)
        for k in buffers["evidence_sha256"]
        if k.endswith("/operand_buffers/native_setup.rpt")
    )
    critical = sorted(
        set(START.findall(old_paths.read_text()) + START.findall(new_paths.read_text()))
    )
    assert critical
    lanes = sorted({int(name.split("[")[1][:-1]) // 8 for name in critical})
    names = [
        f"operand_{port}[{lane * 8 + bit}]"
        for lane in lanes
        for port in "ab"
        for bit in range(8)
    ]
    graph = defaultdict(list)
    edges = pin(old_paths.parent / "edges.tsv", timing)
    for line in edges.read_text().splitlines():
        source, target, fanout = line.split("\t")
        if source in names:
            graph[source].append((target, int(fanout)))
    assert set(graph) == set(names)
    assert all(len(loads) == loads[0][1] for loads in graph.values())
    sinks = {item[0] for refs in graph.values() for item in refs}
    origin = dict(components(physical))
    _, terms = section(physical.read_text(), "PINS")
    positions = {
        name: (int(x), int(y))
        for name, x, y in re.findall(
            r"(?ms)^- (operand_[ab]\[\d+\]) \+ NET .*?\+ PLACED \( (\d+) (\d+) \) \w+ ;",
            terms,
        )
    }
    native_ref = {}
    for name in names:
        for term, _ in graph[name]:
            leaf, pin_name = term.rsplit("/", 1)
            pose = origin[leaf.replace("[", "\\[").replace("]", "\\]").encode()]
            native_ref[name, term] = distance(
                positions[name], locate(pose, pin_name, shapes, sizes, "INPUT")
            )
    del origin

    owners = {}
    required = set()
    with ExitStack() as stack:
        modules = catalog(stack, [linked])
        children, _ = hierarchy(modules)
        for line in scopes.read_bytes().splitlines():
            region, root = line.split(b"\t")
            full = old["path_prefix"].encode() + root.replace(b"\\", b"")
            parent, _, item = full.rpartition(b"/")
            assert item == b"compute"
            description, associations = array_parent(modules, children, parent, names)
            sources = output_drivers(description, set(associations.values()), shapes)
            owners[region.decode()] = (
                full,
                {
                    name: (parent + b"/" + sources[net][0].encode(), sources[net][1])
                    for name, net in associations.items()
                },
            )
            required.update(value[0] for value in owners[region.decode()][1].values())
            required.update(
                full + b"/" + term.rsplit("/", 1)[0].encode() for term in sinks
            )
    chosen = {}
    for name, pose in components(board):
        canonical = name.replace(b"\\", b"")
        if canonical in required:
            assert canonical not in chosen
            chosen[canonical] = pose
    assert len(owners) == 20 and chosen.keys() == required, chosen.keys() ^ required
    measured = {}
    full_spans = defaultdict(list)
    classes = Counter()
    longest_by_driver = {}
    long_paths = Counter()
    for region, (full, sources) in owners.items():
        spans = []
        for name, (source, source_pin) in sources.items():
            driver = chosen[source]
            classes[
                "sram" if driver[0].startswith(("TS5N28", "TS6N28")) else "logic"
            ] += 1
            start = locate(driver, source_pin, shapes, sizes, "OUTPUT")
            previous = displaced.get(source)
            if previous:
                assert driver[0] == previous[0] and driver[2:4] != previous[1:]
            kind = (
                "relocated_logic"
                if previous
                else "fixed_memory"
                if driver[1] == "FIXED"
                else "retained_logic"
            )
            for term, _ in graph[name]:
                leaf, pin_name = term.rsplit("/", 1)
                finish = locate(
                    chosen[full + b"/" + leaf.encode()],
                    pin_name,
                    shapes,
                    sizes,
                    "INPUT",
                )
                length = distance(start, finish)
                full_spans[name].append(length)
                spans.append(length)
                if length > 2000:
                    long_paths[kind] += 1
                if (
                    source not in longest_by_driver
                    or length > longest_by_driver[source][0]
                ):
                    details = dict(
                        region=region,
                        operand=name,
                        driver=source.decode(),
                        driver_pin=source_pin,
                        driver_kind=kind,
                        load=term,
                        span_um=round(length, 2),
                        output_pin_um=[round(value / 2000, 3) for value in start],
                        input_pin_um=[round(value / 2000, 3) for value in finish],
                    )
                    if previous:
                        details["previous_driver_origin_um"] = [
                            coordinate / 2000 for coordinate in previous[1:]
                        ]
                    longest_by_driver[source] = length, details
        measured[region] = summary(spans)
    pin(Path(__file__).resolve().relative_to(ROOT))
    return {
        "state": "linked_booth_array_operands_traced_to_placed_drivers",
        "selected_multiplier_lanes": lanes,
        "operand_bits_per_region": len(names),
        "array_regions": len(measured),
        "driver_kind_by_operand_bit": classes,
        "critical_operand_spans": {
            key: dict(
                full_chip=summary(full_spans[key]),
                isolated_array=summary(
                    [span for (bit, _), span in native_ref.items() if bit == key]
                ),
            )
            for key in critical
        },
        "isolated_array_spans": summary(list(native_ref.values())),
        "on_chip_spans": summary(
            [span for values in full_spans.values() for span in values]
        ),
        "on_chip_spans_by_region": measured,
        "on_chip_spans_over_2000_um_by_driver_kind": long_paths,
        "longest_twelve_unique_drivers": [
            details
            for _, details in sorted(
                longest_by_driver.values(), key=lambda pair: -pair[0]
            )[:12]
        ],
        "scope": "Manhattan spans from the selected logic and memory output pin shapes to array input loads in the current whole-chip seed. The standalone region uses its fixed terminal anchors. These geometric spans do not estimate detailed route length or path delay.",
        "evidence_sha256": evidence,
    }


if __name__ == "__main__":
    assert Path.cwd() == ROOT and __debug__
    print(json.dumps(report(), sort_keys=True, indent=2))
