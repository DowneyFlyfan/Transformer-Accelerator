"""Verify the cluster read interfaces and serialized memory boundary of the placed chip."""

from functools import cache
import json
import mmap
from pathlib import Path

from audit_tri_oracle_mapped_redundancy import TOP as COMPUTE, hierarchy
from check_tri_oracle_paper300_gate import PAPER_RELATIVE, PAPER_SHA256
from link_tri_oracle_indexed_whole_chip import module_at, pins, signature, spans
from verify_tri_oracle_booth_clock_boundary import PLACEMENT
from verify_tri_oracle_corrected_booth_roundtrip import ROOT, TOP, digest


CONTROL = ("req_valid", "req_ready", "rsp_valid", "rsp_ready", "rsp_last", "rsp_error")
VECTORS = {"req_address": 64, "req_length": 6, "rsp_data": 512}
RESPONSE = ("valid", "ready", "last", "error", "data")
TRANSMIT = ("valid", "ready", "data")
WRAPPERS = (
    ("tri_oracle_chip_host_status_io", "normalization"),
    ("tri_oracle_chip_projection_packet_io", "chip"),
    ("tri_oracle_chip_attention_packet_io", "chip"),
    ("tri_oracle_chip_rotary_packet_io", "chip"),
)


def require(actual, expected, context):
    if actual != expected:
        raise ValueError(f"{context}: expected {expected!r}, got {actual!r}")


def check_pins(actual, expected, context):
    for pin, wire in expected.items():
        require(actual.get(pin), wire.encode(), f"{context}.{pin}")


def check_clusters(clients, fabric):
    require(len(clients), 5, "grouped read clients")
    for cluster, client in enumerate(clients):
        expected = {f"mem_{signal}": f"cluster_{signal}[{cluster}]" for signal in CONTROL}
        expected.update({f"mem_{signal}": rf"\cluster_{signal}[{cluster}]" for signal in VECTORS})
        check_pins(client, expected, f"grouped_{cluster}")
    expected = {f"client_{signal}": f"cluster_{signal}" for signal in CONTROL}
    expected.update({f"client_{signal}[{i}]": rf"\cluster_{signal}[{i}]"
                     for i in range(5) for signal in VECTORS})
    expected.update({"mem_rsp_data[0]": "rsp_data", "mem_rsp_data[1]": "aux_rsp_data"})
    check_pins(fabric, expected, "grouped_reads")


def reject_swapped_connections(clients, fabric):
    address = "client_req_address"
    swapped_client = fabric | {f"{address}[0]": fabric[f"{address}[1]"], f"{address}[1]": fabric[f"{address}[0]"]}
    swapped_lane = fabric | {"mem_rsp_data[0]": fabric["mem_rsp_data[1]"], "mem_rsp_data[1]": fabric["mem_rsp_data[0]"]}
    rejected = {}
    for case, changed, first_pin in (
        ("cluster_address_swap", swapped_client, "client_req_address[0]"),
        ("memory_response_lane_swap", swapped_lane, "mem_rsp_data[0]"),
    ):
        try:
            check_clusters(clients, changed)
        except ValueError as error:
            require(str(error).partition(":")[0], f"grouped_reads.{first_pin}", case)
            rejected[case] = first_pin
        else:
            raise AssertionError(f"Accepted {case}")
    return rejected


def verify():
    paper = Path(PAPER_RELATIVE)
    require(digest(paper), PAPER_SHA256, paper)
    placed = json.loads(PLACEMENT.read_text())
    netlist = Path(placed["database"]).parents[1] / "cold/cold.v"
    netlist_digest = placed["evidence_sha256"][str(netlist)]
    require(digest(netlist), netlist_digest, netlist)
    graph = hierarchy(netlist)
    with netlist.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
        index = spans(data)

        def binding(master, instance, child=None):
            actual = graph[master][instance]
            if child is not None:
                require(actual, child, f"{master}.{instance}")
            return pins(module_at(data, index, master), actual, instance)

        @cache
        def ports(master):
            return signature(module_at(data, index, master))

        def port(master, name, direction, width):
            fields = (direction.encode(), b"" if width == 1 else f"[{width - 1}:0]".encode())
            require(ports(master).get(name), fields, f"{master}.{name}")

        grouped = "tri_oracle_grouped_read_fabric_cells"
        fabric = binding(COMPUTE, "grouped_reads", grouped)
        clients = [binding(COMPUTE, f"grouped_{i}") for i in range(5)]
        check_clusters(clients, fabric)
        for i in range(5):
            for vector, width in VECTORS.items():
                client_output = vector != "rsp_data"
                port(grouped, f"client_{vector}[{i}]", "input" if client_output else "output", width)
                port(graph[COMPUTE][f"grouped_{i}"], f"mem_{vector}", "output" if client_output else "input", width)
        for i, name in enumerate(("rsp_data", "aux_rsp_data")):
            port(grouped, f"mem_rsp_data[{i}]", "input", 512)
            port(COMPUTE, name, "input", 512)
        port(COMPUTE, "proj_rsp_data", "input", 64)

        credited = "tri_oracle_chip_credited_metadata"
        external_response = ("data", "metadata", "credit", "protocol_error")
        check_pins(binding(TOP, "chip", credited),
                   {f"memory_mem_rsp_{name}": f"memory_mem_rsp_{name}" for name in external_response}
                   | {f"memory_tx_{name}": f"wide_memory_tx_{name}" for name in TRANSMIT}, "top.chip")
        check_pins(binding(TOP, "request_link", "tri_oracle_memory_tx_credit"),
                   {"in_valid": "wide_memory_tx_valid", "in_ready": "wide_memory_tx_ready",
                    "in_word": "wide_memory_tx_data", "pad_data": "memory_tx_data",
                    "pad_valid": "memory_tx_valid", "pad_credit": "memory_tx_credit"}, "request_link")
        receiver = "tri_oracle_credit_metadata_ingress"
        check_pins(binding(credited, "credit_receiver", receiver),
                   {"pad_data": "memory_mem_rsp_data", "pad_metadata": "memory_mem_rsp_metadata",
                    "pad_credit": "memory_mem_rsp_credit", "protocol_error": "memory_mem_rsp_protocol_error"}
                   | {f"out_{name}": f"assembled_{name}" for name in RESPONSE}, "credit_receiver")
        check_pins(binding(credited, "chip", WRAPPERS[0][0]),
                   {f"memory_mem_rsp_{name}": f"assembled_{name}" for name in RESPONSE}
                   | {f"memory_tx_{name}": f"memory_tx_{name}" for name in TRANSMIT}, "credited.chip")
        packet = "tri_oracle_chip_packet_io"
        pass_through = {f"memory_mem_rsp_{name}": f"memory_mem_rsp_{name}" for name in RESPONSE}
        pass_through.update({f"memory_tx_{name}": f"memory_tx_{name}" for name in TRANSMIT})
        for (owner, instance), child in zip(WRAPPERS, [name for name, _ in WRAPPERS[1:]] + [packet], strict=True):
            check_pins(binding(owner, instance, child), pass_through, owner)
        accelerator = binding(packet, "accelerator", COMPUTE)
        check_pins(accelerator, {name: name for name in ("rsp_data", "aux_rsp_data", "proj_rsp_data")},
                   "accelerator")
        check_pins(binding(packet, "memory_link", "tri_oracle_memory_io_link"),
                   {f"mem_rsp_{name}": f"memory_mem_rsp_{name}" for name in RESPONSE}
                   | {f"tx_{name}": f"memory_tx_{name}" for name in TRANSMIT}
                   | {"rsp_data": "{proj_rsp_data,dma_aux_rsp_data,rsp_data}"}, "memory_link")
        port(TOP, "memory_mem_rsp_data", "input", 448)
        port(TOP, "memory_mem_rsp_metadata", "input", 7)
        port(TOP, "memory_tx_data", "output", 8)
        port(graph[credited]["chip"], "memory_mem_rsp_data", "input", 1024)

    require(digest(netlist), netlist_digest, netlist)
    return {
        "state": "placed_booth_memory_interconnect_verified",
        "database_fingerprint_sha256": placed["database_fingerprint_sha256"],
        "paper_figure": "31.6.2",
        "grouped_memory_clients": 5,
        "grouped_response_lanes_bits": [512, 512],
        "projection_response_bits": 64,
        "packed_memory_boundary_bits": {"transmit_data": 8, "response_data": 448, "response_metadata": 7},
        "memory_wrapper_masters": [name for name, _ in WRAPPERS],
        "rejected_negative_controls": reject_swapped_connections(clients, fabric),
        "paper_network_on_chip_equivalence_verified": False,
        "scope": "Named port associations and payload widths of the grouped read clients and external "
                 "memory wrappers on the cold-placed netlist. This does not trace cell-level steering inside "
                 "the memory arbiter. "
                 "Figure 31.6.2 shows a network serving all clusters and a local network serving the cores "
                 "and aggregator. The figure does not specify the packet format or arbitration.",
        "evidence_sha256": {str(PLACEMENT): digest(PLACEMENT), str(paper): PAPER_SHA256,
                            str(netlist): netlist_digest,
                            str(Path(__file__).resolve().relative_to(ROOT)): digest(Path(__file__))},
    }


if __name__ == "__main__":
    assert Path.cwd() == ROOT and not Path("/.dockerenv").is_file()
    print(json.dumps(verify(), indent=2, sort_keys=True))
