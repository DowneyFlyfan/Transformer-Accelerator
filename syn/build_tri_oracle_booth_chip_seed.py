"""Bind the verified Booth chip's row-slot assignments to the linked leaf names."""

from collections import Counter, defaultdict
from contextlib import ExitStack
from functools import lru_cache
from hashlib import sha256
import json
import mmap
from pathlib import Path
import re
import struct

from plan_tri_oracle_bonded_pad_recovery import ROW, section
from verify_tri_oracle_booth_chip_link import INSTANCE, TOP, WORK
from verify_tri_oracle_booth_fence_capacity import PAD, REFINED, TRANSFER, read_table
from verify_tri_oracle_gated_compute_array import ROOT, digest, read
from verify_tri_oracle_serialized_placement_transfer import (
    catalog,
    components,
    dimensions,
)

LINK = Path("records/tri_oracle_linked_booth_chip.json")
AREA = Path("records/tri_oracle_booth_fence_capacity.json")
PACK = WORK / "packing"
PACK_PROOF = WORK / "packing_proof.json"
PITCH = 280
SLOT = struct.Struct("<III")


def entries(path):
    for line in path.read_bytes().splitlines():
        yield line.split(b"\t")


def placed(output, name, master, x, y, side):
    output.write(b"- %s %s + PLACED ( %d %d ) %s ;\n" % (name, master, x, y, side))


def fixed(output, name, master, x, y, side, halo):
    output.write(
        b"- %s %s + FIXED ( %d %d ) %s\n  + HALO %d %d %d %d\n ;\n"
        % (name, master, x, y, side, *halo)
    )


def coordinate_slots(path):
    result = defaultdict(list)
    for width, x, y in SLOT.iter_unpack(path.read_bytes()):
        result[width].append((x, y))
    return result


def orient(side, reference):
    if reference in (b"FN", b"S"):
        return b"FN" if side == b"N" else b"S"
    assert reference in (b"N", b"FS")
    return side


def canonical(name):
    return name.replace(b"\\", b"")


def def_name(name):
    assert re.fullmatch(rb"[\w.$/\[\]]+", name), name
    return name.replace(b"[", b"\\[").replace(b"]", b"\\]")


def spatial(x, y):
    return y // 201600, x // 201600, y, x


def hierarchy(modules):
    @lru_cache(maxsize=64)
    def children(master):
        data, start, end = modules[master.decode()]
        result = {}
        for match in INSTANCE.finditer(data, start, end):
            child, name = match.groups()
            name = name.removeprefix(b"\\")
            assert b"/" not in name and name not in result, (master, name)
            result[name] = child
        return result

    def leaves(master, prefix=b""):
        if master.decode() not in modules:
            yield prefix.removesuffix(b"/"), master
            return
        for name, child in children(master).items():
            yield from leaves(child, prefix + name + b"/")

    return children, leaves


def additional_leaves(linked, transfer):
    with ExitStack() as stack:
        modules = catalog(stack, [linked])
        children, leaves = hierarchy(modules)
        for block in transfer["added_blocks"]:
            master = TOP.encode()
            for name in block["instance"].encode().split(b"/"):
                master = children(master)[name]
            assert master.decode() == block["master"], block
            yield from leaves(master, block["instance"].encode() + b"/")


def identity(values):
    checksum = 0
    count = 0
    for name, master in values:
        token = canonical(name) + b"\0" + master
        checksum = (checksum + int.from_bytes(sha256(token).digest(), "big")) % (
            1 << 256
        )
        count += 1
    return count, f"{checksum:064x}"


def write_def(output, cold, linked, array_def, proof, transfer, moves, size):
    prefix = transfer["path_prefix"].encode()
    region_paths = dict(entries(PACK / "fences.tsv"))
    names_to_regions = {name + b"/": region for region, name in region_paths.items()}
    assert len(region_paths) == len(names_to_regions) == 20
    root = re.escape(
        next(iter(names_to_regions)).split(b"cores")[0].split(b"clusters")[0]
    )
    owner = re.compile(root + rb".*?/cores\\\[\d+\\\]/compute/compute/")
    displaced = {
        name: (master, int(x), int(y))
        for name, master, x, y in entries(PACK / "displaced.tsv")
    }
    region_count, moved_rows = Counter(), Counter()
    with (
        cold.open("rb") as stream,
        mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data,
    ):
        groups = section(data, b"GROUPS")
        groups = re.sub(
            r"(?m)^([ \t]+)([^\s]+\*)$", lambda m: m[1] + prefix.decode() + m[2], groups
        )
        start = data.find(b"\nVERSION ") + 1
        stop = data.find(b"\nCOMPONENTS ")
        assert 0 < start < stop
        header, changed = re.subn(
            rb"(?m)^DESIGN \w+ ;$", f"DESIGN {TOP} ;".encode(), data[start:stop]
        )
        assert changed == 1
    rows = {}
    for line in header.decode().splitlines():
        if match := ROW.match(line):
            rows[int(match[2])] = match[3].encode()
    assert len(rows) == 2966

    kept = fixed_count = 0
    parents = defaultdict(list)
    with output.open("wb") as dest:
        dest.write(
            header
            + f"\nCOMPONENTS {proof['reachable_leaves_including_memories']} ;\n".encode()
        )
        for name, (master, status, x, y, side, halo) in components(cold):
            master_bytes = master.encode()
            if status == "FIXED":
                new_x, new_y = moves.get(name, (x, y))
                if name in moves:
                    assert (new_x, new_y) != (x, y)
                    moved_rows["memories"] += 1
                fixed(
                    dest, prefix + name, master_bytes, new_x, new_y, side.encode(), halo
                )
                fixed_count += 1
            elif match := owner.match(name):
                region_count[names_to_regions[match[0]]] += 1
            elif name in displaced:
                assert displaced.pop(name) == (master_bytes, x, y)
                parents[size[master][0] // PITCH].append(
                    (prefix + name, master_bytes, x, y)
                )
                moved_rows["parent"] += 1
            else:
                assert status == "PLACED"
                placed(dest, prefix + name, master_bytes, x, y, side.encode())
                kept += 1
        assert (
            not displaced
            and len(region_count) == 20
            and len(set(region_count.values())) == 1
        )
        assert fixed_count == proof["fixed_memory_macros"] == 631 and moved_rows[
            "memories"
        ] == len(moves)

        exemplar = defaultdict(list)
        for name, (master, status, x, y, side, _) in components(array_def):
            assert status == "PLACED"
            exemplar[size[master][0] // PITCH].append(
                (name, master.encode(), x, y, side.encode())
            )
        for cells in exemplar.values():
            cells.sort(key=lambda item: (*spatial(item[2], item[3]), item[0]))
        arrays = 0
        for region, owner_path in sorted(region_paths.items()):
            positions = coordinate_slots(PACK / (region.decode() + ".bin"))
            assert positions.keys() == exemplar.keys()
            x0 = min(x for points in positions.values() for x, _ in points)
            y0 = min(y for points in positions.values() for _, y in points)
            for width, slots in sorted(positions.items()):
                slots.sort(
                    key=lambda xy: spatial(xy[0] - x0 + 40000, xy[1] - y0 + 40000)
                )
                for (name, master, _, _, side), (x, y) in zip(
                    exemplar[width], slots, strict=True
                ):
                    placed(
                        dest,
                        prefix + owner_path + b"/" + name,
                        master,
                        x,
                        y,
                        orient(rows[y], side),
                    )
                    arrays += 1
        assert arrays == 20 * sum(map(len, exemplar.values()))

        for name, master in additional_leaves(linked, transfer):
            parents[size[master.decode()][0] // PITCH].append(
                (def_name(name), master, 3600000, 3600000)
            )
            moved_rows["wrapper"] += 1
        all_slots = coordinate_slots(PACK / "parent.bin")
        assert all_slots.keys() == parents.keys()
        for width, slots in sorted(all_slots.items()):
            jobs = sorted(
                parents[width], key=lambda item: (*spatial(item[2], item[3]), item[0])
            )
            for (name, master, _, _), (x, y) in zip(
                jobs, sorted(slots, key=lambda xy: spatial(*xy)), strict=True
            ):
                placed(dest, name, master, x, y, rows[y])
        dest.write(b"END COMPONENTS\n")

        keepouts = list(entries(PACK / "keepouts.tsv"))
        dest.write(f"BLOCKAGES {len(keepouts)} ;\n".encode())
        for box in keepouts:
            dest.write(b"- PLACEMENT RECT ( %s %s ) ( %s %s ) ;\n" % tuple(box))
        dest.write(b"END BLOCKAGES\nGROUPS 20 ;\n")
        dest.write(groups.encode() + b"\nEND GROUPS\nEND DESIGN\n")
    assert (
        kept + fixed_count + arrays + moved_rows["parent"] + moved_rows["wrapper"]
        == proof["reachable_leaves_including_memories"]
    )
    return dict(
        retained_parent_locations=kept,
        fixed_memory_macros=fixed_count,
        shifted_memory_macros=moved_rows["memories"],
        array_leaf_locations=arrays,
        relocated_parent_cells=moved_rows["parent"],
        new_wrapper_cells=moved_rows["wrapper"],
        pad_and_corner_keepouts=len(keepouts),
    )


def build():
    board = read(AREA)
    packing = read(PACK_PROOF)
    link = read(LINK)
    transfer = read(TRANSFER)
    pad = read(PAD)
    assert {k: v for k, v in packing.items() if k != "evidence_sha256"} == {
        k: v for k, v in board.items() if k != "evidence_sha256"
    }

    def pinned(path, receipt):
        expected = receipt["evidence_sha256"][str(path)]
        assert digest(path) == expected, path
        return path

    (cold,) = (
        pinned(Path(k), pad)
        for k in pad["evidence_sha256"]
        if k.endswith("/cold/layout.def")
    )
    lefs = [pinned(Path(k), pad) for k in pad["evidence_sha256"] if k.endswith(".lef")]
    size = dimensions(lefs, 2000)
    linked = pinned(WORK / "linked.v", link)
    refined = read(REFINED)
    (array_def,) = (
        pinned(Path(k), refined)
        for k in refined["evidence_sha256"]
        if k.endswith("/timing_swaps/placed.def")
    )
    for artifact in PACK.iterdir():
        pinned(artifact, packing)
    (move_table,) = (
        pinned(Path(k), pad)
        for k in pad["evidence_sha256"]
        if k.endswith("/memory_macros.tsv")
    )
    moves = {
        row["instance"].encode(): (int(row["x_dbu"]), int(row["y_dbu"]))
        for row in read_table(move_table)
    }
    output = WORK / "placement_seed.def"
    partial = output.with_suffix(".partial")
    facts = write_def(partial, cold, linked, array_def, link, transfer, moves, size)
    with ExitStack() as stack:
        _, leaves = hierarchy(catalog(stack, [linked]))
        expected = identity(leaves(TOP.encode()))
    observed = identity(
        (name, state[0].encode()) for name, state in components(partial)
    )
    assert (
        observed == expected
        and observed[0] == link["reachable_leaves_including_memories"]
    ), (observed, expected)
    assert facts["relocated_parent_cells"] == board["parent_cells_to_relocate"]
    assert facts["retained_parent_locations"] == board["kept_parent_cells"]
    assert facts["array_leaf_locations"] == 20 * board["leaf_cells_per_array"]
    partial.replace(output)
    return dict(
        state="full_booth_chip_component_seed_linked",
        exact_linked_leaf_count=observed[0],
        normalized_component_identity=observed[1],
        **facts,
        scope="Every linked leaf is assigned a position from the verified packing. The seed preserves the original rows and array regions. "
        "The top-level signal pin locations and native placement checks require separate verification.",
        evidence_sha256={
            str(path): digest(path)
            for path in (
                LINK,
                AREA,
                TRANSFER,
                PAD,
                REFINED,
                PACK_PROOF,
                output,
                linked,
                Path(__file__).resolve().relative_to(ROOT),
            )
        },
    )


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    print(json.dumps(build(), indent=2, sort_keys=True))
