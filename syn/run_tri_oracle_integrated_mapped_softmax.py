"""Replay mapped softmax banks in all five clusters with shared vendor memories."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

from run_tri_oracle_softmax_iomem import ROOT, RTL, replace, sha
from verify_tri_oracle_packed_softmax_mapping import STANDARD_MODELS, XRUN, port_signature

PARENT = ROOT / ".cache/physical/shared437/aggregator_local_merge/cluster_native/partitioned_parent"
REPLAY = PARENT.parent / "replay_mapped_cluster_fixture.py"
OWNER_AUDIT = PARENT / "verify_shared_softmax_iomem.py"


def read(path):
    return json.loads(path.read_text())


def verify(inputs):
    for name, digest in inputs.items():
        assert sha(Path(name)) == digest, f"Changed replay input {name}"


def prepare(source, mapping, mapped_replay, output):
    prior_path = source / "xcelium/shared_iomem_qualification.json"
    prior = read(prior_path)
    assert prior["state"] == "cluster_softmax_shared_vendor_iomem_passed_integrated_xcelium"
    prepared_path = source / "receipt.json"
    prepared = read(prepared_path)
    assert prepared["bundle"] == str(source / "bundle.sv")
    assert prepared["mapped_banks"] == [] and prepared["memory_models"] == "vendor"
    assert prior["replay"]["native_exit_status"] == 0
    assert prior["input_sha256"][str(prepared_path)] == sha(prepared_path)
    mapped_proof_path = mapped_replay / "receipt.json"
    mapped_proof = read(mapped_proof_path)
    assert mapped_proof["state"] == "packed_softmax_mapped_bank_and_vendor_memories_verified"
    assert mapped_proof["simulator"] == "Cadence Xcelium" and mapped_proof["compared_probability_codes"] == 12915
    assert mapped_proof["native_log_sha256"] == sha(mapped_replay / "xrun.log")
    netlist = mapping / "netlist.v"
    assert mapped_proof["input_sha256"][str(netlist)] == sha(netlist)
    assert port_signature(netlist.read_text()) == mapped_proof["checked_bank_signal_bits"] == 810
    inputs = prior["input_sha256"].copy()
    for name, digest in mapped_proof["input_sha256"].items():
        assert name not in inputs or inputs[name] == digest
        inputs[name] = digest
    verify(inputs)

    def include(path):
        return f'`include "{path}"'

    old_cluster = source / "tri_oracle_sram_compute_cluster.sv"
    cluster = output / old_cluster.name
    words = ",\n    ".join(rf".\memory_q[{word}] (aggregate_q[{128 * word}+:128])" for word in range(4))
    cluster_text = replace(old_cluster.read_text(), ".memory_q(aggregate_q[511:0])", words)
    bundle = output / "bundle.sv"
    body = (source / "bundle.sv").read_text()
    body = replace(body, include(RTL / "tri_oracle_softmax_iomem.sv"), include(STANDARD_MODELS))
    body = replace(body, include(source / "tri_oracle_softmax_iomem_bank.sv"), include(netlist))
    body = replace(body, include(old_cluster), include(cluster))
    output.mkdir()
    cluster.write_text(cluster_text)
    bundle.write_text(body)
    inputs.update({str(path): sha(path) for path in (
        prior_path, mapped_proof_path, mapped_replay / "xrun.log", bundle, cluster,
        Path(__file__), REPLAY, OWNER_AUDIT, XRUN,
    )})
    prepared.update(bundle=str(bundle), input_sha256=inputs, mapped_softmax_netlist=str(netlist))
    (output / "receipt.json").write_text(json.dumps(prepared, indent=2) + "\n")
    return prior, inputs


def run(source, mapping, mapped_replay, output):
    prior, inputs = prepare(source, mapping, mapped_replay, output)
    result_dir = output / "xcelium"
    try:
        subprocess.run([sys.executable, "-B", str(REPLAY), str(output), "--shared-memory"], check=True)
        subprocess.run([sys.executable, "-B", str(OWNER_AUDIT), str(output)], check=True)
    finally:
        snapshot = result_dir / "xcelium.d"
        if snapshot.is_dir():
            shutil.rmtree(snapshot)
    audited_path = result_dir / "shared_iomem_qualification.json"
    audited = read(audited_path)
    verify(inputs)
    for key in ("native_hierarchy", "measured", "bank_activity", "memory_owner_activity",
                "rows_lengths", "memory_instances_by_type", "compiled_memory_bytes"):
        assert audited[key] == prior[key], (key, audited[key], prior[key])
    evidence = dict(state="five_mapped_softmax_banks_passed_integrated_xcelium",
                    mapped_softmax_banks=5, simulator="Cadence Xcelium",
                    qualification_sha256=sha(audited_path), measured=audited["measured"],
                    compiled_memory_bytes=audited["compiled_memory_bytes"], replay=audited["replay"],
                    scope="Mapped softmax banks integrated into source clusters with unit-delay compiled memories.")
    (result_dir / "mapped_softmax_qualification.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(evidence["state"], evidence["measured"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "mapping", "mapped_replay", "output"):
        parser.add_argument(name, type=lambda value: Path(value).resolve())
    run(**vars(parser.parse_args()))
