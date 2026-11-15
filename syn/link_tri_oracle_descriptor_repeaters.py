"""Insert mapped repeaters on the added command and write-back branches."""

import argparse
import json
import mmap
from pathlib import Path
import re

from audit_tri_oracle_mapped_redundancy import ENDMODULE, MODULE, TOP
from link_tri_oracle_residual_grant_buffers import buffer_instance
from link_tri_oracle_writeback_control import copy_region, replace_once, sha


ROOT = Path(__file__).resolve().parents[1]
CONTROL_PINS = {
    "layer_command_valid[0]": "command_valid",
    "layer_command_ready[0]": "command_ready",
    "layer_done_valid[0]": "done_valid",
    "layer_done_ready[0]": "done_ready",
}
SCALES = [f"layer_command_payload[{bit}]" for bit in range(959, 949, -1)]


def wire_repeaters(source, repeaters):
    signals = {item["signal"]: item for item in repeaters}
    if len(repeaters) != 14 or signals.keys() != CONTROL_PINS.keys() | set(SCALES):
        raise ValueError("The plan must cover all four control and ten scale signals")
    instances, wires = [], {}
    for signal, item in signals.items():
        name = item["name"]
        cell = item["site"]["master"]
        if not re.fullmatch(r"descriptor_repeater_\d+", name):
            raise ValueError(f"Unexpected repeater instance name {name}")
        if not re.fullmatch(r"BUFFD(?:1|2|4|6|8|12|16|20|24)BWP12T40P140", cell):
            raise ValueError(f"Unexpected repeater master {cell}")
        wires[signal] = name + "_output"
        if name in source:
            raise ValueError(f"Repeater already present: {name}")
        instances.append(buffer_instance(cell, name, signal, wires[signal]))
    if len(set(wires.values())) != len(wires):
        raise ValueError("Repeater instance names must be unique")
    controller, = re.findall(
        r"(?ms)^[ \t]+tri_oracle_residual_command_request residual_command_request\s*\(.*?\);",
        source,
    )
    connected = controller
    for signal, pin in CONTROL_PINS.items():
        connected = replace_once(connected, f".{pin}({signal})", f".{pin}({wires[signal]})")
    source = replace_once(source, controller, connected)
    scaled = "{" + ", ".join(wires[signal] for signal in SCALES) + "}"
    source = replace_once(
        source, ".frame_down_shifts(layer_command_payload[959:950])", f".frame_down_shifts({scaled})"
    )
    declaration = "   input residual_lease;\n"
    source = replace_once(source, declaration, declaration + f"   wire {', '.join(wires.values())};\n")
    return replace_once(source, "endmodule", "".join(instances) + "endmodule")


def link(candidate, plan, output):
    seed = ROOT / "records/tri_oracle_descriptor_writeback_placement_seed.json"
    expected = json.loads(seed.read_bytes())
    plan_identity = sha(plan)
    settings = json.loads(plan.read_bytes())
    identity = expected["candidate_sha256"]
    if sha(candidate) != identity or settings["candidate_sha256"] != identity:
        raise ValueError("The repeater plan does not match the mapped descriptor candidate")
    if expected["seed_sha256"] != settings["seed_sha256"] or settings["infeasible"]:
        raise ValueError("The repeater plan lacks a legal site for every selected branch")
    if any(sha(ROOT / name) != digest for name, digest in settings["evidence_sha256"].items()):
        raise ValueError("Repeater plan evidence changed")
    with candidate.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as source:
        top, = (row for row in MODULE.finditer(source) if row[1].decode() == TOP)
        end = ENDMODULE.search(source, top.end()).end()
        updated = wire_repeaters(source[top.start():end].decode(), settings["repeaters"])
        with output.open("xb") as destination:
            copy_region(source, destination, 0, top.start())
            destination.write(updated.encode())
            copy_region(source, destination, end, len(source))
    if sha(candidate) != identity or sha(plan) != plan_identity:
        raise ValueError("The candidate or repeater plan changed during linking")
    return dict(parent_candidate_sha256=identity, candidate_sha256=sha(output),
                plan_sha256=plan_identity, repeaters_added=len(settings["repeaters"]), modified_module=TOP)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("plan", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(link(args.candidate, args.plan, args.output), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
