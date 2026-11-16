"""Bind a mapped credit receiver to the current packetized chip boundary."""
import argparse
import json
from pathlib import Path
import re

import link_tri_oracle_chip_packet_io as chip
from link_tri_oracle_indexed_whole_chip import module_at, spans
from link_tri_oracle_narrow_host import declarations, width
from measure_tri_oracle_serial_memory_requests import digest, read, replace
from verify_tri_oracle_host_control import outer_ports
from verify_tri_oracle_host_projection import include


BASE = chip.ROOT
STATUS = BASE / "host_status_joined"
DUAL_EDGE = BASE / "dual_edge_capture/whole_chip/prepared.json"
INGRESS = "tri_oracle_credit_memory_ingress"
TOP = "tri_oracle_chip_credited_memory"
PREFIX = "memory_mem_rsp_"
FIELDS = ("valid", "ready", "last", "error", "data")


def binding(mapped):
    prior = read(DUAL_EDGE)
    sys_wrapper = STATUS / "results_wrapper.v"
    sys_bundle = STATUS / "wrapper_bundle.sv"
    for path in (sys_wrapper, sys_bundle):
        assert digest(path) == prior["evidence_sha256"][str(path)], path
    source = sys_wrapper.read_text()
    (parent_name,) = {line.split()[1] for line in source.splitlines() if line.startswith("module ")}
    assert parent_name == "tri_oracle_chip_host_status_io"
    old = outer_ports(source)
    bridged = {f"{PREFIX}{field}": old[f"{PREFIX}{field}"] for field in FIELDS}
    exposed = {name: shape for name, shape in old.items() if name not in bridged}
    data = mapped.read_bytes()
    reader = chip.ports(module_at(data, spans(data), INGRESS))
    pin_to_pad = {
        name: PREFIX + name.removeprefix("pad_") for name in reader if name.startswith("pad_")
    }
    pin_to_pad["protocol_error"] = PREFIX + "protocol_error"
    assert set(pin_to_pad) == {
        "pad_data", "pad_valid", "pad_last", "pad_error", "pad_compact", "pad_words",
        "pad_credit", "protocol_error",
    }
    assert reader["pad_credit"] == reader["protocol_error"] == ("OUTPUT", 2)
    assert reader["pad_data"] == ("INPUT", 448)
    assert set(exposed).isdisjoint(pin_to_pad.values())
    exposed.update({wire: reader[pin] for pin, wire in pin_to_pad.items()})
    assembled = {f"assembled_{field}": bridged[f"{PREFIX}{field}"] for field in FIELDS}
    assembled_pins = {wire.replace("assembled_", "out_"): wire for wire in assembled}
    for pin, wire in assembled_pins.items():
        direction, bits = assembled[wire]
        assert reader[pin] == ("OUTPUT" if direction == "INPUT" else "INPUT", bits)
    connected = {"clk": "clk", "rst_n": "rst_n"} | pin_to_pad | assembled_pins
    assert connected.keys() == reader.keys()
    parent_binding = {name: name for name in old} | {
        name: name.replace(PREFIX, "assembled_") for name in bridged
    }
    result = f"module {TOP} (\n" + ",\n".join(declarations(exposed)) + "\n);\n"
    result += "".join(f"{wire};\n" for wire in declarations(assembled, wires=True))
    result += chip.instance(parent_name, "chip", parent_binding)
    result += chip.instance(INGRESS, "credit_receiver", connected)
    return result + "endmodule\n", width(exposed), prior, sys_bundle, sys_wrapper


def run(mapped, destination):
    source, bits, prior, sys_bundle, sys_wrapper = binding(mapped)
    wrapper = destination / "credit_wrapper.v"
    bundle = destination / "credit_bundle.sv"
    content = replace(sys_bundle.read_text(), include(STATUS / "attention_tb.sv"),
                      include(mapped) + include(wrapper))
    destination.mkdir(exist_ok=True)
    for path, text in ((wrapper, source), (bundle, content)):
        if path.exists():
            assert path.read_text() == text
        else:
            path.write_text(text)
    ports = outer_ports(wrapper.read_text())
    assert ports[PREFIX + "credit"] == ("OUTPUT", 2)
    assert PREFIX + "ready" not in ports and width(ports) == bits
    assert bits == prior["external_signal_bits"] + 2 == 531

    sources = tuple(map(Path, re.findall(r'(?m)^`include "([^"\n]+)"$', content)))
    modules = set()
    declaration = re.compile(rb"^\s*module\s+([^\s#(]+)")
    for path in sources:
        with path.open("rb") as stream:
            for line in stream:
                match = declaration.match(line)
                if match:
                    assert match[1] not in modules, (path, match[1])
                    modules.add(match[1])
    assert {TOP.encode(), INGRESS.encode(), b"tri_oracle_chip_host_status_io"} <= modules

    return {
        "state": "mapped_credit_receiver_structurally_bound_to_chip_port_inventory",
        "signals": bits, "credit_return_bits": 2, "protocol_error_bits": 2,
        "direct_source_files": len(sources), "distinct_module_declarations": len(modules),
        "clear_sites_from_predecessor_floorplan": prior["clear_sites_from_prior_floorplan"],
        "remaining_sites_before_power_spacing_and_board_requirements":
            prior["clear_sites_from_prior_floorplan"] - bits,
        "scope": "Digital topology and pin inventory. Whole-chip execution, physical pad placement, "
                 "package timing and power distribution remain unverified.",
        "evidence_sha256": {str(path): digest(path) for path in (
            *sources, bundle, sys_bundle, sys_wrapper, DUAL_EDGE, Path(__file__).resolve())},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mapped", type=Path)
    parser.add_argument("destination", type=Path)
    opts = parser.parse_args()
    print(json.dumps(run(opts.mapped.resolve(), opts.destination.resolve()), indent=2, sort_keys=True))
