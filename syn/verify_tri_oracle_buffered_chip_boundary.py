"""Check the clock, command, and grouped read boundary on the buffered chip."""

import argparse
from contextlib import ExitStack
from functools import cache, lru_cache
import json
from pathlib import Path
import re
import resource

from audit_tri_oracle_mapped_redundancy import CORE, TOP, audit, hierarchy
from audit_tri_oracle_placed_fanout import GIB, memory, sha
from audit_tri_oracle_wac_parent_hdl_export import ASSOCIATION, declarations
from check_tri_oracle_paper300_gate import PAPER_RELATIVE, PAPER_SHA256
from link_tri_oracle_parallel_chip import catalog, definition


ROOT = Path(__file__).resolve().parents[1]
STRUCTURE = ROOT / "records/tri_oracle_bounded_decoder_mapped_paper_structure.json"
SEED = ROOT / "records/tri_oracle_bounded_decoder_probability_buffer_seed.json"

HOST = {
    "command_valid": ("input", 1), "command_ready": ("output", 1),
    "command_opcode": ("input", 3), "command_tag": ("input", 32),
    "payload_valid": ("input", 1), "payload_ready": ("output", 1),
    "payload_data": ("input", 64), "payload_last": ("input", 1),
    "response_valid": ("output", 1), "response_ready": ("input", 1),
    "response_error": ("output", 1), "response_opcode": ("output", 3),
    "response_tag": ("output", 32),
}
READ_CONTROLS = ("req_valid", "req_ready", "rsp_valid", "rsp_ready",
                 "rsp_last", "rsp_error")
READ_VECTORS = ("req_address", "req_length", "rsp_data")


def load(path):
    return json.loads(path.read_text())


def wire_width(span):
    return 1 if span is None else abs(span[0] - span[1]) + 1


def require(port, expected, context):
    if port != expected:
        raise ValueError(f"{context}: expected {expected!r}, observed {port!r}")


def inspect_connections(graph, modules, clusters):
    @lru_cache(maxsize=4)
    def body(master):
        return definition(modules[master])

    @cache
    def interface(master):
        _, delimiter, text = body(master).decode("ascii").partition(";")
        require(delimiter, ";", master)
        ports, _ = declarations(text)
        return {name: (direction, wire_width(span)) for name, (direction, span) in ports.items()}

    @cache
    def wires(master, name):
        pattern = rb"(?m)^[ \t]+[\w$]+\s+" + re.escape(name.encode()) + rb"\s*\(([^;]*)\);"
        (raw,) = re.findall(pattern, body(master))
        fields = raw.decode("ascii")
        pairs = ASSOCIATION.findall(fields)
        require(ASSOCIATION.sub("", fields).strip(" ,\t\n"), "", f"{master}.{name}")
        result = {pin.removeprefix("\\"): " ".join(term.split()) for pin, term in pairs}
        require(len(result), len(pairs), f"{master}.{name} unique pins")
        return result

    def direct_clock(master, child):
        require(interface(master).get("clk"), ("input", 1), f"{master}.clk")
        require(wires(master, child).get("clk"), "clk", f"{master}.{child}.clk")
        return graph[master][child]

    def toward_master(path):
        master = TOP
        cursor = path.removeprefix(TOP + ".")
        require(cursor != path, True, path)
        while cursor:
            candidates = [name for name in graph[master]
                          if cursor == name.removeprefix("\\") or
                          cursor.startswith(name.removeprefix("\\") + ".")]
            if not candidates:
                raise ValueError(f"{path}: missing mapped child at {cursor}")
            child = max(candidates, key=len)
            master = direct_clock(master, child)
            cursor = cursor[len(child.removeprefix("\\")):].removeprefix(".")
        return master

    top_ports = interface(TOP)
    dispatcher = direct_clock(TOP, "dispatch")
    require(dispatcher, "tri_oracle_indexed_chip_dispatch", "mapped command dispatcher")
    arbiter = direct_clock(TOP, "grouped_reads")
    require(arbiter, "tri_oracle_grouped_read_fabric_cells", "mapped grouped read arbiter")
    require(top_ports.get("rst_n"), ("input", 1), "external reset")
    for signal, spec in HOST.items():
        require(top_ports.get(signal), spec, signal)
        require(interface(dispatcher).get(signal), spec, f"dispatch formal {signal}")
        require(wires(TOP, "dispatch").get(signal), signal, f"dispatch connection {signal}")

    layer = wires(TOP, "layer")
    require(layer.get("cfg_valid"), "wb_compute_cfg_valid", "configuration after writeback arbitration")
    for index, port in enumerate(("projection", "frame", "restore", "head", "row"), start=1):
        require(layer.get(port + "_valid"), f"layer_command_valid[{index}]", port)
    require(wires(TOP, "dispatch").get("layer_command_valid"),
            "{ grouped_batch_command_valid, grouped_command_valid, layer_command_valid }",
            "dispatcher command valid vector")

    for port in ("rsp_data", "aux_rsp_data"):
        require(top_ports.get(port), ("input", 512), f"external {port}")
    fanin = wires(TOP, "grouped_reads")
    for lane, port in enumerate(("rsp_data", "aux_rsp_data")):
        require(fanin.get(f"mem_rsp_data[{lane}]"), port, f"grouped arbiter memory lane {lane}")

    endpoints = {"clusters": 0, "cores": 0, "arrays": 0, "grouped_clients": 0}
    for cluster in clusters:
        index = cluster["bank"]
        master = toward_master(cluster["instance"])
        require(interface(master).get("clk"), ("input", 1), f"cluster {index} clock")
        endpoints["clusters"] += 1
        for child, core in graph[master].items():
            if CORE.fullmatch(core) is None:
                continue
            require(direct_clock(master, child), core, child)
            array = direct_clock(direct_clock(core, "compute"), "compute")
            require(interface(array).get("clk"), ("input", 1), array)
            endpoints["cores"] += 1
            endpoints["arrays"] += 1

        group = f"grouped_{index}"
        direct_clock(TOP, group)
        consumer = wires(TOP, group)
        for port in READ_CONTROLS:
            vector = f"cluster_{port}"
            require(consumer.get(f"mem_{port}"), f"{vector}[{index}]", group)
            require(fanin.get(f"client_{port}"), vector, arbiter)
        for port in READ_VECTORS:
            vector = rf"\cluster_{port}[{index}]"
            require(consumer.get(f"mem_{port}"), vector, group)
            require(fanin.get(f"client_{port}[{index}]"), vector, arbiter)
        endpoints["grouped_clients"] += 1
    require(endpoints, {"clusters": 5, "cores": 20, "arrays": 20, "grouped_clients": 5}, "clock endpoints")
    return endpoints


def verify(netlist):
    if not __debug__ or not Path("/.dockerenv").is_file() or memory()[0] < 8 * GIB:
        raise RuntimeError("Run in the Cadence container with assertions enabled and 8 GiB available")
    resource.setrlimit(resource.RLIMIT_AS, (3900 * 2**20, 3900 * 2**20))
    paper = ROOT / PAPER_RELATIVE
    require(sha(paper), PAPER_SHA256, paper)
    expected = load(SEED)["buffered_netlist_sha256"]
    require(sha(netlist), expected, netlist)
    graph = hierarchy(netlist)
    topology = audit(graph)
    reference = load(STRUCTURE)
    require(topology["clusters"], reference["clusters"], "preserved cluster topology")
    require(topology["additional_shared_prediction_instances"],
            reference["additional_shared_prediction_instances"], "preserved shared prediction paths")
    with ExitStack() as stack:
        endpoints = inspect_connections(graph, catalog(stack, netlist), topology["clusters"])
    require(sha(netlist), expected, "candidate changed during verification")
    evidence = [paper, SEED, STRUCTURE, Path(__file__).resolve()]
    return {
        "state": "candidate_bound_clock_command_and_grouped_read_boundary_verified",
        "candidate_sha256": expected,
        "external_clock_pin": "clk",
        "direct_external_clock_endpoints": endpoints,
        "dispatcher_host_ports": len(HOST),
        "grouped_read_client_signals_per_cluster": len(READ_CONTROLS) + len(READ_VECTORS),
        "external_grouped_read_response_widths": [512, 512],
        "paper_clock_generator_equivalence": False,
        "paper_network_protocol_equivalence_verified": False,
        "scope": "Direct external clock connections, command boundary, and grouped read binding on the "
                 "buffered Innovus seed. The paper includes an on-chip phase-locked loop and a network-on-chip.",
        "evidence_sha256": {str(path.relative_to(ROOT)): sha(path) for path in evidence},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("netlist", type=Path)
    print(json.dumps(verify(parser.parse_args().netlist), indent=2, sort_keys=True))
