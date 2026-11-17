"""Place the mapped wrapper control logic on the exact Booth chip seed."""

from argparse import ArgumentParser
from bisect import bisect_left, bisect_right
from contextlib import ExitStack
import json
from pathlib import Path
import re

from audit_tri_oracle_pad_ring_clearance import overlap
from audit_tri_oracle_physical_io_budget import macro_boxes
from build_tri_oracle_booth_chip_seed import def_name, hierarchy, placed
from prepare_tri_oracle_booth_chip_native import NATIVE
from link_tri_oracle_indexed_whole_chip import signature
from verify_tri_oracle_booth_chip_geometry import geometry, layout
from verify_tri_oracle_booth_chip_link import TOP, WORK, pieces
from verify_tri_oracle_gated_compute_array import ROOT, digest, read
from verify_tri_oracle_pad_cold_reload import components
from verify_tri_oracle_serialized_placement_transfer import catalog, dimensions

TRIAL = WORK / "native_glue"
RETRY = TRIAL / "retry"
INPUTS = Path("records/tri_oracle_booth_chip_native_inputs.json")
OWNER = "tri_oracle_chip_packet_io"
STATUS_OWNER = "tri_oracle_chip_host_status_io"
GLUE = "tri_oracle_boundary_control"
HEIGHT = 2400
BENCH = Path("verilog/tri_oracle_boundary_control_tb.sv")
SYNTHESIS = Path("syn/tri_oracle_synthesize_booth_native_glue.tcl")
EQUATIONS = re.compile(
    rb"(?m)^  assign (?:merge_start|merge_finish|config_valid|host_config_enable) = [^;]+;\n"
)
STATUS_INIT = re.compile(rb"(?m)^  wire \[26:0\] chip_status = (\{[^;]+\});$")
PORTS = (
    "command_valid command_ready command_opcode response_valid response_opcode "
    "payload_valid payload_ready payload_last merge_start merge_finish config_valid host_config_enable"
).split()


def write_linked(source, mapped, reference, target):
    with ExitStack() as stack:
        modules = catalog(stack, [source, mapped])
        children, leaves = hierarchy(modules)

        def paths(master, prefix=b""):
            if master == OWNER.encode():
                yield prefix
            elif master.decode() in modules:
                for name, child in children(master).items():
                    if child.decode() in modules:
                        yield from paths(child, prefix + name + b"/")

        (owner_path,) = paths(TOP.encode())
        instances = children(OWNER.encode())
        assert b"boundary_control" not in instances and b"sign_fetch" in instances
        assert b"host_link" in instances

        original, start, stop = modules[OWNER]
        replacement = original[start:stop]
        assert len(EQUATIONS.findall(replacement)) == 4
        assert EQUATIONS.findall(replacement) == EQUATIONS.findall(
            reference.read_bytes()
        )
        replacement = EQUATIONS.sub(b"", replacement)
        ports = ",\n    ".join(f".{name}({name})" for name in PORTS)
        assert replacement.endswith(b"endmodule")
        replacement = replacement.removesuffix(b"endmodule") + (
            f"  {GLUE} boundary_control (\n    {ports}\n  );\nendmodule".encode()
        )

        raw, status_start, status_stop = modules[STATUS_OWNER]
        assert raw is original
        status, count = STATUS_INIT.subn(
            rb"  wire [26:0] chip_status;\n  assign chip_status = \1;",
            original[status_start:status_stop],
        )
        assert count == 1

        mapped_source, mapped_start, mapped_end = modules[GLUE]
        module = mapped_source[mapped_start:mapped_end] + b"\n"
        assert signature(module) == signature(reference.read_bytes())
        edits = [(start, stop, replacement), (status_start, status_stop, status)]
        with target.open("xb") as stream:
            stream.writelines(pieces(original, edits))
            stream.write(b"\n" + module)
        control_cells = list(leaves(GLUE.encode(), owner_path + b"boundary_control/"))
        assert control_cells and all(
            master.decode() not in modules for _, master in control_cells
        )
        return control_cells, owner_path


def allocate_slots(seed, added, owner, physical, sizes):
    die, units, rows, _, _, blockages = physical
    assert units == 2000
    keys = sorted(rows)
    left, _, columns, pitch = rows[keys[0]]
    bottom = keys[0]
    assert keys == list(range(bottom, bottom + len(rows) * HEIGHT, HEIGHT))
    grid = [bytearray(columns) for _ in keys]
    fixed = {}
    expected = {name for name, _ in added}
    support = tuple(owner + item for item in (b"host_link/", b"sign_fetch/"))
    bounds = [die[2], die[3], die[0], die[1]]
    for name, coordinate in components(seed):
        master, status, x, y, _, _ = coordinate
        assert name not in expected
        if status == "FIXED":
            fixed[name] = coordinate
            continue
        width, height = sizes[master]
        assert status == "PLACED" and height == HEIGHT and width % pitch == 0
        row = grid[(y - bottom) // HEIGHT]
        col = (x - left) // pitch
        row[col : col + width // pitch] = b"\x01" * (width // pitch)
        if name.startswith(support):
            bounds = [
                min(bounds[0], x),
                min(bounds[1], y),
                max(bounds[2], x + width),
                max(bounds[3], y + height),
            ]
    assert len(fixed) == 631 and bounds[2] > bounds[0] and bounds[3] > bounds[1]
    _, halos = macro_boxes(fixed, sizes)
    obstructions = blockages + list(halos.values())
    # The array groups constrain their members. Parent cells already occupy
    # the same regions across the die, so only physical obstructions apply here.
    for x1, y1, x2, y2 in obstructions:
        col1, col2 = (
            max(0, (x1 - left) // pitch),
            min(columns, -(-(x2 - left) // pitch)),
        )
        if col1 < col2:
            for index in range(bisect_right(keys, y1 - HEIGHT), bisect_left(keys, y2)):
                grid[index][col1:col2] = b"\x01" * (col2 - col1)

    cx, cy = (bounds[0] + bounds[2]) // 2, (bounds[1] + bounds[3]) // 2
    slots = [
        (y, gap.start(), gap.end())
        for y, row in zip(keys, grid, strict=True)
        for gap in re.finditer(rb"\x00+", row)
    ]
    extra = []
    for name, master in added:
        width, height = sizes[master.decode()]
        assert height == HEIGHT and width % pitch == 0
        size = width // pitch
        best = None
        for index, (y, start, end) in enumerate(slots):
            if end - start >= size:
                col = min(max((cx - left) // pitch, start), end - size)
                x = left + col * pitch
                candidate = (abs(x - cx) + abs(y - cy), index, col, x, y)
                if best is None or candidate < best:
                    best = candidate
        assert best is not None, master
        _, index, col, x, y = best
        _, start, end = slots[index]
        slots[index] = (y, start, col)
        slots.append((y, col + size, end))
        bbox = (x, y, x + width, y + height)
        assert not any(overlap(box, bbox) for box in obstructions)
        extra.append((def_name(name), master, x, y, rows[y][1].encode()))
    return extra, fixed, obstructions


def write_seed(original, new, count, extra):
    with original.open("rb") as source, new.open("xb") as result:
        adjustments = 0
        for line in source:
            if line == f"COMPONENTS {count} ;\n".encode():
                line = f"COMPONENTS {count + len(extra)} ;\n".encode()
                adjustments += 1
            if line == b"END COMPONENTS\n":
                for pose in extra:
                    placed(result, *pose)
                adjustments += 1
            result.write(line)
        assert adjustments == 2


def fixture_bytes():
    linked = WORK / "linked.v"
    inputs = read(INPUTS)
    assert digest(linked) == inputs["evidence_sha256"][str(linked)]
    with ExitStack() as stack:
        modules = catalog(stack, [linked])
        data, start, end = modules[OWNER]
        equations = EQUATIONS.findall(data, start, end)
    assert len(equations) == 4
    return (
        f"module {GLUE}({', '.join(PORTS)});\n".encode()
        + b"  input command_valid, command_ready, response_valid, payload_valid, payload_ready, payload_last;\n"
        + b"  input [2:0] command_opcode, response_opcode;\n"
        + b"  output merge_start, merge_finish, config_valid, host_config_enable;\n"
        + b"".join(equations)
        + b"endmodule\n"
    )


def extract():
    fixture = fixture_bytes()
    for portion in ("before", "mapped", "after", "replay"):
        (TRIAL / portion).mkdir(parents=True, exist_ok=True)
    paths = {
        TRIAL / "before/source.v": fixture,
        TRIAL / "replay/reference.v": fixture.replace(
            f"module {GLUE}(".encode(), b"module boundary_reference(", 1
        ),
        TRIAL / "replay/lockstep.sv": BENCH.read_bytes(),
    }
    for path, data in paths.items():
        with path.open("xb") as stream:
            stream.write(data)


def verify_fixture():
    before = TRIAL / "before/console.log"
    mapped_log = TRIAL / "mapped/console.log"
    after = TRIAL / "after/console.log"
    replay = TRIAL / "replay/xrun.log"
    assert "**ERROR: (IMPVL-209)" in before.read_text()
    assert "TRI_ORACLE_GLUE_GENUS_PASS" in mapped_log.read_text().splitlines()
    assert "TRI_ORACLE_GLUE_NATIVE_PARSE_PASS" in after.read_text().splitlines()
    assert (
        "TRI_ORACLE_BOUNDARY_GLUE_EQUIVALENT binary_vectors=4096"
        in replay.read_text().splitlines()
    )
    return before, mapped_log, after, replay


def prepare():
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    evidence = verify_fixture()
    old_net = WORK / "linked.v"
    old_seed = WORK / "placement_with_terminal_seed.def"
    inputs = read(INPUTS)
    sources = inputs["evidence_sha256"]
    lib_paths = [Path(name) for name in sources if name.endswith(".lef")]
    for path in (old_net, old_seed, *lib_paths):
        assert digest(path) == sources[str(path)], path
    sizes = dimensions(lib_paths, 2000)
    mapped, reference = TRIAL / "mapped/netlist.v", TRIAL / "before/source.v"
    RETRY.mkdir(exist_ok=False)
    new_net, new_seed, plan = (
        RETRY / name for name in ("linked.v", "seed.def", "plan.tcl")
    )
    leaves, owner = write_linked(old_net, mapped, reference, new_net)
    physical = geometry(old_seed, verify_top=True)
    extra, fixed, obstructions = allocate_slots(
        old_seed, leaves, owner, physical, sizes
    )
    count = inputs["physical_components"]
    write_seed(old_seed, new_seed, count, extra)
    assert geometry(new_seed, verify_top=True) == physical
    _, _, rows, regions, groups, _ = physical
    census, array_cells, _, _, capacity, free = layout(
        new_seed,
        sizes,
        rows,
        regions,
        groups,
        obstructions,
        fixed,
        HEIGHT,
    )
    extra_sites = sum(sizes[master.decode()][0] // 280 for _, master, *_ in extra)
    baseline = read(Path("records/tri_oracle_booth_chip_geometry.json"))
    assert census.total() == count + len(leaves) and census["FIXED"] == 631
    assert len(array_cells) == 20 and len(set(array_cells.values())) == 1
    assert capacity == baseline["row_sites_capacity"]
    assert free == baseline["row_sites_free_after_placement"] - extra_sites
    text = (NATIVE / "plan.tcl").read_text()
    for key, before, after in (
        ("netlist", old_net.resolve(), new_net.resolve()),
        ("seed", old_seed.resolve(), new_seed.resolve()),
        (
            "database",
            (NATIVE / "import/placed.db").resolve(),
            (RETRY / "import/placed.db").resolve(),
        ),
        ("components", count, count + len(leaves)),
    ):
        old = f"{key} {{{before}}}"
        assert text.count(old) == 1
        text = text.replace(old, f"{key} {{{after}}}")
    plan.write_text(text)
    result = dict(
        state="mapped_boundary_control_linked_into_full_chip_and_placed_on_legal_sites",
        logical_top=TOP,
        placement_leaves=census.total(),
        inserted_cells=[name.decode() for name, _, *_ in extra],
        added_row_sites=extra_sites,
        binary_vectors=4096,
        fixed_macros=census["FIXED"],
        free_row_sites=free,
        evidence_sha256={
            str(path): digest(path)
            for path in (
                INPUTS,
                old_net,
                old_seed,
                mapped,
                reference,
                new_net,
                new_seed,
                plan,
                TRIAL / "replay/lockstep.sv",
                *evidence,
            )
        },
    )
    (RETRY / "prepared.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    print(
        result["state"],
        result["placement_leaves"],
        "added_sites",
        extra_sites,
        flush=True,
    )


def verify():
    evidence = verify_fixture()
    receipt = RETRY / "prepared.json"
    result = read(receipt)
    assert result["binary_vectors"] == 4096 and result["fixed_macros"] == 631
    assert all(
        digest(Path(name)) == value for name, value in result["evidence_sha256"].items()
    )
    source = TRIAL / "before/source.v"
    expected = fixture_bytes()
    # Accept formatting differences from the original extraction while
    # requiring identical ports and the four exact equations.
    assert signature(source.read_bytes()) == signature(expected)
    assert EQUATIONS.findall(source.read_bytes()) == EQUATIONS.findall(expected)
    reference = source.read_bytes().replace(
        f"module {GLUE}(".encode(), b"module boundary_reference(", 1
    )
    assert (TRIAL / "replay/reference.v").read_bytes() == reference
    assert (TRIAL / "replay/lockstep.sv").read_bytes() == BENCH.read_bytes()

    parsed = RETRY / "parse/console.log"
    native = RETRY / "parse/status.json"
    status = read(native)
    assert status["exit_status"] == 0 and status["stop_reason"] is None
    log = parsed.read_text()
    assert str((RETRY / "linked.v").resolve()) in log
    assert "TRI_ORACLE_LINKED_CHIP_NETLIST_READ_PASS" in log.splitlines()
    assert re.search(r"Message Summary: \d+ warning\(s\), 0 error\(s\)", log)
    assert not re.search(r"(?m)^\*\*?ERROR:", log)
    result["state"] = "booth_chip_mapped_boundary_control_passed_innovus_netlist_read"
    result["scope"] = (
        "Genus mapped the four wrapper equations. Xcelium exhaustively checked "
        "binary inputs. The seed adds five standard cells at legal sites. "
        "Innovus read the entire linked netlist. Native placement reload and "
        "timing qualification are pending."
    )
    result["full_linked_read_wall_seconds"] = round(status["wall_seconds"], 3)
    for path in (
        receipt,
        parsed,
        native,
        SYNTHESIS,
        BENCH,
        TRIAL / "replay/reference.v",
        Path(__file__).resolve().relative_to(ROOT),
        *evidence,
    ):
        result["evidence_sha256"][str(path)] = digest(path)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("extract", "prepare", "verify"))
    {"extract": extract, "prepare": prepare, "verify": verify}[
        parser.parse_args().mode
    ]()
