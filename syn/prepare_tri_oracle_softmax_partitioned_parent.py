"""Prepare the hierarchical synthesis parent with the current softmax cluster interfaces."""

import argparse
import json
from pathlib import Path
import re

from prepare_tri_oracle_wac_outlier_layer import read, sha, verify
from run_tri_oracle_mapped_wac_cluster_replay import FIELDS, PORT, bridge

WRAPPER = re.compile(r"(?m)^module (tri_oracle_native_cluster([0-4])) \(\n(.*?)^\);", re.S)
INCLUDE = re.compile(r'(?m)^`include "([^"]+)"$')


def cluster_contract(header):
    ports = {}
    for direction, _, msb, lsb, name in PORT.findall(header):
        assert name not in ports
        if name in FIELDS:
            assert msb is None or msb == ""
            for field, width in FIELDS[name].items():
                ports[f"{name}[{field}]"] = dict(direction=direction, width=width)
        else:
            assert not msb or int(lsb) == 0
            ports[name] = dict(direction=direction, width=int(msb) + 1 if msb else 1)
    assert len(ports) == 59 and ports["clk"] == dict(direction="input", width=1)
    return ports


def prepare(case, checked_cluster, output):
    setup_path = case / "receipt.json"
    setup = read(setup_path)
    qualification = case / "xcelium/mapped_wac_qualification.json"
    proof = read(qualification)
    assert proof["state"] == "twenty_mapped_compute_cores_replayed_archived_attention"
    assert proof["mapped_compute_cores"] == 20 and proof["compared"]["values"] == 1023
    assert setup["mapped_banks"] == []
    bundle = case / "bundle.sv"
    pins = proof["input_sha256"].copy()
    for path in (setup_path, bundle):
        assert pins[str(path)] == sha(path)
    verify(pins)
    source = bundle.read_text()
    includes = [Path(name) for name in INCLUDE.findall(source)]
    wrappers, = (path for path in includes if path.name == "wrappers.sv")
    wrapper_source = wrappers.read_text()
    wrapper_matches = list(WRAPPER.finditer(wrapper_source))
    assert [int(match[2]) for match in wrapper_matches] == list(range(5))
    interfaces = {match[2]: cluster_contract(match[3]) for match in wrapper_matches}
    counts = {bank: sum(item["width"] for item in ports.values()) for bank, ports in interfaces.items()}
    assert counts == {str(bank): 6329 if bank == 0 else 6201 for bank in range(5)}

    mapping_path = checked_cluster / "receipt.json"
    mapped = read(mapping_path)
    assert mapped["bank"] == 2 and mapped["state"] == "cluster_mapped_around_four_verified_cores"
    netlist = checked_cluster / "netlist.v"
    assert mapped["output_sha256"][netlist.name] == sha(netlist)
    # This compares every shaped field with the actual native output naming.
    bridge(wrapper_matches[2][0], mapped["top"], netlist.read_text())
    for path in (Path(__file__), qualification, mapping_path, netlist):
        pins[str(path)] = sha(path)

    output.mkdir()
    abstracts = output / "cluster_abstracts.sv"
    abstracts.write_text("\n\n".join(match[0] + "\n  // cadence black_box\nendmodule" for match in wrapper_matches) + "\n")
    kept = [path for path in includes if path.suffix == ".sv" and not path.stem.endswith(("_tb", "_probe", "_witness"))
            and path.name != "tri_oracle_sram_compute_cluster.sv"]
    assert wrappers in kept and any(path.name == "cluster_adapter.sv" for path in kept)
    assert any(path.name == "tri_oracle_shared_layer437.sv" for path in kept)
    for path in kept:
        assert pins[str(path)] == sha(path)
    parent = output / "parent_sources.sv"
    parent.write_text("".join(f'`include "{abstracts if path == wrappers else path}"\n' for path in kept))
    for path in (abstracts, parent):
        pins[str(path)] = sha(path)
    verify(pins)
    result = dict(state="current_parent_source_and_five_cluster_cut_contracts_prepared", root="tri_oracle_shared_layer437",
                  validated_against_native_bank=2, ports_by_bank=interfaces, signal_bits_by_bank=counts,
                  total_cluster_signal_bits=sum(counts.values()), input_sha256=pins,
                  scope="Parent synthesis source and cluster cut contracts. Physical netlist assembly and cold connectivity remain pending.")
    with (output / "receipt.json").open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(result["state"], result["total_cluster_signal_bits"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("case", "checked_cluster", "output"):
        parser.add_argument(name, type=lambda value: Path(value).resolve())
    args = parser.parse_args()
    prepare(args.case, args.checked_cluster, args.output)
