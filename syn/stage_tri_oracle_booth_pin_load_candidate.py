"""Materialize the verified load repair as a separate mapped and placed candidate."""
from argparse import ArgumentParser
from collections import defaultdict
from hashlib import file_digest
from pathlib import Path
import json
import mmap
import re
import shutil

from audit_tri_oracle_booth_pin_loads import CELL, MODELS, PLACEMENT, ROOT, normalize_module, pin_fields, read_module, spans
from build_tri_oracle_booth_chip_seed import def_name
from audit_tri_oracle_physical_io_budget import macro_boxes
from verify_tri_oracle_booth_chip_geometry import geometry, layout as check_layout
from verify_tri_oracle_pad_cold_reload import components
from verify_tri_oracle_serialized_placement_transfer import dimensions


from plan_tri_oracle_booth_pin_load_repair import WORK
PIN = re.compile(rb"\.(\\\S+|[\w$]+)\s*\(([^()]*)\)")
COMPONENTS = re.compile(rb"COMPONENTS (\d+) ;\n")


def sha(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def read(path):
    return json.loads(path.read_text())


def prepare_edits(plan):
    rewires = defaultdict(lambda: defaultdict(dict))
    additions = defaultdict(dict)
    buffers = []
    for net in plan["nets"]:
        module = net["module"]
        parent = net["driver"]["name"].rsplit("/", 1)[0] + "/"
        old = net["net"]
        assert re.fullmatch(r"\w+", old), old
        nodes = net["buffers"]
        roots = [node for node in nodes if node["name"].endswith("_root")]
        assert len(roots) == int(net["added_root"])
        upstream = roots[0]["name"].removeprefix(parent) + "_wire" if roots else old
        for node in nodes:
            assert node["name"].startswith(parent)
            local = node["name"].removeprefix(parent)
            assert re.fullmatch(r"tri_load_repair_\d+_(?:leaf\d+|root)", local)
            assert local not in additions[module]
            branch = local + "_wire"
            root_node = node in roots
            additions[module][local] = (node["master"], old if root_node else upstream, branch)
            buffers.append(node)
            if root_node:
                expected = {(leaf["name"], "I") for leaf in nodes if leaf not in roots}
                assert set(map(tuple, node["loads"])) == expected
            else:
                for sink, pin in node["loads"]:
                    assert sink.startswith(parent)
                    cell = sink.removeprefix(parent)
                    assert "/" not in cell and pin not in rewires[module][cell]
                    rewires[module][cell][pin] = (old, branch)
    assert len({node["name"] for node in buffers}) == len(buffers)
    return rewires, additions, buffers


def rewrite_module(body, rewires, additions):
    seen = set()

    def fix_instance(match):
        name = match[2].decode().removeprefix("\\")
        if name not in rewires:
            return match[0]
        seen_pins = set()

        def fix_pin(pin_match):
            pin = pin_match[1].decode().removeprefix("\\")
            if pin not in rewires[name]:
                return pin_match[0]
            old, branch = rewires[name][pin]
            assert b"".join(pin_match[2].split()) == old.encode(), (name, pin)
            assert pin not in seen_pins
            seen_pins.add(pin)
            return b"." + pin_match[1] + b"(" + branch.encode() + b")"

        revised = PIN.sub(fix_pin, match[3])
        assert seen_pins == rewires[name].keys()
        seen.add(name)
        begin = match.start(3) - match.start()
        return match[0][:begin] + revised + match[0][begin + len(match[3]):]

    rewritten = CELL.sub(fix_instance, body)
    assert seen == rewires.keys()
    prefix, sep, suffix = rewritten.rpartition(b"endmodule")
    assert sep and not suffix.strip()
    new = []
    for instance, (master, upstream, branch) in additions.items():
        new.append(f"  wire {branch};\n  {master} {instance} (.I({upstream}), .Z({branch}));\n")
    return prefix + "".join(new).encode() + sep + suffix


def prove_module(before, after, rewires, additions):
    initial = read_module(normalize_module(before))
    result = read_module(normalize_module(after))
    assert initial[:2] == result[:2] and initial[4] == result[4]
    expected_wires = initial[2] | {branch: None for _, _, branch in additions.values()}
    assert expected_wires == result[2]
    assert result[3].keys() == initial[3].keys() | additions.keys()
    for name, (master, fields) in initial[3].items():
        observed_master, observed_fields = result[3][name]
        assert master == observed_master
        if name in rewires:
            canonical = {pin.removeprefix("\\"): " ".join(expr.split()) for pin, expr in pin_fields(fields).items()}
            for pin, (old, branch) in rewires[name].items():
                assert canonical[pin] == old
                canonical[pin] = branch
            measured = {pin.removeprefix("\\"): " ".join(expr.split()) for pin, expr in pin_fields(observed_fields).items()}
            assert canonical == measured
        else:
            assert fields == observed_fields
    for name, (master, upstream, branch) in additions.items():
        observed_master, fields = result[3][name]
        assert observed_master == master
        assert pin_fields(fields) == {"I": upstream, "Z": branch}


def stage_netlist(source, destination, rewires, additions):
    with source.open("rb") as handle, mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as raw, destination.open("xb") as out:
        cursor = 0
        parsed = spans(raw)
        assert set(additions) == set(rewires) and additions.keys() <= parsed.keys()
        for name, (start, stop) in parsed.items():
            out.write(raw[cursor:start])
            chunk = raw[start:stop]
            if name in additions:
                changed = rewrite_module(chunk, rewires[name], additions[name])
                prove_module(chunk, changed, rewires[name], additions[name])
                chunk = changed
            out.write(chunk)
            cursor = stop
        out.write(raw[cursor:])
    with source.open("rb") as first, destination.open("rb") as second, \
         mmap.mmap(first.fileno(), 0, access=mmap.ACCESS_READ) as a, mmap.mmap(second.fileno(), 0, access=mmap.ACCESS_READ) as b:
        old_set, new_set = spans(a), spans(b)
        assert old_set.keys() == new_set.keys()
        for name, (start, stop) in old_set.items():
            if name not in additions:
                begin, end = new_set[name]
                assert a[start:stop] == b[begin:end], name


def stage_layout(source, destination, buffers, old_count):
    with source.open("rb") as before, destination.open("xb") as after:
        count = end = False
        for line in before:
            if COMPONENTS.fullmatch(line):
                assert not count and int(COMPONENTS.fullmatch(line)[1]) == old_count
                after.write(b"COMPONENTS %d ;\n" % (old_count + len(buffers)))
                count = True
                continue
            if line == b"END COMPONENTS\n":
                assert count and not end
                for item in buffers:
                    after.write(b"- %s %s + PLACED ( %d %d ) %s ;\n" % (
                        def_name(item["name"].encode()), item["master"].encode(),
                        item["x"], item["y"], item["orientation"].encode()))
                end = True
            after.write(line)
        assert count and end


def main(output):
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    receipt = read(WORK / "repair_plan_receipt.json")
    assert receipt["state"] == "corrected_booth_overload_buffer_plan_pin_and_site_checks_passed"
    for name, digest_value in receipt["evidence_sha256"].items():
        assert sha(ROOT / name) == digest_value, name
    proof, models = read(PLACEMENT), read(MODELS)
    cold = (ROOT / proof["database"]).parents[1] / "cold"
    assert sha(cold / "cold.v") == receipt["cold_netlist_sha256"]
    plan = read(WORK / "buffer_plan.json")
    rewires, additions, buffers = prepare_edits(plan)
    changed = sum(len(pins) for by_cell in rewires.values() for pins in by_cell.values())
    assert changed == receipt["sinks"] and len(buffers) == receipt["buffers"]
    expected = proof["geometry"].copy()
    old_count = expected["standard_cells"] + expected["fixed_memory_macros"]
    expected["standard_cells"] += len(buffers)
    lefs = [ROOT / proof["database"] / "libs/lef" / name for name in models["physical_abstracts"]]
    assert shutil.disk_usage(WORK).free >= 12 * 1024**3
    assert output.resolve().is_relative_to(WORK.resolve())
    output.mkdir()
    try:
        v, layout = output / "buffered.v", output / "layout.def"
        stage_netlist(cold / "cold.v", v, rewires, additions)
        stage_layout(cold / "layout.def", layout, buffers, old_count)
        _, units, rows, regions, groups, blockages = geometry(layout, verify_top=True)
        sizes = dimensions(lefs, units)
        by_name = {item["name"].encode(): item for item in buffers}
        seen, fixed = set(), {}
        for name, pose in components(layout):
            if pose[1] == "FIXED":
                fixed[name] = pose
            canonical = name.replace(b"\\", b"")
            if canonical in by_name:
                item = by_name[canonical]
                assert canonical not in seen
                assert pose[:5] == (item["master"], "PLACED", item["x"], item["y"], item["orientation"])
                seen.add(canonical)
        assert seen == by_name.keys()
        _, halos = macro_boxes(fixed, sizes)
        height = sizes[buffers[0]["master"]][1]
        census, *_ = check_layout(layout, sizes, rows, regions, groups,
                                 blockages + list(halos.values()), fixed, height)
        assert census == {"PLACED": expected["standard_cells"], "FIXED": expected["fixed_memory_macros"]}
        facts = dict(state="booth_load_repair_candidate_staged_and_static_checks_passed",
                     baseline_netlist_sha256=receipt["cold_netlist_sha256"],
                     buffer_instances=len(buffers), rewired_sink_pins=changed,
                     unchanged_original_components=old_count, modified_logical_modules=len(additions),
                     maximum_planned_pin_limit_ratio=receipt["maximum_planned_pin_limit_ratio"],
                     evidence_sha256={str(path.relative_to(ROOT)): sha(path) for path in (
                         v, layout, WORK / "repair_plan_receipt.json", Path(__file__).resolve())})
        data = json.dumps(facts, indent=2, sort_keys=True) + "\n"
        (output / "receipt.json").write_text(data)
        print(data, end="")
    except Exception:
        shutil.rmtree(output)
        raise


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=WORK / "candidate")
    main(parser.parse_args().output)
