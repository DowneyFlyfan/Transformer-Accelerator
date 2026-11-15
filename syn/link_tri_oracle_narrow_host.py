"""Prepare the exact cold chip plus its synthesized host command link."""
import argparse
import json
from pathlib import Path
import re

from audit_tri_oracle_placed_chip_boundary import TOP, verilog_ports
from audit_tri_oracle_placed_fanout import sha
from check_tri_oracle_paper300_gate import BOUNDED_STAGE, BOUNDED_TOKEN_MAP_PLACEMENT


ADAPTER = "tri_oracle_host_command_link"
WRAPPER = "tri_oracle_chip_narrow_host"
HOST = {
    "command_valid": ("INPUT", None), "command_ready": ("OUTPUT", None),
    "command_opcode": ("INPUT", 3), "command_tag": ("INPUT", 32),
    "payload_valid": ("INPUT", None), "payload_ready": ("OUTPUT", None),
    "payload_data": ("INPUT", 64), "payload_last": ("INPUT", None),
    "response_valid": ("OUTPUT", None), "response_ready": ("INPUT", None),
    "response_error": ("OUTPUT", None), "response_opcode": ("OUTPUT", 3),
    "response_tag": ("OUTPUT", 32),
}
PHYSICAL = {
    "rx_valid": ("INPUT", None), "rx_ready": ("OUTPUT", None),
    "rx_is_payload": ("INPUT", None), "rx_payload_last": ("INPUT", None),
    "rx_data": ("INPUT", 16), "tx_valid": ("OUTPUT", None),
    "tx_ready": ("INPUT", None), "tx_last": ("OUTPUT", None),
    "tx_data": ("OUTPUT", 16),
}
DECLARATION = re.compile(r"(?m)^\s*(input|output)\s+(?:\[(\d+):0\]\s+)?([^;]+)\s*;")


def adapter_ports(path):
    text = path.read_text()
    module = re.search(r"\bmodule\s+" + ADAPTER + r"\s*\(([^;]+)\);(.*?)\bendmodule\b", text, re.S)
    assert module is not None
    header = [name.strip() for name in module[1].split(",")]
    ports = {}
    for direction, msb, names in DECLARATION.findall(module[2]):
        for name in names.split(","):
            label = name.strip()
            assert label not in ports
            ports[label] = direction.upper(), int(msb) + 1 if msb else None
    assert len(header) == len(set(header)) and set(header) == ports.keys()
    return ports


def width(ports):
    return sum(count or 1 for _, count in ports.values())


def declarations(ports, wires=False):
    for name, (direction, count) in ports.items():
        assert re.fullmatch(r"\w+", name)
        dimensions = f" [{count - 1}:0]" if count is not None else ""
        prefix = "wire" if wires else direction.lower() + " wire"
        yield f"  {prefix}{dimensions} {name}"


def bind(master, instance, ports):
    return f"  {master} {instance} (\n" + ",\n".join(f"    .{name}({name})" for name in ports) + "\n  );\n"


def link(root, mapped, output):
    assert Path("/.dockerenv").is_file()
    record_path = root / BOUNDED_TOKEN_MAP_PLACEMENT
    record = json.loads(record_path.read_text())
    original = root / BOUNDED_STAGE / "native_token_map_buffer_candidate/cold/cold.v"
    assert sha(original) == record["cold_netlist_sha256"]
    core_ports = verilog_ports(original)
    assert {name:core_ports[name] for name in HOST} == HOST
    adapter = adapter_ports(mapped)
    invert = {"INPUT": "OUTPUT", "OUTPUT": "INPUT"}
    expected = PHYSICAL | {"clk": ("INPUT", None), "rst_n": ("INPUT", None)}
    expected.update({name:(invert[direction], size) for name,(direction,size) in HOST.items()})
    assert adapter == expected
    assert not PHYSICAL.keys() & core_ports.keys()
    outer_ports = {name:signal for name,signal in core_ports.items() if name not in HOST} | PHYSICAL
    assert width(core_ports) == record["checked_ports"] == 7945
    assert width(HOST) == 142 and width(PHYSICAL) == 39 and width(outer_ports) == 7842
    with output.open("x") as stream:
        stream.write(f"module {WRAPPER} (\n")
        stream.write(",\n".join(declarations(outer_ports)) + "\n);\n")
        stream.writelines(line+";\n" for line in declarations(HOST,wires=True))
        stream.write(bind(TOP,"accelerator",core_ports))
        stream.write(bind(ADAPTER,"host_link",adapter))
        stream.write("endmodule\n")
    proof = dict(state="mapped_host_link_wrapper_ports_reconciled",
                 cold_netlist_sha256=record["cold_netlist_sha256"], original_signal_bits=width(core_ports),
                 wrapped_signal_bits=width(outer_ports), host_signals_before=width(HOST),
                 host_signals_after=width(PHYSICAL), retained_core_ports=len(core_ports)-len(HOST),
                 evidence_sha256={str(path.relative_to(root)):sha(path)
                                  for path in (mapped,output,record_path,Path(__file__).resolve())})
    receipt = output.with_suffix(".json")
    with receipt.open("x") as stream:
        json.dump(proof,stream,indent=2,sort_keys=True)
        stream.write("\n")
    print("TRI_ORACLE_NARROW_HOST_LINK", proof["original_signal_bits"], proof["wrapped_signal_bits"])


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mapped",type=lambda text:Path(text).resolve())
    parser.add_argument("wrapper",type=lambda text:Path(text).resolve())
    args=parser.parse_args()
    link(Path.cwd(),args.mapped,args.wrapper)
