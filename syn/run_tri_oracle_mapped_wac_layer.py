"""Check archived attention on twenty mapped compute cores."""

import argparse
import json
from pathlib import Path
import re

from prepare_tri_oracle_mapped_wac_layer import CORE, MODULE, read, sha, verify
from replay_mapped_cluster_fixture import BENCH
from run_tri_oracle_head_offload_layer import run as run_attention

LEAF = re.compile(
    rf"WAC_MAPPED_COMPUTE_LEAF {BENCH}\.dut\.feedforward\.compute\.compute\.tensor\.fabric"
    r"\.clusters\[([0-4])\]\.unit\.selected_bank([0-4])\.block_instance"
    r"\.source_cluster\.implementation\.cores\[([0-3])\]\.compute\.mapped_wac_witness"
)


def run(case):
    setup_path = case / "receipt.json"
    setup = read(setup_path)
    assert setup["mapped_compute_leaf_count"] == 20 and setup["mapped_banks"] == []
    identities = setup["input_sha256"].copy()
    verify(identities)
    bundle = case / "bundle.sv"
    assert setup["bundle"] == str(bundle) and identities[str(bundle)] == sha(bundle)
    includes = [Path(path) for path in re.findall(r'(?m)^`include "([^"]+)"$', bundle.read_text())]
    definitions = [path for path in includes if CORE in MODULE.findall(path.read_text())]
    assert definitions == [Path(setup["mapped_core_netlist"])], definitions
    identities.update({str(path): sha(path) for path in (Path(__file__), setup_path)})
    run_attention(case)
    qualification_path = case / "xcelium/head_offload_qualification.json"
    result = read(qualification_path)
    assert result["state"] == "dynamic_head_offload_replayed_on_twenty_core_layer"
    console = case / "xcelium/positive/console.log"
    assert result["input_sha256"][str(console)] == sha(console)
    observed = []
    with console.open() as stream:
        for line in stream:
            if line.startswith("WAC_MAPPED_COMPUTE_LEAF "):
                match = LEAF.fullmatch(line.rstrip("\n"))
                assert match, line
                observed.append(tuple(map(int, match.groups())))
    assert sorted(observed) == [(cluster, cluster, core) for cluster in range(5) for core in range(4)], observed
    identities.update({str(path): sha(path) for path in (qualification_path, console)})
    verify(identities)
    output = case / "xcelium/mapped_wac_qualification.json"
    output.write_text(json.dumps(dict(state="twenty_mapped_compute_cores_replayed_archived_attention",
        mapped_compute_cores=20, compared=result["compared"], replay_seconds=result["replay_seconds"],
        input_sha256=identities, scope="Source cluster controllers and mapped compute cores with vendor unit-delay memory models."), indent=2) + "\n")
    print("Twenty mapped compute cores reproduced the four archived attention outputs.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", type=Path)
    args = parser.parse_args()
    run(args.case.resolve())
