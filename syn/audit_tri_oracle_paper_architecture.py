"""Bind the reproduced layer architecture and its chip integration gaps to native evidence."""

import argparse
import json
from pathlib import Path
import re

from check_tri_oracle_paper300_gate import PAPER_RELATIVE, PAPER_SHA256
from prepare_tri_oracle_wac_outlier_layer import ROOT, read, sha, verify
from run_tri_oracle_head_offload_layer import routes
from run_tri_oracle_mapped_wac_cluster_replay import normalize
from run_tri_oracle_mapped_wac_layer import LEAF
from run_separate_cores_fixture_export_at_reserve import genus_ports

EXTERNAL_PORTS = {
    "clock_and_reset": {"clk": "input", "rst_n": "input"},
    "layer_dispatch": {"cfg_valid": "input", "projection_valid": "input", "frame_valid": "input",
                       "head_valid": "input", "row_valid": "input"},
    "normalization_stream": {"stats_data": "input", "replay_data": "input", "replay_gamma": "input"},
    "memory_transport": {"req_address": "output", "rsp_data": "input", "wr_address": "output",
                         "wr_rsp_valid": "input", "cache_write_address": "output", "value_rsp_data": "input"},
}


def port_directions(source):
    header, _, _ = source.partition("\n);")
    assert header and len(header) < len(source)
    ports = {}
    declarations = r"(?m)^\s*(input|output)\s+logic\s+(?:signed\s+)?(?:\[[^\]]+\]\s+)?([^\n]+)"
    for direction, names in re.findall(declarations, header):
        for name in names.rstrip(",").split(","):
            name = name.strip()
            assert re.fullmatch(r"\w+", name) and name not in ports, name
            ports[name] = direction
    return ports


def audit(case):
    setup_path = case / "receipt.json"
    qualified_path = case / "xcelium/mapped_cluster_qualification.json"
    raw_path = case / "xcelium/receipt.json"
    log = case / "xcelium/positive/console.log"
    setup, qualified, raw = (read(path) for path in (setup_path, qualified_path, raw_path))
    assert qualified["state"] == "mapped_clusters_replayed_archived_attention_on_twenty_mapped_cores"
    assert qualified["mapped_compute_cores"] == 20 and qualified["compiled_memories"] == 623
    assert raw["elaboration"]["native_exit_status"] == raw["replay"]["native_exit_status"] == 0
    pins = qualified["input_sha256"].copy()
    for path in (setup_path, raw_path, log):
        assert pins[str(path)] == sha(path)
    assert raw["replay"]["log_sha256"] == sha(log)
    verify(pins)
    bundle = Path(setup["bundle"])
    assert bundle == case / "bundle.sv" and pins[str(bundle)] == sha(bundle)
    includes = [Path(name) for name in re.findall(r'(?m)^`include "([^"]+)"$', bundle.read_text())]
    assert all(pins[str(path)] == sha(path) for path in includes)
    top, = (path for path in includes if path.name == "tri_oracle_shared_layer437.sv")
    bench, = (path for path in includes if path.name == "attention_tb.sv")
    root = top.read_text()
    bench_text = bench.read_text()
    assert "module tri_oracle_shared_layer437 #(" in root
    assert re.search(r"tri_oracle_batched_learned437\s+#\(.*?\) feedforward\s*\(", root, re.S)
    assert re.search(r"tri_oracle_attention_pipeline430\s+#\(.*?\) attention_pipeline\s*\(", root, re.S)
    assert "tri_oracle_shared_layer437 #(.COMPILED_SIGN_BANK(1), .LOCAL_TOKEN_SIZES(1), .LOCAL_TOKEN_MERGE(1)) dut (" in bench_text
    assert re.search(r"always\s+#\d+\s+clk\s*=\s*~clk", bench_text)
    assert re.search(r"wire\s+rsp_valid\s*=\s*reading", bench_text)
    ports = port_directions(root)
    for service in EXTERNAL_PORTS.values():
        assert all(ports[name] == direction for name, direction in service.items())

    paper = ROOT / PAPER_RELATIVE
    targets_path = ROOT / "records/paper_result_targets.json"
    assert sha(paper) == PAPER_SHA256 and read(targets_path)["source"] == PAPER_RELATIVE
    targets = read(targets_path)
    source = ROOT / "verilog/tri_oracle_pe_array.sv"
    mapped_core = Path(setup["mapped_core_netlist"])
    assert all(pins[str(path)] == sha(path) for path in (source, mapped_core))
    params = {name: int(value) for name, value in re.findall(r"parameter integer (LINES|LANES|DATA_W)=(\d+)", source.read_text())}
    assert [params["LINES"], params["LANES"]] == targets["silicon"]["processing_element_array_per_core"]
    assert params["DATA_W"] == 8
    with mapped_core.open() as stream:
        pe = genus_ports(stream, "tri_oracle_pe_array")
    lanes = params["LINES"] * params["LANES"]
    assert pe["lane_enable"] == ("input", (lanes - 1, 0))
    assert pe["operand_a"] == pe["operand_b"] == ("input", (lanes * params["DATA_W"] - 1, 0))
    lines = [normalize(line) for line in log.read_text().splitlines()]
    leaves = [LEAF.fullmatch(line) for line in lines if line.startswith("WAC_MAPPED_COMPUTE_LEAF ")]
    assert len(leaves) == 20 and all(leaves)
    assert sorted(tuple(map(int, match.groups())) for match in leaves) == [(bank, bank, core)
                                                                          for bank in range(5) for core in range(4)]
    measured = qualified["measured"]
    assert measured == raw["measured"] and measured["maps"] == 576
    routes(lines, (2, 0), measured["rows"], measured["values"])
    pins.update({str(path): sha(path) for path in (Path(__file__), qualified_path, targets_path, paper)})
    verify(pins)
    return dict(state="native_layer_architecture_verified_chip_integration_unqualified",
        simulated_device_root="tri_oracle_shared_layer437", fully_mapped_cluster_banks=qualified["mapped_banks"],
        clusters=5, cores_per_cluster=4, processing_element_geometry=[params["LINES"], params["LANES"]],
        signed_operand_bits=params["DATA_W"], mapped_compute_cores=len(leaves), compiled_memories=623,
        archived_attention=measured, externally_supplied_services=EXTERNAL_PORTS,
        paper_chip_services_pending=["top controller", "all-digital phase-locked loop", "chip-level network and external memory integration"],
        whole_chip_architecture_verified=False, input_sha256=pins)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", type=lambda value: Path(value).resolve())
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = audit(args.case)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(result["state"], result["mapped_compute_cores"], result["paper_chip_services_pending"], flush=True)
