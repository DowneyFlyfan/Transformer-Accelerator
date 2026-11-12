"""Observe the mapped write-mux input after Genus propagates the scalar strobe."""

from contextlib import ExitStack
import re

from link_tri_oracle_parallel_chip import catalog, definition
from prepare_tri_oracle_packed_sign_predictor import rewrite
from verify_linked_placed_topology import bits, parse_module, pin_fields


PAYLOAD = "{dut.layer.layer.wr_data, dut.layer.layer.wr_data_last, dut.layer.layer.wr_strobe}"
MAPPED_PAYLOAD = "{dut.layer.shared_writes.scalar_data, dut.layer.shared_writes.scalar_data_last, dut.layer.shared_writes.scalar_strobe}"


def observation_source(netlist, top):
    with ExitStack() as stack:
        modules = catalog(stack, netlist)

        def view(master):
            text = definition(modules[master]).decode()
            return parse_module(text, (0, len(text)))

        wrapper, _ = view(top)[3]["layer"]
        _, _, nets, children, _ = view(wrapper)
        core, producer = children["layer"]
        mux, consumer = children["shared_writes"]
        assert mux == "tri_oracle_external_write_mux"
        producer, consumer = map(pin_fields, (producer, consumer))
        for field in ("data", "data_valid", "data_ready", "data_last"):
            source = bits(producer["wr_" + field], nets)
            sink = bits(consumer["scalar_" + field], nets)
            assert source and source == sink, field
        _, core_ports, _, core_children, assigns = view(core)
        _, mux_ports, _, _, _ = view(mux)
        assert core_ports["wr_strobe"] == ("output", (7, 0))
        assert mux_ports["scalar_strobe"] == ("input", (7, 0))
        source = bits(producer["wr_strobe"], nets)
        sink = bits(consumer["scalar_strobe"], nets)
        if source == sink:
            assert len(source) == 8
            return "directly_connected"
        assert consumer["scalar_strobe"] == "8'b11111111"
        assert len(source) == 8 and all(
            bit[0] == "scalar" and re.fullmatch(r"UNCONNECTED\d+", bit[1]) for bit in source
        ), source
        assert all(not re.search(r"\bwr_strobe\b", value) for row in assigns for value in row)
        assert all(not re.search(r"\(\s*wr_strobe(?:\[|\s*\))", fields) for _, fields in core_children.values())
        return "constant_propagated_to_mux"


def retarget(text):
    return rewrite(text, ((PAYLOAD, MAPPED_PAYLOAD),))
