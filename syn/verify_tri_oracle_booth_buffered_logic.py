"""Verify settled four-state logic across the two cold-exported Booth netlists."""

from collections import defaultdict
from contextlib import ExitStack
import json
import mmap
from pathlib import Path
import re

from audit_tri_oracle_booth_pin_loads import MINIMUM_SINKS, pin_models, scan_module
from stage_tri_oracle_booth_pin_load_candidate import ROOT, WORK, prepare_edits, prove_module, sha, spans

ORIGINAL = Path("records/tri_oracle_corrected_booth_placement_roundtrip.json")
BUFFERED = Path("records/tri_oracle_corrected_booth_buffered_placement_roundtrip.json")
ORIGINAL_MODELS = Path("records/tri_oracle_corrected_booth_physical_models.json")
REPAIR = Path("records/tri_oracle_corrected_booth_pin_load_repair.json")
TESTBENCH = Path("verilog/tri_oracle_booth_buffer_truth_tb.sv")
STANDARD_MODEL = Path(".cache/physical/library/tcbn28hpcplusbwp12t40p140.v")


def verify():
    evidence = {}

    def pin(path, expected=None):
        checksum = sha(path)
        assert expected is None or checksum == expected, path
        evidence[path.relative_to(ROOT).as_posix() if path.is_absolute() else str(path)] = checksum
        return path

    def record(path, expected=None):
        return json.loads(pin(path, expected).read_text())

    original = record(ORIGINAL)
    repaired = record(BUFFERED)
    repair = record(REPAIR, repaired["evidence_sha256"][str(REPAIR)])
    plan_file = WORK / "buffer_plan.json"
    plan = record(plan_file, repair["evidence_sha256"][str(plan_file.relative_to(ROOT))])
    rewires, additions, buffers = prepare_edits(plan)
    counts = defaultdict(set)
    for net in plan["nets"]:
        driver = net["driver"]
        driver_name = driver["name"].rsplit("/", 1)[-1]
        counts[net["module"]].add((net["net"], driver_name, driver["master"], driver["pin"]))
    assert set(counts) == additions.keys() == rewires.keys()

    before_stage, after_stage = (Path(receipt["database"]).parents[1] for receipt in (original, repaired))
    before, after = (stage / "cold/cold.v" for stage in (before_stage, after_stage))
    original_hash = original["evidence_sha256"][str(before)]
    repaired_hash = repaired["evidence_sha256"][str(after)]
    assert original_hash == repair["baseline_netlist_sha256"]
    replica = before_stage / "unseeded_packet_layer"
    replay = record(replica / "native/prepared_native.json")
    assert replay["cold_netlist_sha256"] == original_hash
    bundle = replica / "bundle.sv"
    inputs = pin(bundle, replay["evidence_sha256"][str(bundle)]).read_text()
    assert all(f'`include "{ROOT / path}"' in inputs for path in (before, STANDARD_MODEL))
    packet = record(before_stage / "packet_replay/prepared.json")
    pin(STANDARD_MODEL, packet["evidence_sha256"][str(STANDARD_MODEL)])

    models = record(ORIGINAL_MODELS)
    database = Path(original["database"])
    standard_libraries = [name for name in models["liberty_models_by_corner"]["slow"]
                          if name.startswith("tcbn28hpcplusbwp12t40p140")]
    (standard_name,) = standard_libraries
    (standard_library,) = (database / "libs").rglob(standard_name)
    liberty = pin_models(pin(standard_library, models["evidence_sha256"][str(standard_library)]))

    with ExitStack() as stack:
        maps = []
        for path, digest in ((before, original_hash), (after, repaired_hash)):
            source = stack.enter_context(pin(path, digest).open("rb"))
            maps.append(stack.enter_context(mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_READ)))
        old, new = maps
        original_modules, new_modules = spans(old), spans(new)
        assert original_modules.keys() == new_modules.keys()
        for name, (start, end) in original_modules.items():
            new_start, new_end = new_modules[name]
            baseline_body, repaired_body = old[start:end], new[new_start:new_end]
            if name not in additions:
                assert baseline_body == repaired_body, name
                continue
            prove_module(baseline_body, repaired_body, rewires[name], additions[name])
            _, _, loads = scan_module(baseline_body, liberty, MINIMUM_SINKS)
            observed = {(load["net"], load["driver_instance"], load["master"], load["driver_pin"])
                        for load in loads}
            assert counts[name] <= observed, name

    affected_drivers = {(net["driver"]["master"], net["driver"]["pin"]) for net in plan["nets"]}
    test_source = pin(TESTBENCH).read_text()
    tested_drivers = set(re.findall(
        r"(?m)^\s*(\w+) driver\d+ .*\.(\w+)\(direct\[\d+\]\)\);$", test_source))
    assert affected_drivers == tested_drivers
    assert {node["master"] for node in buffers} == {"BUFFD8BWP12T40P140"}
    assert len(buffers) == repair["added_buffers"]
    reads = sum(len(pins) for module in rewires.values() for pins in module.values())
    assert reads == repair["rewired_sink_pins"]
    truth_log = pin(after_stage / "buffer_truth/xrun.log").read_text()
    assert all(str(ROOT / path) in truth_log for path in (TESTBENCH, STANDARD_MODEL))
    assert not re.search(r"\*[EF],", truth_log)
    (driver_count, combinations, depth) = map(int, re.findall(
        r"(?m)^BOOTH_BUFFER_TRUTH_PASS (\d+) (\d+) (\d+)$", truth_log)[0])
    assert driver_count == len(affected_drivers) and combinations == 16 * driver_count and depth == 2
    assert truth_log.count("Simulation complete via $finish(1)") == 1
    pin(Path(__file__).resolve())
    return {
        "state": "booth_buffer_repair_settled_four_state_logic_verified",
        "scope": "Cold-exported structural comparison and settled four-state standard-cell behavior with zero-delay simulation settings.",
        "original_cold_netlist_sha256": original_hash,
        "repaired_cold_netlist_sha256": repaired_hash,
        "unchanged_modules": len(original_modules) - len(additions),
        "changed_modules": len(additions),
        "rewired_input_pins": reads,
        "added_buffers": len(buffers),
        "independently_checked_single_driver_nets": sum(map(len, counts.values())),
        "exhaustive_driver_input_combinations": combinations,
        "evidence_sha256": evidence,
    }


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    print(json.dumps(verify(), indent=2, sort_keys=True))
