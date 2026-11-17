"""Verify the raw packed weight path in a cold-exported Tri-Oracle netlist."""

import argparse
import json
import mmap
from pathlib import Path
import re

from audit_tri_oracle_mapped_redundancy import ENDMODULE, MODULE, TOP, hierarchy
from audit_tri_oracle_placed_chip_boundary import digest


LOADER = "tri_oracle_parallel_weight_loader_parallel_chip"
STAGE = "tri_oracle_packed_write_stage_mapped"
PIN = re.compile(rb"\.([\\\w\[\]]+)\s*\(([^()]*)\)")


def loader_paths(graph):
    pending = [(TOP, TOP, (TOP,))]
    while pending:
        path, master, parents = pending.pop()
        for name, child in graph[master].items():
            instance = name.removeprefix("\\")
            child_path = f"{path}.{instance}"
            if child == LOADER:
                yield child_path, master
            if child in parents:
                raise ValueError(f"Recursive hierarchy at {child_path}")
            pending.append((child_path, child, (*parents, child)))


def module_body(source, master):
    definition, = (match for match in MODULE.finditer(source) if match[1].decode() == master)
    end = ENDMODULE.search(source, definition.end())
    if end is None:
        raise ValueError(f"Unterminated module {master}")
    return source[definition.end():end.start()]


def named_instance(body, master, instance):
    prefix = re.escape(master.encode()) + rb"\s+" + re.escape(instance.encode())
    match, = re.finditer(rb"(?m)^[ \t]*(" + prefix + rb")\s*\(([^;]*)\);", body)
    return match


def pins(body, master, instance):
    fields = named_instance(body, master, instance)[2]
    pairs = PIN.findall(fields)
    result = {name.decode().lstrip("\\"): b"".join(value.split()) for name, value in pairs}
    if len(result) != len(pairs) or PIN.sub(b"", fields).strip(b" \r\n\t,"):
        raise ValueError(f"Invalid named connections on {instance}")
    return result


def verify_boundary(parent_body, stage_body, loader, stage, fabric):
    def expect(actual, expected, label):
        if actual != expected:
            raise ValueError(f"{label} expected {expected!r}, found {actual!r}")

    def expect_connection(left, left_pin, right, right_pin):
        expect(left[left_pin], right[right_pin], left_pin)

    response_pins = {name for name in loader if name.startswith("rsp_")}
    expect(response_pins, {"rsp_valid", "rsp_last", "rsp_error", "rsp_ready"},
           "loader response pins")
    for signal in ("valid", "last", "error", "ready"):
        expect(loader[f"rsp_{signal}"], f"{{aux_rsp_{signal},wide_rsp_{signal}}}".encode(),
               f"response {signal} lane order")
    expect_connection(loader, "load_valid", stage, "load_valid")
    for direction in ("valid", "error", "ready"):
        expect_connection(loader, f"done_{direction}", stage, f"loader_done_{direction}")
    expect_connection(stage, "write_valid", fabric, "wide_load_valid")

    lanes = []
    for lane, response in enumerate(("wide_rsp_data", "aux_rsp_data")):
        expect(len(re.findall(rb"(?m)^\s*input \[511:0\] " + response.encode() + rb";", parent_body)),
               1, f"512-bit parent port {response}")
        for direction in ("load", "write"):
            port = re.escape(f"\\{direction}_payload[{lane}]".encode())
            declaration = b"input" if direction == "load" else b"output"
            expect(len(re.findall(rb"(?m)^\s*" + declaration + rb" \[511:0\] " + port + rb" ;",
                                  stage_body)), 1, f"512-bit {direction} payload lane {lane}")
        expect(stage[f"load_payload[{lane}]"], response.encode(), f"raw payload lane {lane}")
        for field in ("core", "addr", "row_enable"):
            expect_connection(loader, f"load_{field}[{lane}]", stage, f"load_{field}[{lane}]")
        for field in ("core", "addr", "row_enable", "payload"):
            fabric_field = "enable" if field == "row_enable" else field
            expect_connection(stage, f"write_{field}[{lane}]", fabric, f"wide_load_{fabric_field}[{lane}]")
        lanes.append({"lane": lane, "parent_response_port": response,
                      "registered_payload_net": stage[f"write_payload[{lane}]"].decode(),
                      "payload_bits": 512})
    return lanes


def audit(netlist, checksum):
    if digest(netlist) != checksum:
        raise ValueError("Unexpected candidate netlist digest")
    graph = hierarchy(netlist)
    (path, parent), = loader_paths(graph)
    if not path.endswith(".packed_loader") or graph[parent]["packed_write_stage"] != STAGE:
        raise ValueError(f"Unexpected packed weight hierarchy at {path}")
    fabric_master = graph[parent]["fabric"]
    if not fabric_master.startswith("tri_oracle_compute_fabric_"):
        raise ValueError(f"Unexpected compute fabric {fabric_master}")
    with netlist.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as source:
        parent_body = module_body(source, parent)
        lanes = verify_boundary(parent_body, module_body(source, STAGE),
                                pins(parent_body, LOADER, "packed_loader"),
                                pins(parent_body, STAGE, "packed_write_stage"),
                                pins(parent_body, fabric_master, "fabric"))
    return {"state": "native_packed_weight_path_is_raw",
            "netlist_sha256": checksum, "loader_instance": path,
            "packed_write_stage": STAGE, "lanes": lanes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("netlist", type=Path)
    parser.add_argument("--sha256", required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.netlist, args.sha256), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
