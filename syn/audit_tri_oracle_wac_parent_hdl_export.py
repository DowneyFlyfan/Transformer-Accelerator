"""Compare exported parent cluster connections with the cold Genus database."""

import argparse
import json
from pathlib import Path
import re

from audit_second_cluster_innovus_nets import expand_bits, resolve_bits
from prepare_mapped_cluster_fixture import MODULE
from prepare_tri_oracle_wac_outlier_layer import read, sha, verify
from run_tri_oracle_wac_layer_parent import CLUSTER_ROOT, pin_map

SUFFIX = "_budgeted_parent"
IDENTIFIER = r"(?:\\\S+|[A-Za-z_$][\w$]*)"
DECLARATION = re.compile(r"(?m)^\s*(input|output|wire)\s+(?:\[(\d+):(\d+)\]\s*)?([^;]+);")
ASSOCIATION = re.compile(rf"\.({IDENTIFIER})\s*\(([^()]*)\)")


def declarations(source):
    ports, nets = {}, {}
    for direction, first, last, names in DECLARATION.findall(source):
        span = None if first == "" else (int(first), int(last))
        for name in names.split(","):
            name = name.strip()
            assert re.fullmatch(IDENTIFIER, name), name
            key = name.removeprefix("\\")
            assert nets.get(key, span) == span, key
            nets[key] = span
            if direction != "wire":
                assert key not in ports, key
                ports[key] = direction, span
    return ports, nets


def audit_connections(wrapper, fields, ports, expected_nets):
    _, nets = declarations(wrapper)
    pairs = [(pin.removeprefix("\\"), expression.strip()) for pin, expression in ASSOCIATION.findall(fields)]
    assert not ASSOCIATION.sub("", fields).strip(" ,\t\n")
    assert len(pairs) == len(ports) and {pin for pin, _ in pairs} == ports.keys()
    observed = {}
    for pin, expression in pairs:
        _, span = ports[pin]
        observed.update(zip(expand_bits(pin, span), resolve_bits(expression, nets), strict=True))
    assert observed.keys() == expected_nets.keys()
    for pin, net in observed.items():
        assert net == expected_nets[pin], (pin, net, expected_nets[pin])
    return len(observed)


def audit_export(text, cold_rows, cold_top_ports, netlist, mapped_bank):
    modules = {}
    for module in MODULE.finditer(text):
        if module[1].endswith(SUFFIX):
            assert module[1] not in modules, module[1]
            modules[module[1]] = module
    top, = (name for name in modules if name.startswith("tri_oracle_shared_layer437"))
    direction_names = {"input": "in", "output": "out"}
    top_ports, _ = declarations(modules[top][0])
    exported_top_bits = {(pin, direction_names[direction]) for name, (direction, span) in top_ports.items()
                         for pin in expand_bits(name, span)}
    assert len(exported_top_bits) == len(cold_top_ports) and exported_top_bits == set(cold_top_ports)
    checked = {}
    for bank in range(5):
        original = f"tri_oracle_native_cluster{bank}"
        abstract = original + SUFFIX
        stub = modules[abstract][0]
        tail = stub.partition(");")[2]
        assert DECLARATION.sub("", tail).strip() == "endmodule", abstract
        ports, _ = declarations(stub)
        expected = {}
        prefix = f"clusters[{bank}].unit/"
        for (owner, pin), (master, direction, net) in cold_rows.items():
            if master == original:
                assert owner == prefix + f"selected_bank{bank}.block_instance"
                assert net.startswith(prefix)
                expected[pin] = direction, net.removeprefix(prefix)
        expected_directions = {pin: direction_names[direction] for name, (direction, span) in ports.items()
                               for pin in expand_bits(name, span)}
        assert expected_directions == {pin: direction for pin, (direction, _) in expected.items()}, bank
        instance, = re.finditer(rf"(?m)^\s*{abstract}\s+({IDENTIFIER})\s*\((\s*\..*?)\);", text, re.S)
        assert instance[1].removeprefix("\\") == f"selected_bank{bank}.block_instance"
        wrapper, = (module for module in modules.values() if module.start() < instance.start() < module.end())
        expected_nets = {pin: net for pin, (_, net) in expected.items()}
        checked[str(bank)] = audit_connections(wrapper[0], instance[2], ports, expected_nets)
        if bank == mapped_bank:
            gate_top, = (module for module in MODULE.finditer(netlist) if module[1] == original)
            assert declarations(gate_top[0])[0] == ports
    assert sum(checked.values()) == len(cold_rows) == 31133
    return top, len(exported_top_bits), checked


def run(export, cold, mapping):
    native_path = export / "native_receipt.json"
    cold_path = cold / "receipt.json"
    mapping_path = mapping / "receipt.json"
    native, parent, cluster = map(read, (native_path, cold_path, mapping_path))
    assert native["state"] == "native_exit" and native["native_exit_status"] == 0
    assert parent["state"] == "current_layer_parent_cold_reload_preserved_verified_cluster_connections"
    assert cluster["state"] == "cluster_mapped_around_four_verified_cores"
    assert cluster["native"]["native_exit_status"] == 0
    verify(native["evidence_sha256"])
    verify(parent["input_sha256"])
    assert native["evidence_sha256"][str(cold_path)] == sha(cold_path)
    ledger = cold / "block_pins.tsv"
    top_ports = cold / "ports.tsv"
    netlist = mapping / "netlist.v"
    assert sha(ledger) == parent["output_sha256"][ledger.name]
    assert sha(top_ports) == parent["output_sha256"][top_ports.name]
    assert sha(netlist) == cluster["output_sha256"][netlist.name]
    hdl = export / "parent.v"
    cold_top_ports = [tuple(line.split()) for line in top_ports.read_text().splitlines()]
    top, top_bits, banks = audit_export(hdl.read_text(), pin_map(ledger, CLUSTER_ROOT), cold_top_ports,
                                        netlist.read_text(), cluster["bank"])
    inputs = {str(path): sha(path) for path in (
        Path(__file__), native_path, cold_path, mapping_path, hdl, ledger, top_ports, netlist,
        Path(resolve_bits.__code__.co_filename), Path(pin_map.__code__.co_filename))}
    verify(inputs)
    result = dict(state="native_layer_parent_hdl_cut_and_bank_port_signatures_verified", top=top, top_port_bits=top_bits,
                  verified_signal_bits_by_bank=banks, verified_signal_bits=sum(banks.values()),
                  compared_mapped_bank=cluster["bank"], evidence_sha256=inputs,
                  scope="Verilog interfaces and named connections from an elaborated checkpoint.")
    with (export / "receipt.json").open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(result["state"], banks, cluster["bank"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("export", "cold", "mapping"):
        parser.add_argument(name, type=lambda value: Path(value).resolve())
    run(**vars(parser.parse_args()))
