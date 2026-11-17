"""Trace grouped cluster data to the direct and packetized host interfaces."""

import json
from mmap import ACCESS_READ, mmap
from pathlib import Path

from audit_tri_oracle_mapped_redundancy import TOP
from audit_tri_oracle_packed_weight_path import pins
from check_tri_oracle_paper300_gate import PAPER_RELATIVE, PAPER_SHA256
from link_tri_oracle_indexed_whole_chip import module_at, signature, spans
from verify_tri_oracle_booth_chip_link import named_bindings
from verify_tri_oracle_booth_memory_interconnect import check_clusters, check_pins, reject_swapped_connections
from verify_tri_oracle_serialized_placement_transfer import INSTANCE
from verify_tri_oracle_value_register_clock_rows import ROOT, linked_file, pin


PLACED_PACKET = Path("records/tri_oracle_corrected_booth_buffered_placement_roundtrip.json")
WIDE_PLACEMENTS = Path("records/tri_oracle_value_register_clock_rows.json")
PACKET_ROOT = "tri_oracle_chip_credited_request"
GROUP_PORTS = {
    "group_valid": (b"output", b""),
    "group_ready": (b"input", b""),
    "group_last": (b"output", b""),
    "group_tag": (b"output", b"[31:0]"),
    "group_cluster": (b"output", b"[2:0]"),
    "group_lane": (b"output", b"[1:0]"),
    "group_values": (b"output", b"[2047:0]"),
}
WRAPPER_CHAIN = (
    ("tri_oracle_chip_host_status_io", "tri_oracle_chip_projection_packet_io", "normalization"),
    ("tri_oracle_chip_projection_packet_io", "tri_oracle_chip_attention_packet_io", "chip"),
    ("tri_oracle_chip_attention_packet_io", "tri_oracle_chip_rotary_packet_io", "chip"),
    ("tri_oracle_chip_rotary_packet_io", "tri_oracle_chip_packet_io", "chip"),
    ("tri_oracle_chip_packet_io", TOP, "accelerator"),
)
PAYLOAD_PORTS = {"rsp_data": (b"input", b"[511:0]"), "aux_rsp_data": (b"input", b"[511:0]"),
                 "proj_rsp_data": (b"input", b"[63:0]"), "wr_data": (b"output", b"[63:0]")}


def hosts(packet_path):
    with packet_path.open("rb") as stream, mmap(stream.fileno(), 0, access=ACCESS_READ) as source:
        index = spans(source)
        group_wires = dict(zip(GROUP_PORTS, GROUP_PORTS, strict=True))
        for owner, child, inst in WRAPPER_CHAIN:
            links = pins(module_at(source, index, owner), child, inst)
            check_pins(links, group_wires, owner)
        host = module_at(source, index, WRAPPER_CHAIN[0][0])
        group_tx = pins(host, "tri_oracle_host_grouped_tx", "grouped_tx")
        writeback_tx = pins(host, "tri_oracle_host_writeback_tx", "writeback_tx")
        status = pins(host, "tri_oracle_host_status_link", "status_link")
        check_pins(group_tx, group_wires, "grouped_tx")
        for kind in ("ready", "valid", "last", "data"):
            combined = b"combined_" + kind.encode()
            prior = b"prior_" + kind.encode()
            assert group_tx["tx_" + kind] == writeback_tx["source_" + kind] == combined
            assert writeback_tx["tx_" + kind] == status["source_" + kind] == prior
        core_ports = signature(module_at(source, index, TOP))
        assert {name: core_ports[name] for name in GROUP_PORTS} == GROUP_PORTS
        wrapper = module_at(source, index, "tri_oracle_chip_packet_io")
        assert pins(wrapper, TOP, "accelerator").keys() == core_ports.keys()
        packet_ports = signature(module_at(source, index, PACKET_ROOT))
        assert packet_ports["host_tx_data"] == (b"output", b"[3:0]")
        assert packet_ports["memory_tx_data"] == (b"output", b"[7:0]")
        assert packet_ports["memory_mem_rsp_data"] == (b"input", b"[447:0]")
        return core_ports


def gate_predecessors(top):
    drivers = {}
    for instance in INSTANCE.finditer(top):
        master = instance[1]
        if not master.endswith(b"BWP12T40P140"):
            continue
        start = top.find(b"(", instance.start(), instance.end()) + 1
        stop = top.find(b");", instance.end())
        assert start < stop
        associations = named_bindings(top[start:stop])
        if (output := associations.pop("Z", None)) is None:
            output = associations.pop("ZN", None)
        if output is not None:
            assert output not in drivers, output
            drivers[output] = frozenset(associations.values())
    return drivers


def check_data_paths(drivers):
    for i in range(2048):
        raw = f"grouped_result_values[{i}]".encode()
        ports = [f"{prefix}[{i}]".encode() for prefix in ("out_data", "result_values")]
        for port in ports:
            intermediates = drivers.get(port, ())
            assert any(raw in drivers.get(wire, ()) for wire in intermediates), (i, port)
    for src, dst in ((b"grouped_out_valid", b"out_valid"), (b"selected_result_last", b"out_last")):
        assert src in drivers[dst], (src, dst)


def wide_candidate(path, previous_ports):
    with path.open("rb") as stream, mmap(stream.fileno(), 0, access=ACCESS_READ) as source:
        index = spans(source)
        top = module_at(source, index, TOP)
        caller = signature(top)
        assert caller == {key: value for key, value in previous_ports.items() if key not in GROUP_PORTS}
        assert PACKET_ROOT not in index and "tri_oracle_host_grouped_tx" not in index
        assert {name: caller[name] for name in PAYLOAD_PORTS} == PAYLOAD_PORTS
        batch = pins(top, "tri_oracle_grouped_cluster_batch_cells", "batch")
        check_pins(batch, {"result_ready": "wb_out_ready", "result_data": "grouped_result_values",
                          "result_valid": "grouped_out_valid", "result_last": "selected_result_last"}, "batch")
        writer = pins(top, "tri_oracle_decoder_bank_writeback", "bank_writeback")
        check_pins(writer, {"in_valid": "out_valid", "in_last": "out_last", "in_data": "out_data",
                           "out_ready": "wb_out_ready", "out_data": "wb_out_data"}, "bank_writeback")
        assert caller["wb_out_data"] == (b"output", b"[127:0]")
        assert caller["result_values"] == (b"output", b"[2047:0]")
        gates = gate_predecessors(top)
        check_data_paths(gates)
        bad = dict(gates)
        bad[b"out_data[0]"] = bad[b"out_data[1]"]
        try:
            check_data_paths(bad)
        except AssertionError as error:
            assert error.args == ((0, b"out_data[0]"),)
        else:
            raise AssertionError("Grouped output data lane swap passed")
        stage = signature(module_at(source, index, "tri_oracle_packed_write_stage_mapped"))
        for lane in range(2):
            assert stage[f"write_payload[{lane}]"] == (b"output", b"[1023:0]")
        fabric = pins(top, "tri_oracle_grouped_read_fabric_cells", "grouped_reads")
        groups = [pins(top, f"tri_oracle_native_probability_copy_{5*i}", f"grouped_{i}") for i in range(5)]
        check_clusters(groups, fabric)
        rejected = reject_swapped_connections(groups, fabric)
        return {"common_accelerator_port_declarations": len(caller), "internal_write_lane_bits": [1024, 1024],
                "same_index_grouped_data_paths_to_direct_result_and_writeback_input": 2048,
                "external_write_data_bits": 64, "grouped_read_clients": 5,
                "rejected_controls": list(rejected) + ["grouped_writeback_data_bit_swap"]}


def verify():
    evidence = {}
    pin(Path(PAPER_RELATIVE), evidence, PAPER_SHA256)
    packet_record = json.loads(pin(PLACED_PACKET, evidence).read_text())
    packet = linked_file(packet_record, "/cold/cold.v", evidence)
    packet_core = hosts(packet)
    current = json.loads(pin(WIDE_PLACEMENTS, evidence).read_text())
    results = {}
    for key, placed in current["placement"].items():
        wanted = placed["cold_netlist_sha256"]
        part, = (Path(name) for name, value in current["evidence_sha256"].items()
                 if value == wanted and name.endswith("/cold.v"))
        pin(part, evidence, wanted)
        results[key] = {"cold_netlist_sha256": wanted} | wide_candidate(part, packet_core)
    for p in (Path(__file__).resolve().relative_to(ROOT),
              Path("syn/audit_tri_oracle_packed_weight_path.py"),
              Path("syn/link_tri_oracle_indexed_whole_chip.py"),
              Path("syn/verify_tri_oracle_booth_memory_interconnect.py"),
              Path("syn/verify_tri_oracle_booth_chip_link.py"),
              Path("syn/verify_tri_oracle_value_register_clock_rows.py")):
        pin(p, evidence)
    return {
        "state": "native_wide_placement_and_existing_package_boundary_gap_verified",
        "paper_figure": "31.6.2",
        "packetized_candidate_sha256": evidence[str(packet)],
        "packetized_accelerator_port_declarations": len(packet_core),
        "wide_candidates": results,
        "grouped_transport_signals_missing_from_both_wide_accelerator_boundaries": list(GROUP_PORTS),
        "scope": ("Exact logic and named wires on three native placement exports. The packaged candidate "
                  "has a separate grouped-result host transmitter. The two wider candidates expose shared "
                  "writeback and a direct result bus. A direct substitution loses the grouped host "
                  "handshake. Packaged wide-lane operation, the paper network protocol, and physical "
                  "timing remain unqualified."),
        "evidence_sha256": evidence,
    }


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT
    print(json.dumps(verify(), indent=2, sort_keys=True))
