"""Check native cluster pins against the compute fabric's declared adapter wiring."""

import argparse
import json
from pathlib import Path
import re

from prepare_tri_oracle_softmax_partitioned_parent import INCLUDE
from prepare_tri_oracle_wac_outlier_layer import read, sha, verify

PACKED_ADAPTER_PORTS = {
    "token_size_bank_command": "bank_command_t",
    "token_size_bank_result": "bank_result_t",
    "merge_range_command": "range_command_t",
    "merge_range_result": "range_result_t",
}
FIELD = re.compile(r"logic\s+(?:\[(\d+):0\]\s+)?(\w+(?:\s*,\s*\w+)*)")
NATIVE_PIN = re.compile(r"clusters\[([0-4])\]\.unit/selected_bank([0-4])\.block_instance")


def bit_names(name, width):
    return [name] if width == 1 else [f"{name}[{bit}]" for bit in range(width)]


def packed_nets(declarations):
    result = {}
    for port, typedef in PACKED_ADAPTER_PORTS.items():
        fields, = re.findall(rf"typedef struct packed\s*\{{([^{{}}]+)\}}\s*{typedef};", declarations)
        layout = []
        for field in fields.strip().removesuffix(";").split(";"):
            declaration = FIELD.fullmatch(field.strip())
            assert declaration, (typedef, field)
            high, names = declaration.groups()
            layout.extend((name.strip(), int(high) + 1 if high is not None else 1) for name in names.split(","))
        result[port] = [bit for name, width in reversed(layout) for bit in bit_names(f"{port}[{name}]", width)]
    return result


def expected_pins(ports_by_bank, packed):
    direction = {"input": "in", "output": "out"}
    expected = {}
    for bank, ports in ports_by_bank.items():
        scope = f"clusters[{bank}].unit"
        owner = f"{scope}/selected_bank{bank}.block_instance"
        for port, spec in ports.items():
            pins = bit_names(port, spec["width"])
            nets = packed.get(port, pins)
            assert len(pins) == len(nets), (bank, port)
            for pin, net in zip(pins, nets, strict=True):
                expected[owner, pin] = direction[spec["direction"]], f"{scope}/{net}"
    return expected


def audit_pin_rows(rows, expected):
    observed = {}
    counts = {}
    for line in rows:
        owner, master, pin, direction, net = line.rstrip("\n").split("\t")
        owner_match = NATIVE_PIN.fullmatch(owner)
        assert owner_match, owner
        bank, selected = owner_match.groups()
        assert selected == bank and master == f"tri_oracle_native_cluster{bank}", (owner, master)
        key = owner, pin
        assert key not in observed, key
        assert expected.get(key) == (direction, net), (key, expected.get(key), (direction, net))
        observed[key] = direction, net
        counts[bank] = counts.get(bank, 0) + 1
    assert observed.keys() == expected.keys(), list(expected.keys() - observed.keys())[:10]
    return counts


def run(preparation, case):
    setup_path = preparation / "receipt.json"
    setup = read(setup_path)
    assert setup["state"] == "current_parent_source_and_five_cluster_cut_contracts_prepared"
    verify(setup["input_sha256"])
    native_path = case / "native_receipt.json"
    native = read(native_path)
    assert native["state"] == "native_exit" and native["native_exit_status"] == 0
    inputs = native["evidence_sha256"].copy()
    verify(inputs)
    assert inputs[str(setup_path)] == sha(setup_path)
    assert (case / "console.log").read_text().splitlines().count("CURRENT_FABRIC_BOUNDARY_ELABORATED") == 1
    source = preparation / "parent_sources.sv"
    assert inputs[str(source)] == setup["input_sha256"][str(source)]
    declarations = []
    for include in map(Path, INCLUDE.findall(source.read_text())):
        content = include.read_text()
        if re.search(r"package tri_oracle_(token_size|merge_range)_types;", content):
            assert setup["input_sha256"][str(include)] == sha(include)
            inputs[str(include)] = sha(include)
            declarations.append(content)
    assert len(declarations) == 2
    expected = expected_pins(setup["ports_by_bank"], packed_nets("\n".join(declarations)))
    ledger = case / "block_pins.tsv"
    with ledger.open() as rows:
        counts = audit_pin_rows(rows, expected)
    assert counts == setup["signal_bits_by_bank"]
    unresolved = case / "unresolved.rpt"
    report = unresolved.read_text()
    assert "No unresolved references in design 'tri_oracle_compute_fabric" in report
    modules = re.findall(r"(?m)^tri_oracle_native_cluster[0-4]$", report)
    assert sorted(modules) == [f"tri_oracle_native_cluster{bank}" for bank in range(5)]
    assert re.findall(r"Total number of empty modules.*?: (\d+)", report) == ["5"]
    for path in (Path(__file__), native_path, ledger, unresolved):
        inputs[str(path)] = sha(path)
    verify(inputs)
    result = dict(state="native_compute_fabric_cluster_adapter_pins_verified", signal_bits_by_bank=counts,
                  total_signal_bits=sum(counts.values()), native_exit_status=native["native_exit_status"],
                  scope="Actual compute-fabric elaboration with five cluster abstracts. Checks adapter-local bit, direction and net bindings.",
                  evidence_sha256=inputs)
    with (case / "receipt.json").open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(result["state"], result["total_signal_bits"], counts, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("preparation", type=lambda value: Path(value).resolve())
    parser.add_argument("native_case", type=lambda value: Path(value).resolve())
    args = parser.parse_args()
    run(args.preparation, args.native_case)
