"""Bind the verified weight-attention core netlist into all twenty layer cores."""

import argparse
from collections import Counter
import json
from pathlib import Path
import re

from prepare_tri_oracle_wac_outlier_layer import ROOT, read, sha, verify
from verify_tri_oracle_wac_core_gate import TOP as CORE

STANDARD_CELLS = ROOT / ".cache/physical/library/tcbn28hpcplusbwp12t40p140.v"
MODULE = re.compile(r"(?m)^\s*module\s+(\w+)\s*(?=\(|#|;)")
WITNESS = f"""module tri_oracle_mapped_wac_witness ();
    initial $display("WAC_MAPPED_COMPUTE_LEAF %m");
endmodule
bind {CORE} tri_oracle_mapped_wac_witness mapped_wac_witness ();
"""


def prepare(source, mapping, gate, output):
    prior_path = source / "xcelium/head_offload_qualification.json"
    prior = read(prior_path)
    assert prior["state"] == "dynamic_head_offload_replayed_on_twenty_core_layer"
    prepared_path = source / "receipt.json"
    prepared = read(prepared_path)
    assert prepared["outlier_owner"] == "core_simd_round_robin" and prepared["mapped_banks"] == []
    assert prior["input_sha256"][str(prepared_path)] == sha(prepared_path)
    mapped_path = mapping / "receipt.json"
    mapped = read(mapped_path)
    assert mapped["state"] == "mapped_core_preserved_verified_processing_array"
    assert mapped["native"]["native_exit_status"] == 0
    assert mapped["native"]["log_sha256"] == sha(mapping / "console.log")
    for name in ("pe", "memory"):
        assert (mapping / f"before.{name}.tsv").read_bytes() == (mapping / f"after.{name}.tsv").read_bytes()
    gate_path = gate / "receipt.json"
    gate_proof = read(gate_path)
    assert gate_proof["state"] == "core_handoff_and_outliers_gate_replayed"
    assert gate_proof["implementation"] == "mapped_core" and gate_proof["compiled_memories"] == 28
    assert gate_proof["native"]["native_exit_status"] == 0
    assert gate_proof["native"]["log_sha256"] == sha(gate / "console.log")
    netlist = mapping / "netlist.v"
    assert gate_proof["input_sha256"][str(netlist)] == sha(netlist)
    inputs = prior["input_sha256"].copy()
    for proof in (mapped, gate_proof):
        for name, digest in proof["input_sha256"].items():
            assert inputs.get(name, digest) == digest, name
            inputs[name] = digest
    verify(inputs)

    native_modules = Counter(MODULE.findall(netlist.read_text()))
    assert native_modules[CORE] == native_modules["tri_oracle_pe_array"] == 1
    original = source / "bundle.sv"
    assert inputs[str(original)] == sha(original)
    replaced = set()

    def replace_leaf(match):
        path = Path(match[1])
        assert inputs[str(path)] == sha(path)
        definitions = set(MODULE.findall(path.read_text()))
        overlap = definitions & native_modules.keys()
        if not overlap:
            return match[0]
        assert overlap == definitions, (path, overlap, definitions)
        replaced.update(overlap)
        if CORE in overlap:
            return f'`include "{STANDARD_CELLS}"\n`include "{netlist}"'
        return ""

    body = re.sub(r'(?m)^`include "([^"]+)"$', replace_leaf, original.read_text())
    assert {CORE, "tri_oracle_pe_array", "tri_oracle_wac_softmax"} <= replaced, replaced
    output.mkdir()
    bundle = output / "bundle.sv"
    witness = output / "mapped_wac_witness.sv"
    witness.write_text(WITNESS)
    bundle.write_text(body + f'`include "{witness}"\n')
    paths = (Path(__file__), prior_path, mapped_path, gate_path, bundle, witness, STANDARD_CELLS, netlist,
             mapping / "unresolved_after.rpt", mapping / "timing.rpt", mapping / "area.rpt")
    inputs.update({str(path): sha(path) for path in paths})
    verify(inputs)
    prepared.update(bundle=str(bundle), input_sha256=inputs, mapped_core_netlist=str(netlist),
                    mapped_compute_leaf_count=20, replaced_source_modules=sorted(replaced))
    (output / "receipt.json").write_text(json.dumps(prepared, indent=2) + "\n")
    print("Prepared twenty mapped compute leaves with source cluster controllers.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "mapping", "gate", "output"):
        parser.add_argument(name, type=lambda value: Path(value).resolve())
    prepare(**vars(parser.parse_args()))
