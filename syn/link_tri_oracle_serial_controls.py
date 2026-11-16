"""Bind the serialized controls to the verified credited chip interface."""
import argparse
import json
from pathlib import Path

from link_tri_oracle_chip_packet_io import instance
from link_tri_oracle_narrow_host import declarations, width
from measure_tri_oracle_serial_memory_requests import digest, read
from verify_tri_oracle_host_control import outer_ports


ROOT = Path(__file__).resolve().parents[1]
PARENT = Path(".cache/physical/whole_chip_xcelium_speed/split_credit_ingress/chip_binding/credit_wrapper.v")
PRIOR = Path("records/tri_oracle_split_credit_ingress.json")
CAPACITY = Path("records/tri_oracle_bonded_pad_capacity.json")
BRIDGE = "tri_oracle_serial_control_pads"
TOP = "tri_oracle_chip_serial_controls"
CLOCK = ("clk", "rst_n")
# Flags occupy the high bits of each original data word.
LINKS = {
    "host_rx": (4, ("host_rx_payload_last", "host_rx_is_payload")),
    "host_tx": (4, ("host_tx_last",)),
    "memory_tx": (8, ()),
}


def module(name, ports, body):
    return f"module {name} (\n" + ",\n".join(declarations(ports)) + "\n);\n" + body + "endmodule\n"


def bind():
    assert Path.cwd() == ROOT and __debug__
    credit = read(PRIOR)
    assert digest(PARENT) == credit["evidence_sha256"][str(PARENT)]
    source = PARENT.read_text()
    assert source.startswith("module tri_oracle_chip_credited_memory (")
    original = outer_ports(source)
    assert width(original) == credit["whole_chip_structural_signal_bits"] == 531
    physical = dict(original)
    internal = {}
    bridge = {pin: original[pin] for pin in CLOCK}
    body = ""
    for link, (pad_bits, flags) in LINKS.items():
        valid, ready, data = (f"{link}_{field}" for field in ("valid", "ready", "data"))
        inputs = original[data][0] == "INPUT"
        selected = {pin: original[pin] for pin in (valid, ready, data, *flags)}
        internal.update({f"wide_{pin}": spec for pin, spec in selected.items()})
        physical[data] = (original[data][0], pad_bits)
        for flag in flags:
            del physical[flag]
        bridge.update({pin: physical[pin] for pin in (valid, ready, data)})
        bridge.update({f"wide_{pin}": ("OUTPUT" if direction == "INPUT" else "INPUT", bits)
                       for pin, (direction, bits) in selected.items()})
        word_bits = width({pin: original[pin] for pin in (*flags, data)})
        serializer = "tri_oracle_flit_from_pads" if inputs else "tri_oracle_flit_to_pads"
        wide_word = "{" + ", ".join(f"wide_{pin}" for pin in (*flags, data)) + "}" if flags else f"wide_{data}"
        wide_side = "out" if inputs else "in"
        body += instance(f"{serializer} #(.WORD_BITS({word_bits}), .PAD_BITS({pad_bits}))", link, {
            "clk": "clk", "rst_n": "rst_n", "pad_valid": valid, "pad_ready": ready, "pad_data": data,
            f"{wide_side}_valid": f"wide_{valid}", f"{wide_side}_ready": f"wide_{ready}",
            f"{wide_side}_word": wide_word,
        })
    unchanged = original.keys() - {pin.removeprefix("wide_") for pin in internal}
    assert all(physical[pin] == original[pin] for pin in unchanged)
    assert physical["memory_mem_rsp_data"] == ("INPUT", 448) and width(physical) == 490
    wide = {pin: f"wide_{pin}" if pin not in unchanged else pin for pin in original}
    wires = "".join(f"{line};\n" for line in declarations(internal, wires=True))
    wrappers = wires + instance("tri_oracle_chip_credited_memory", "chip", wide)
    wrappers += instance(BRIDGE, "serial_pads", {pin: pin for pin in bridge})
    return module(BRIDGE, bridge, body), module(TOP, physical, wrappers), physical


def run(out):
    pads, chip, ports = bind()
    out.mkdir(parents=True, exist_ok=True)
    for name, content in (("serial_control_pads.v", pads), ("serial_control_wrapper.v", chip)):
        path = out / name
        path.write_text(content)
    assert outer_ports(chip) == ports
    bonded = read(CAPACITY)
    reserve = sum(bonded["illustrative_supply_and_ground_pads"].values())
    return {
        "physical_signal_bits": width(ports),
        "removed_signal_bits": 531 - width(ports),
        "double_edge_receive_bits": ports["memory_mem_rsp_data"][1],
        "illustrative_supply_and_ground_reserve": reserve,
        "site_margin_by_case": {
            name: case["sites"] - width(ports) - reserve for name, case in bonded["scenarios"].items()
        },
        "evidence_sha256": {str(path): digest(path) for path in (PARENT, PRIOR, CAPACITY, *(
            out / name for name in ("serial_control_pads.v", "serial_control_wrapper.v")))},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.out), indent=2, sort_keys=True))
