"""Elaborate and verify the current Tri-Oracle layer parent around five cluster cuts."""

import argparse
import json
import math
import os
from pathlib import Path
import re
import time

from prepare_tri_oracle_softmax_partitioned_parent import INCLUDE
from prepare_tri_oracle_wac_outlier_layer import read, sha, verify
from replay_mapped_cluster_fixture import shared_memory_stage, wait_for_shared_memory

TOP = "tri_oracle_shared_layer437"
CLUSTER_ROOT = "feedforward/compute/compute/tensor/fabric/"
SRAM = "TS5N28HPCPSVTA512X64M4F"
METADATA = {f"feedforward/predictor/replay_table/{bank}_metadata {SRAM}" for bank in ("lower", "upper")}
MARKER = "TRI_ORACLE_PARTITIONED_PARENT_ELABORATED"


def live_pid_identity(pid):
    try:
        data = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    except FileNotFoundError:
        return None
    return None if data[0] == "Z" else data[19]


def pin_map(path, prefix=""):
    pins = {}
    for row in path.read_text().splitlines():
        owner, master, pin, direction, net = row.split("\t")
        assert owner.startswith(prefix) and net.startswith(prefix), row
        key = owner.removeprefix(prefix), pin
        assert key not in pins, key
        pins[key] = master, direction, net.removeprefix(prefix)
    return pins


def audit(case, setup, fabric, previous, old_ports, sources):
    source, = (file for file in sources if file.name == f"{TOP}.sv")
    old_source, = (Path(path) for path in previous["input_sha256"] if path.endswith(f"/{TOP}.sv"))
    assert previous["input_sha256"][str(old_source)] == sha(old_source)
    assert source.read_text().split("\n);", 1)[0] == old_source.read_text().split("\n);", 1)[0]
    ports = (case / "ports.tsv").read_text().splitlines()
    assert len(ports) == len(set(ports)) == previous["observed"]["top_port_bits"]
    assert sha(old_ports) == previous["output_sha256"]["ports.tsv"]
    assert set(ports) == set(old_ports.read_text().splitlines())

    expected = pin_map(fabric / "block_pins.tsv")
    observed = pin_map(case / "block_pins.tsv", CLUSTER_ROOT)
    assert len(observed) == len(expected) == setup["total_cluster_signal_bits"]
    assert observed == expected, [(key, value, observed.get(key)) for key, value in expected.items()
                                  if observed.get(key) != value][:10]
    memories = (case / "memories.tsv").read_text().splitlines()
    assert len(memories) == 2 and set(memories) == METADATA
    report = (case / "unresolved.rpt").read_text()
    assert f"No unresolved references in design '{TOP}" in report
    empty = re.findall(r"(?m)^tri_oracle_native_cluster[0-4]$", report)
    assert sorted(empty) == [f"tri_oracle_native_cluster{bank}" for bank in range(5)]
    assert re.findall(r"Total number of empty modules.*?: (\d+)", report) == ["5"]
    period, = re.findall(r'(?m)^create_clock -name "core_clock" -period ([\d.]+).*\[get_ports clk\]',
                         (case / "clock.sdc").read_text())
    assert math.isclose(float(period), 1000 / 580, abs_tol=0.000005)
    return dict(top_port_bits=len(ports), cluster_signal_bits=len(observed), direct_parent_memory_macros=len(memories),
                clock_period_ns=float(period))


def run(preparation, fabric, previous, template, case, wait_pid):
    setup_path, fabric_path = preparation / "receipt.json", fabric / "receipt.json"
    setup, proof, old = read(setup_path), read(fabric_path), read(previous)
    old_ports = previous.parent / "ports.tsv"
    assert old["state"] == "full_layer_parent_elaborates_with_verified_cluster_boundaries"
    assert old["output_sha256"]["ports.tsv"] == sha(old_ports)
    assert proof["state"] == "native_compute_fabric_cluster_adapter_pins_verified"
    assert setup["state"] == "current_parent_source_and_five_cluster_cut_contracts_prepared"
    assert proof["evidence_sha256"][str(setup_path)] == sha(setup_path)
    verify(setup["input_sha256"])
    verify(proof["evidence_sha256"])

    source = preparation / "parent_sources.sv"
    sources = [Path(path) for path in INCLUDE.findall(source.read_text())]
    text = template.read_text()
    libraries = re.findall(r"\{([^{}]+\.lib)\}", text)
    assert len(libraries) == 7
    standard, metadata, *_ = map(Path, libraries)
    assert setup["input_sha256"][str(standard)] == sha(standard)
    assert metadata.name == "ts5n28hpcpsvta512x64m4f_130a_ssg0p9v125c.lib"
    text = re.sub(r"(?m)^read_libs .*$", f"read_libs [list {{{standard}}} {{{metadata}}}]", text, count=1)
    text = text.replace("set_db fail_on_error_mesg true\n", "set_db fail_on_error_mesg true\n"
                        "set_db message:ELABUTL/ELABUTL-123 .severity Error\n"
                        "set_db message:ELABUTL/ELABUTL-124 .severity Error\n", 1)
    assert os.environ.get("CDS_LIC_FILE"), "Run inside the configured Cadence container environment"
    if wait_pid:
        identity = live_pid_identity(wait_pid)
        print("Waiting for cluster supervisor", wait_pid, identity, flush=True)
        while identity is not None and live_pid_identity(wait_pid) == identity:
            time.sleep(5)
    verify(setup["input_sha256"])
    verify(proof["evidence_sha256"])
    case.mkdir()
    script = case / "elaborate.tcl"
    script.write_text(text)
    inputs = dict(proof["evidence_sha256"])
    inputs.update({str(path): sha(path) for path in (Path(__file__), setup_path, fabric_path, previous, old_ports,
                                                   template, script, standard, metadata, source, *sources)})
    os.environ["TRI_ORACLE_PARTITIONED_PARENT_SOURCE"] = str(source)
    wait_for_shared_memory("full layer parent elaboration", 17)
    native = shared_memory_stage("full layer parent elaboration", case, [
        "/usr/bin/prlimit", "--as=5368709120", "--", "/opt/cadence/bin/genus", "-batch", "-files", str(script)
    ], 360, 0)
    assert (case / "console.log").read_text().splitlines().count(MARKER) == 1
    observed = audit(case, setup, fabric, old, old_ports, sources)
    verify(inputs)
    verify(setup["input_sha256"])
    outputs = ("elaborated.db", "block_pins.tsv", "memories.tsv", "ports.tsv", "unresolved.rpt", "clock.sdc")
    result = dict(state="full_layer_parent_elaborated_with_verified_cluster_cuts", observed=observed,
                  native=native, input_sha256=inputs, output_sha256={name: sha(case / name) for name in outputs},
                  scope="Full layer parent with cluster interfaces. Linkage of mapped clusters and timing qualification remain pending.")
    (case / "receipt.json").write_text(json.dumps(result, indent=2) + "\n")
    print(result["state"], observed, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("preparation", "fabric", "previous", "template", "case"):
        parser.add_argument(name, type=lambda value: Path(value).resolve())
    parser.add_argument("--wait-pid", type=int)
    run(**vars(parser.parse_args()))
