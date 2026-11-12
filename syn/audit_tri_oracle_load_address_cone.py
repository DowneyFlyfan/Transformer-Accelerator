"""Check combinational reachability into the mapped fabric load-address pins."""

import argparse
from collections import deque
import json
from pathlib import Path
import re

from audit_tri_oracle_wac_parent_hdl_export import declarations
from verify_linked_placed_topology import COMMENT, bits, module_index, parse_module, pin_fields


def cell_interfaces(models):
    cells = {}
    for match in re.finditer(r"(?ms)^module (\w+)\s*\([^;]+;(.+?)^endmodule\b", models):
        name, body = match.groups()
        body = COMMENT.sub("", body)
        ports, _ = declarations(body)
        storage = re.search(r"\b(?:tsmc_dff\w*|tsmc_dla\w*|always)\b", body)
        assert name not in cells
        cells[name] = ports, "state" if storage else "combinational"
    return cells


def dependency_graph(code, modules, view, cells):
    _, ports, nets, instances, assignments = view
    drivers = {}
    interface = {}

    def add(net, driver, kind, inputs):
        assert net[0] != "constant" and net not in drivers, (net, driver, drivers.get(net))
        drivers[net] = (driver, kind, inputs)

    for target, source in assignments:
        for left, right in zip(bits(target, nets), bits(source, nets), strict=True):
            add(left, "assignment", "combinational", (right,))
    for instance, (master, raw) in instances.items():
        if master in cells:
            ports_by_name, kind = cells[master]
        else:
            if master not in interface:
                interface[master] = parse_module(code, modules[master])[1]
            ports_by_name, kind = interface[master], "hierarchy"
        connected = {pin.removeprefix("\\"): bits(net, nets) for pin, net in pin_fields(raw).items()}
        assert connected.keys() <= ports_by_name.keys(), (instance, master)
        inputs = tuple(net for pin, connected_bits in connected.items()
                       if ports_by_name[pin][0] == "input" for net in connected_bits)
        for pin, connected_bits in connected.items():
            if ports_by_name[pin][0] == "output":
                for net in connected_bits:
                    add(net, f"{instance}/{pin}", kind, inputs if kind == "combinational" else ())
    input_names = {name for name, (direction, _) in ports.items() if direction == "input"}
    assert not any(net[1] in input_names for net in drivers)
    return drivers, input_names


def cone(net, drivers, input_names):
    start = ("scalar", "rsp_valid")
    queue = deque([net])
    downstream = {net: None}
    opaque = set()
    while queue:
        point = queue.popleft()
        if point[0] == "constant" or point[1] in input_names:
            continue
        driver, kind, inputs = drivers[point]
        if kind == "hierarchy":
            opaque.add(driver)
        for upstream in inputs:
            if upstream not in downstream:
                downstream[upstream] = point
                queue.append(upstream)
    path = []
    if start in downstream:
        current = downstream[start]
        while current is not None:
            path.append(drivers[current][0])
            current = downstream[current]
    return {"rsp_valid_reachable": start in downstream, "path_drivers": path,
            "opaque_hierarchy_outputs": sorted(opaque)}


def audit(netlist, models):
    code = netlist.read_text()
    modules = module_index(code)
    top, = (name for name in modules if name.startswith("tri_oracle_batched_tensor390_"))
    view = parse_module(code, modules[top])
    assert view[1]["rsp_valid"] == ("input", None)
    _, fields = view[3]["fabric"]
    fabric = pin_fields(fields)
    address = bits(fabric["load_addr"], view[2])
    valid, = bits(fabric["load_valid"], view[2])
    assert len(address) == 10
    drivers, input_names = dependency_graph(code, modules, view, cell_interfaces(models.read_text()))
    return {
        "top": top,
        "load_valid": cone(valid, drivers, input_names),
        "address_bits": {index: cone(net, drivers, input_names) for index, net in enumerate(reversed(address))},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("netlist", type=Path)
    parser.add_argument("cell_models", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.netlist, args.cell_models), indent=2))
