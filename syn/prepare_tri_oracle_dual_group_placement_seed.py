"""Carry verified geometry and unchanged cell poses into the widened netlist."""

import argparse
from collections import Counter
from decimal import Decimal
import json
import mmap
import os
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory

from audit_tri_oracle_placed_chip_boundary import digest
from link_tri_oracle_indexed_whole_chip import LOADER, TOP, module_at, signature, spans
from verify_tri_oracle_joined_placed_constraints import parse_sdc
from verify_tri_oracle_pad_cold_reload import boundary_sections, components
from verify_tri_oracle_seed_components import INSTANCE, expanded_instances


RECORDS = Path("records")
NATIVE = RECORDS / "tri_oracle_full_native_token_tree_placement.json"
WIDENED = RECORDS / "tri_oracle_dual_group_whole_chip_link.json"
VIEWS = ("setup_slow", "setup_typ", "hold_fast")
RAW_PARENT = "layer/layer/feedforward/compute/compute/tensor/packed_loader/"
RAW_CHILD = RAW_PARENT + "raw_loader/"
PIN = re.compile(r"^- (\S+) \+ NET \S+ \+ DIRECTION (INPUT|OUTPUT) \+ USE SIGNAL$")
POSITION = re.compile(r"^  \+ PLACED \( (\d+) (\d+) \) ([NESW]) ;$")


def read(path):
    return json.loads(path.read_text())


def top_ports(netlist):
    ports = {}
    for name, (direction, bus) in signature(netlist).items():
        if bus:
            high, low = map(int, bus[1:-1].split(b":"))
            for bit in range(low, high + 1):
                ports[f"{name}[{bit}]"] = direction.decode().upper()
        else:
            ports[name] = direction.decode().upper()
    return ports


def check_boundary(parent, views, ports):
    sections = boundary_sections(parent)
    count, rows = sections["PINS"]
    pins = {}
    assert len(rows) == 3 * count
    for index in range(0, len(rows), 3):
        pin = PIN.fullmatch(rows[index].rstrip("\n"))
        position = POSITION.fullmatch(rows[index + 2].rstrip("\n"))
        assert pin and position and rows[index + 1].startswith(("  + LAYER M4 ", "  + LAYER M5 "))
        name, direction = pin.groups()
        x, y = map(int, position.groups()[:2])
        assert name not in pins and 0 <= min(x, y) <= max(x, y) <= 7200000
        assert any(value in (0, 7200000) for value in (x, y))
        pins[name] = direction
    assert pins == ports and len(pins) == 7945
    expected = set()
    for port, direction in ports.items():
        if port in ("clk", "rst_n"):
            continue
        commands = ("set_input_delay", "set_input_transition") if direction == "INPUT" else (
            "set_output_delay", "set_load"
        )
        expected.update((command, port, edge) for command in commands for edge in ("min", "max"))
    counts = {}
    for label, path in views.items():
        text = path.read_text().replace("-name core ", "-name core_clock ")
        metadata, constraints, protected = parse_sdc(
            text.replace("[get_clocks {core}]", "[get_clocks {core_clock}]")
        )
        assert metadata["current_design"] == TOP
        assert metadata["create_clock"] == ("clk", Decimal("1.72414"), (Decimal(0), Decimal("0.86207")))
        assert metadata["set_false_path"] == "rst_n"
        assert not protected and constraints.keys() == expected
        counts[label] = len(constraints)
    return sections, counts


def reachable(source, index, master):
    pending = [master]
    seen = set()
    while pending:
        master = pending.pop()
        if master not in seen:
            seen.add(master)
            for child, _ in INSTANCE.findall(module_at(source, index, master)):
                name = child.decode()
                if name in index:
                    pending.append(name)
    return seen


def verify_handoff(before, after):
    with (
        before.open("rb") as old, after.open("rb") as new,
        mmap.mmap(old.fileno(), 0, access=mmap.ACCESS_READ) as parent,
        mmap.mmap(new.fileno(), 0, access=mmap.ACCESS_READ) as candidate,
    ):
        old_index, new_index = spans(parent), spans(candidate)
        old_top = module_at(parent, old_index, TOP)
        new_top = module_at(candidate, new_index, TOP)
        assert signature(old_top) == signature(new_top)
        raw = reachable(parent, old_index, LOADER)
        assert raw == reachable(candidate, new_index, LOADER)
        for name in raw:
            assert module_at(parent, old_index, name) == module_at(candidate, new_index, name), name
        return top_ports(new_top)


def def_name(name):
    assert not re.search(rb"\s|\\", name), name
    return name.replace(b"[", rb"\[").replace(b"]", rb"\]")


def old_rows(parent):
    for name, (master, status, x, y, orient, halo) in components(parent):
        canonical = name.replace(b"\\", b"")
        prefix = RAW_PARENT.encode()
        if canonical.startswith(prefix):
            canonical = RAW_CHILD.encode() + canonical[len(prefix):]
        position = [status, str(x), str(y), orient, *map(str, halo)]
        yield canonical + b"\t" + master.encode() + b"\t" + "\t".join(position).encode()


def sorted_rows(directory, label, rows, cpus):
    raw, result = (directory / f"{label}{suffix}" for suffix in (".tsv", ".sorted"))
    count = 0
    with raw.open("xb") as stream:
        for row in rows:
            stream.write(row + b"\n")
            count += 1
    with result.open("xb") as stream:
        subprocess.run(["sort", f"--parallel={cpus}", "-S", "256M", "-T", str(directory), str(raw)],
                       env=os.environ | {"LC_ALL": "C"}, check=True, stdout=stream)
    raw.unlink()
    return result, count


def ordered(stream):
    previous = b""
    for line in stream:
        name, *fields = line.rstrip(b"\n").split(b"\t")
        assert name > previous, name
        previous = name
        yield name, fields


def copy_header(parent, stream):
    with parent.open("rb") as source:
        for line in source:
            if line.startswith(b"COMPONENTS "):
                assert line == b"COMPONENTS 3745374 ;\n"
                return
            stream.write(line)
    raise ValueError("Missing verified layout geometry")


def write_seed(parent, sections, old, new, total, output):
    positions = Counter()
    new_masters = Counter()
    removed_masters = Counter()
    with old.open("rb") as before, new.open("rb") as after, output.open("xb") as stream:
        copy_header(parent, stream)
        stream.write(f"COMPONENTS {total} ;\n".encode())
        prior = ordered(before)
        found = next(prior, None)

        def removed(row):
            _, (master, status, *_rest) = row
            assert status == b"PLACED"
            removed_masters[master.decode()] += 1

        for name, (master,) in ordered(after):
            while found and found[0] < name:
                removed(found)
                found = next(prior, None)
            label = b"- " + def_name(name) + b" " + master
            if found and found[0] == name and found[1][0] == master:
                _, status, x, y, orient, *halo = found[1]
                stream.write(label + b" + " + status + b" ( " + x + b" " + y + b" ) " + orient)
                if status == b"FIXED":
                    assert len(halo) == 4
                    stream.write(b"\n  + HALO " + b" ".join(halo) + b"\n")
                stream.write(b" ;\n")
                positions[status.decode()] += 1
                if name.startswith(RAW_CHILD.encode()):
                    positions["retargeted_raw_coordinates"] += 1
                found = next(prior, None)
            else:
                stream.write(label + b" + UNPLACED ;\n")
                positions["UNPLACED"] += 1
                new_masters[master.decode()] += 1
        if found:
            removed(found)
        for row in prior:
            removed(row)
        stream.write(b"END COMPONENTS\n\n")
        count, pins = sections["PINS"]
        stream.write(f"PINS {count} ;\n".encode())
        stream.writelines(row.encode() for row in pins)
        stream.write(b"END PINS\n\n")
        count, blockages = sections["BLOCKAGES"]
        stream.write(f"BLOCKAGES {count} ;\n".encode())
        for x0, y0, x1, y1 in blockages:
            stream.write(f"   - PLACEMENT RECT ( {x0} {y0} ) ( {x1} {y1} ) ;\n".encode())
        stream.write(b"END BLOCKAGES\n\nEND DESIGN\n")
    assert sum(positions[key] for key in ("FIXED", "PLACED", "UNPLACED")) == total
    assert positions["FIXED"] == 631 and positions["retargeted_raw_coordinates"] > 0
    return positions, new_masters, removed_masters


def prepare(reload, candidate, output):
    old = read(NATIVE)
    widened = read(WIDENED)
    before = reload / "legality/cold.v"
    placement = reload / "legality/cold.def"
    views = {name: reload / f"structure/{name}.sdc" for name in VIEWS}
    evidence = {str(path): digest(path) for path in (before, placement, *views.values())}
    assert all(old["evidence_sha256"][name] == checksum for name, checksum in evidence.items())
    assert digest(candidate) == widened["candidate_sha256"]
    evidence[str(candidate)] = widened["candidate_sha256"]
    ports = verify_handoff(before, candidate)
    sections, delay_counts = check_boundary(placement, views, ports)
    assert delay_counts == old["constraint_entries_by_view"]
    print("WIDENED_PLACEMENT_BOUNDARY_VERIFIED", len(ports), flush=True)
    assert shutil.disk_usage(output.parent).free >= 12 * 1024**3
    output.mkdir()
    seed = output / "seed.def"
    with TemporaryDirectory(dir=output, prefix="inventory_") as scratch:
        cpus = min(4, len(os.sched_getaffinity(0)))
        old_rows_path, old_count = sorted_rows(Path(scratch), "old", old_rows(placement), cpus)
        rows = (name + b"\t" + master for name, master in expanded_instances(candidate))
        new_rows_path, new_count = sorted_rows(Path(scratch), "new", rows, cpus)
        positions, added, removed = write_seed(placement, sections, old_rows_path, new_rows_path, new_count, seed)
        assert old_count == 3745374 and old_count + sum(added.values()) - sum(removed.values()) == new_count
    assert boundary_sections(seed) == sections
    assert all(digest(Path(path)) == checksum for path, checksum in evidence.items())
    return {
        "state": "widened_candidate_placement_seed_prepared",
        "candidate_sha256": widened["candidate_sha256"],
        "source_def_sha256": evidence[str(placement)],
        "seed_def_sha256": digest(seed),
        "die_dimensions_mm": [3.6, 3.6],
        "boundary_pins": len(ports),
        "pin_constraints_by_view": delay_counts,
        "positions": positions,
        "new_or_changed_component_masters": added,
        "removed_or_replaced_component_masters": removed,
        "scope": "Offline geometry and timing-constraint compatibility check. New and replaced components "
                 "have no assigned coordinates. Native import, legalization and timing remain separate.",
        "evidence_sha256": evidence,
    }


def main():
    assert __debug__ and Path("/.dockerenv").is_file()
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("reload", "candidate", "output"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    result = prepare(args.reload, args.candidate, args.output)
    with (args.output / "receipt.json").open("x") as receipt:
        json.dump(result, receipt, indent=2, sort_keys=True)
        receipt.write("\n")
    print(result["state"], dict(result["positions"]), flush=True)


if __name__ == "__main__":
    main()
