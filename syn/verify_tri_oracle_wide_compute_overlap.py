"""Bind the nine-credit replay and same-core load exclusion to the widened seed."""

from collections import Counter
from contextlib import ExitStack
from itertools import product
import json
from pathlib import Path
import re

from build_tri_oracle_booth_chip_seed import hierarchy
from link_tri_oracle_indexed_whole_chip import pins, signature
from verify_tri_oracle_booth_chip_link import named_bindings
from verify_tri_oracle_corrected_booth_roundtrip import ROOT, TOP, digest, read
from verify_tri_oracle_wide_request_trial import FIXTURES, MATRIX, TERMINAL, TOP as REPLAY, TRAFFIC
from verify_tri_oracle_wide_seed_resources import catalog, compute_paths, module_text


RESOURCE = Path("records/tri_oracle_wide_seed_paper_resources.json")
LINK = Path("records/tri_oracle_wide_request_trial.json")
BUDGET = Path("records/tri_oracle_wide_split_receive.json")
LIBRARY = Path(".cache/physical/library/tcbn28hpcplusbwp12t40p140ssg0p9v125c.lib")
ARRAY_MEMORY = "TS5N28HPCPSVTA32X128M2FW"
AND3 = "AN3D1BWP12T40P140"
NAND2 = "CKND2D1BWP12T40P140"


def weight_banks(module):
    banks = {}
    expression = rb"(?m)^\s*" + ARRAY_MEMORY.encode() + rb"\s+\\weights\[(\d+)\]\s*\(([^;]+)\);"
    for number, fields in re.findall(expression, module):
        bank = int(number)
        assert bank not in banks
        banks[bank] = named_bindings(fields)
    assert set(banks) == set(range(16))
    for bank, wiring in banks.items():
        assert set(wiring) == {"A", "CLK", "CEB", "WEB", "D", "BWEB", "Q"}
        assert wiring["CLK"] == b"clk" and wiring["A"] == b"weight_address"
        assert wiring["WEB"] == b"weight_web[%d]" % bank and wiring["CEB"] == b"weight_ceb[%d]" % bank
    return len(banks)


def handshake(module):
    ports = signature(module)
    assert ports["load_valid"] == ports["cmd_valid"] == (b"input", b"")
    assert ports["load_ready"] == ports["cmd_ready"] == (b"output", b"")
    ready = pins(module, AND3, "g145238")
    blocked = pins(module, NAND2, "g146562")
    issue = pins(module, AND3, "g143678")
    assert ready == {"A1": b"array_ready", "A2": blocked["ZN"], "A3": b"compute_enabled", "Z": b"cmd_ready"}
    assert blocked == {"A1": b"load_ready", "A2": b"load_valid", "ZN": ready["A2"]}
    assert issue == {"A1": b"cmd_ready", "A2": b"cmd_valid", "A3": issue["A3"], "Z": b"accept_command"}
    assert module.count(b".Z(cmd_ready)") == module.count(b".Z(accept_command)") == 1
    # Use free values for every input to these gates, including the opaque
    # compute-enable and reset-guard signals. No controller state assumptions are required.
    joint = loads = projections = 0
    for load_ready, load_valid, array_ready, enabled, command, reset_guard in product((False, True), repeat=6):
        load = load_ready and load_valid
        compute = array_ready and not load and enabled and command and reset_guard
        loads += load
        projections += compute
        joint += load and compute
    assert loads == 16 and projections == 3 and joint == 0
    return {"checked_input_assignments": 64, "accepted_load_assignments": loads,
            "accepted_compute_assignments": projections, "simultaneous_assignments": joint}


def function(library, master, pin):
    cell = re.search(rf"(?ms)^cell \({master}\)\s*\{{(.*?)(?=^cell \()", library)[1]
    section = re.search(rf"(?ms)^  pin\({pin}\)\s*\{{(.*?)(?=^  \}})", cell)[1]
    return re.search(r'(?m)^\s*function\s*:\s*"([^"]+)"', section)[1]


def verify():
    resources, link, budget = map(read, (RESOURCE, LINK, BUDGET))
    evidence = {str(path): digest(path) for path in (RESOURCE, LINK, BUDGET, LIBRARY)}

    def pin(path, expected=None):
        value = digest(path)
        assert expected is None or expected == value, path
        evidence[str(path.relative_to(ROOT) if path.is_absolute() else path)] = value
        return path

    candidate, = (Path(path) for path in resources["evidence_sha256"] if path.endswith("/placement_seed/candidate.v"))
    pin(candidate, resources["candidate_sha256"])
    text = LIBRARY.read_text()
    assert function(text, AND3, "Z") == "((A1 A2) A3)"
    assert function(text, NAND2, "ZN") == "(!(A1 A2))"
    (model, checksum), = ((Path(path), value) for path, value in resources["evidence_sha256"].items()
                          if path.endswith("/ts5n28hpcpsvta32x128m2fw_130a_tt1v25c.v"))
    header = re.search(rf"(?ms)^module\s+{ARRAY_MEMORY}\s*\((.*?)\);", pin(model, checksum).read_text())[1]
    assert set(re.findall(r"\w+", header)) == {"A", "CLK", "CEB", "WEB", "D", "BWEB", "Q"}

    instances, macros, outcomes = set(), Counter(), None
    with ExitStack() as stack:
        modules = catalog(stack, (candidate,))
        children, _ = hierarchy(modules)
        for path, _ in compute_paths(modules):
            master = TOP.encode()
            for instance in path.split(b"/")[:-1]:
                master = children(master)[instance]
            assert master not in instances, master
            instances.add(master)
            module = module_text(modules, master.decode())
            macros[weight_banks(module)] += 1
            result = handshake(module)
            assert outcomes is None or outcomes == result
            outcomes = result
    assert macros == {16: 20}

    native_path, = (Path(path) for path in link["evidence_sha256"] if path.endswith("/wide_request_trial/xrun.log"))
    baseline = pin(native_path, link["evidence_sha256"][str(native_path)]).read_text()
    stage = native_path.parent / "placed_receiver_nine_credits"
    native = pin(stage / "xrun.log").read_text()
    assert pin(stage / "exit_status").read_text().strip() == "0"
    bundle = native_path.with_name("bundle.sv")
    for path in (bundle, *(Path(name) for name in re.findall(r'(?m)^\x60include "([^"]+)"$', bundle.read_text()))):
        path = path.resolve()
        pin(path, link["evidence_sha256"][str(path.relative_to(ROOT))])
    for fixture in FIXTURES:
        resolved = (native_path.parent / fixture).resolve(strict=True)
        assert (stage / fixture).resolve(strict=True) == resolved
        pin(resolved, link["evidence_sha256"][str(resolved.relative_to(ROOT))])
    cycles = []
    for credits, log in ((8, baseline), (9, native)):
        assert log.count(TERMINAL) == 1 and not re.search(r"\*(?:E|F|SE),", log)
        assert f"\t{bundle.resolve()}\n" in log and f"\t-top {REPLAY}\n" in log and "\t+FULL_MATRIX\n" in log
        assert f"TRI_ORACLE_TRAINED_WINDOW={credits}" in log and "TRI_ORACLE_TRAINED_RETURN=7" in log
        assert f"TRAINED_WINDOW_CHECK credits={credits} delay=7 stalls=0,0" in log
        assert "NATIVE_MEMORY_IO_PASS acks=16 faults=2" in log
        cycles.append(int(re.search(r"(?m)^DUAL_GROUP_MATRIX_WRITES writes=90112 cycles=(\d+)$", log)[1]))
    assert MATRIX.findall(native) == MATRIX.findall(baseline)
    assert TRAFFIC.findall(native) == TRAFFIC.findall(baseline)
    assert "STAGED_INDEXED_DOWN_MATRIX_PASS cases=78 exact_bytes=11534336 " in native
    assert cycles[0] == link["wide_request_cycles"]

    pin(Path(__file__).resolve())
    needed = budget["original_receiver_nine_credit_bounds_by_delay_then_disjoint_transfers"]["7"]["2"]
    return {
        "state": "wide_candidate_nine_credit_replay_and_core_load_exclusion_verified",
        "candidate_sha256": resources["candidate_sha256"],
        "mapped_cores_checked": len(instances), "weight_macros_per_core": 16,
        "independent_weight_addresses_per_core": 1, "mapped_handshake_truth_table": outcomes,
        "trained_tiles": 78, "exact_weight_bytes": 11534336, "modeled_credit_return_cycles": 7,
        "fixture_cycles_by_initial_credits": {"8": cycles[0], "9": cycles[1]},
        "required_overlap_cycles_under_archived_model": needed["minimum_projection_overlap_cycles_if_archived_issue_count_holds"],
        "scope": "The nine-credit wide-link fixture uses the placed receiver and archived modeled external memory. "
                 "The gate check proves local acceptance exclusion and counts the common weight address. "
                 "Already-issued operations can remain in flight during a load. Scheduling across cores and "
                 "whole-chip latency still require verification.",
        "evidence_sha256": evidence,
    }


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").is_file()
    print(json.dumps(verify(), indent=2, sort_keys=True))
