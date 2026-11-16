"""Place the linked top's signal terminals inside the audited perimeter slots."""

from collections import Counter
from hashlib import sha256
import json
from mmap import ACCESS_READ, mmap
from pathlib import Path
import re
import shutil

from audit_tri_oracle_pad_ring_clearance import contains, overlap
from audit_tri_oracle_placed_chip_boundary import check_ports
from verify_tri_oracle_booth_chip_geometry import geometry
from verify_tri_oracle_booth_chip_link import TOP, WORK
from verify_tri_oracle_booth_fence_capacity import PAD, read_table
from verify_tri_oracle_gated_compute_array import ROOT, digest, read
from verify_tri_oracle_host_control import outer_ports

GEOMETRY = Path("records/tri_oracle_booth_chip_geometry.json")
LINK = Path("records/tri_oracle_linked_booth_chip.json")
PAD_BUDGET = Path("records/tri_oracle_bonded_pad_capacity.json")
BOUNDARY = b"\nEND COMPONENTS\n"
TERMINALS = re.compile(
    rb"^- (\S+) \+ NET (\S+) \+ DIRECTION (INPUT|OUTPUT) \+ USE SIGNAL\n"
    rb"  \+ LAYER (M4|M5) \( -50 0 \) \( 50 2000 \)\n"
    rb"  \+ FIXED \( (\d+) (\d+) \) ([NEWS]) ;$",
    re.MULTILINE,
)
RING = ("bottom", "right", "top", "left")


def read_ports(linked):
    with (
        linked.open("rb") as stream,
        mmap(stream.fileno(), 0, access=ACCESS_READ) as data,
    ):
        label = f"\nmodule {TOP} (\n".encode()
        start = data.rfind(label)
        assert start >= 0 and data.find(label, 0, start) == -1
        stop = data.find(b"\n);", start)
        assert 0 < stop - start < 8192
        return outer_ports(data[start : stop + 3].decode())


def terminal(edge, body, tracks):
    left, bottom, right, top = body
    horizontal = edge in ("left", "right")
    layer, axis = ("M4", "Y") if horizontal else ("M5", "X")
    origin, count, pitch = tracks[layer, axis]
    center = (bottom + top) // 2 if horizontal else (left + right) // 2
    index = (center - origin + pitch // 2) // pitch
    assert 0 <= index < count
    at = origin + index * pitch
    return {
        "left": (layer, right - 2000, at, "E"),
        "right": (layer, left + 2000, at, "W"),
        "bottom": (layer, at, top - 2000, "N"),
        "top": (layer, at, bottom + 2000, "S"),
    }[edge]


def terminal_box(x, y, orientation):
    if orientation == "E":
        return x, y - 50, x + 2000, y + 50
    if orientation == "W":
        return x - 2000, y - 50, x, y + 50
    if orientation == "N":
        return x - 50, y, x + 50, y + 2000
    assert orientation == "S"
    return x - 50, y - 2000, x + 50, y


def pins(ports, slots, reserved, tracks):
    grouped = {edge: [] for edge in RING}
    for slot in slots:
        body = tuple(int(slot["body_" + k]) for k in ("x1", "y1", "x2", "y2"))
        grouped[slot["edge"]].append(body)

    ordered = []
    held = Counter()
    for edge, edge_slots in grouped.items():
        edge_slots.sort(reverse=edge in {"top", "left"})
        positions = {0, len(edge_slots) - 1}
        # Keep the first and last positions on each side for the original ground allowance.
        held["corner_ground"] += len(positions)
        for index, kind in reserved[edge]:
            slot = len(edge_slots) * index // 4
            assert slot not in positions
            positions.add(slot)
            held[kind] += 1
        ordered.extend(
            (edge, body) for i, body in enumerate(edge_slots) if i not in positions
        )

    # Keep the dense 448-bit response bus in contiguous, perimeter-ordered pin sites.
    bits = [
        (bit, direction)
        for port in sorted(ports, key=lambda name: name == "memory_mem_rsp_data")
        for direction, width in (ports[port],)
        for bit in ([port] if width is None else (f"{port}[{i}]" for i in range(width)))
    ]
    lines = [f"PINS {len(bits)} ;"]
    positions_by_pin = {}
    for (name, direction), (edge, body) in zip(bits, ordered, strict=True):
        layer, x, y, side = terminal(edge, body, tracks)
        lines.extend(
            (
                f"- {name} + NET {name} + DIRECTION {direction} + USE SIGNAL",
                f"  + LAYER {layer} ( -50 0 ) ( 50 2000 )",
                f"  + FIXED ( {x} {y} ) {side} ;",
            )
        )
        positions_by_pin[name] = edge, body, (layer, x, y, side)
    lines.extend(("END PINS", ""))
    return "\n".join(lines).encode(), positions_by_pin, held


def verify_section(section, ports, assigned):
    matches = list(TERMINALS.finditer(section))
    assert len(matches) == len(assigned) == 484
    assert section.count(b"\n") == 3 * len(matches) + 2
    observed = {}
    by_edge = Counter()
    shapes = []
    for match in matches:
        name, net, direction, layer, x, y, side = (
            item.decode() for item in match.groups()
        )
        assert name == net and name not in observed
        observed[name] = direction
        edge, body, position = assigned[name]
        assert (layer, int(x), int(y), side) == position
        shape = terminal_box(int(x), int(y), side)
        assert contains(body, shape), (name, edge, body, shape)
        shapes.append(shape)
        by_edge[edge] += 1
    check_ports(ports, observed)
    for i, shape in enumerate(shapes):
        assert not any(overlap(shape, prior) for prior in shapes[:i])
    return by_edge


def prepare():
    proof, link, pad, budget = (read(p) for p in (GEOMETRY, LINK, PAD, PAD_BUDGET))
    source, linked = WORK / "placement_seed.def", WORK / "linked.v"
    (slot_path,) = (
        Path(k) for k in pad["evidence_sha256"] if k.endswith("/pad_slots.tsv")
    )
    assert digest(linked) == link["evidence_sha256"][str(linked)]
    assert digest(slot_path) == proof["evidence_sha256"][str(slot_path)]
    assert digest(source) == proof["evidence_sha256"][str(source)]
    assert shutil.disk_usage(WORK).free >= source.stat().st_size + (1 << 20)
    ports = read_ports(linked)
    slots = read_table(slot_path)
    assert all(
        contains(
            tuple(int(entry["keepout_" + k]) for k in ("x1", "y1", "x2", "y2")),
            tuple(int(entry["body_" + k]) for k in ("x1", "y1", "x2", "y2")),
        )
        for entry in slots
    )

    reserved = {
        "bottom": [(2, "core_supply")],
        "right": [(2, "io_supply")],
        "top": [(1, "core_supply"), (3, "io_supply")],
        "left": [(2, "core_supply")],
    }
    target = WORK / "placement_with_terminal_seed.def"
    partial = target.with_suffix(".partial")
    with (
        source.open("rb") as stream,
        mmap(stream.fileno(), 0, access=ACCESS_READ) as data,
    ):
        split = data.find(BOUNDARY)
        assert split > 0
        split += len(BOUNDARY)
        assert data.find(b"\nPINS ") < 0
        header_end = data.find(b"\nCOMPONENTS ")
        tracks = {
            (layer.decode(), axis.decode()): (int(origin), int(count), int(pitch))
            for axis, origin, count, pitch, layer in re.findall(
                rb"(?m)^TRACKS ([XY]) (\d+) DO (\d+) STEP (\d+) LAYER (M4|M5) ;$",
                data[:header_end],
            )
        }
        section, assigned, held = pins(ports, slots, reserved, tracks)
        by_edge = verify_section(section, ports, assigned)
        assert (
            held == budget["illustrative_supply_and_ground_pads"]
            and len(slots)
            == sum(held.values()) + len(assigned)
            == pad["pad_reservations"]
        )

        with partial.open("wb") as dest, memoryview(data) as original:
            dest.write(original[:split])
            dest.write(section)
            dest.write(original[split:])
    with (
        partial.open("rb") as stream,
        mmap(stream.fileno(), 0, access=ACCESS_READ) as data,
    ):
        assert data.find(b"\nPINS ") == split - 1
        end = data.find(b"\nEND PINS\n", split) + len(b"\nEND PINS\n")
        assert data[split:end] == section
        unchanged = sha256()
        with memoryview(data) as modified:
            unchanged.update(modified[:split])
            unchanged.update(modified[end:])
        assert unchanged.hexdigest() == proof["evidence_sha256"][str(source)]
    assert geometry(partial, verify_top=True) == geometry(source, verify_top=True)
    partial.replace(target)
    files = (
        source,
        linked,
        slot_path,
        target,
        LINK,
        PAD,
        PAD_BUDGET,
        GEOMETRY,
        Path(__file__).resolve().relative_to(ROOT),
    )
    return {
        "state": "whole_chip_signal_terminals_fit_verified_perimeter_slots",
        "signal_terminals": len(assigned),
        "terminal_counts_by_edge": by_edge,
        "unassigned_supply_and_ground_reservations": held,
        "scope": "The placed signal terminals use track-aligned metal shapes inside the reserved slots. The allocation preserves the component and blockage sections byte for byte. The slot allocation is a placement seed. Bond pad cells, power and ground connectivity, and signal timing have separate physical requirements.",
        "evidence_sha256": {str(path): digest(path) for path in files},
    }


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    print(json.dumps(prepare(), indent=2, sort_keys=True))
