"""Remap the verified compute core with time reserved for its cluster softmax mux."""

import argparse
from decimal import Decimal
import json
from pathlib import Path
import re

from audit_tri_oracle_mapped_wac_physical_views import setup_report
from prepare_tri_oracle_wac_outlier_layer import read, sha, verify
from replay_mapped_cluster_fixture import shared_memory_stage, wait_for_shared_memory

TOP = "tri_oracle_sram_memory_compute"
TARGET_MHZ = 580
OUTPUT_DELAY_NS = Decimal("0.26")


def with_softmax_budget(recipe):
    original = "set_output_delay 0.2 -clock core_clock [all_outputs]"
    assert recipe.count(original) == 1
    return recipe.replace(original, f"""set probability_ports [get_ports {{softmax_out_probability*}}]
if {{[sizeof_collection $probability_ports] != 16}} {{error "Expected sixteen probability bits"}}
set_output_delay 0.2 -clock core_clock [remove_from_collection [all_outputs] $probability_ports]
set_output_delay {OUTPUT_DELAY_NS} -clock core_clock $probability_ports
puts WAC_SOFTMAX_OUTPUT_BUDGET_CONSTRAINED""")


def run(baseline, cluster, replay, output):
    source_receipt = baseline / "receipt.json"
    source = read(source_receipt)
    assert source["state"] == "mapped_core_preserved_verified_processing_array"
    assert source["native"]["native_exit_status"] == 0
    assert source["native"]["log_sha256"] == sha(baseline / "console.log")
    cluster_timing = cluster / "early_physical_views.json"
    mapped = read(cluster_timing)
    assert mapped["bank"] == 2 and mapped["preplacement_setup"]["worst_path"]["slack_ps"] < 0
    assert mapped["preplacement_setup"]["worst_path"]["endpoint"].startswith("softmax_response[probability]")
    replay_receipt = replay / "xcelium/mapped_cluster_qualification.json"
    result = read(replay_receipt)
    assert result["state"] == "mapped_clusters_replayed_archived_attention_on_twenty_mapped_cores"
    assert result["mapped_banks"] == [2] and result["measured"]["values"] == 1023
    pins = source["input_sha256"].copy()
    for proof in (mapped, result):
        for name, digest in proof["input_sha256"].items():
            assert pins.get(name, digest) == digest, name
            pins[name] = digest
    source_recipe = baseline / "map.tcl"
    assert pins[str(source_recipe)] == sha(source_recipe)
    for path in (Path(__file__), source_receipt, baseline / "console.log", baseline / "after.pe.tsv",
                 baseline / "after.memory.tsv", cluster_timing, replay_receipt):
        digest = sha(path)
        assert pins.get(str(path), digest) == digest, path
        pins[str(path)] = digest
    verify(pins)

    output.mkdir()
    recipe = output / "map.tcl"
    recipe.write_text(with_softmax_budget(source_recipe.read_text()))
    pins[str(recipe)] = sha(recipe)
    (output / "inputs.json").write_text(json.dumps(pins, indent=2) + "\n")
    wait_for_shared_memory("core mapping with cluster softmax timing budget", 17)
    native = shared_memory_stage("core mapping with cluster softmax timing budget", output, [
        "/usr/bin/prlimit", "--as=7516192768", "--", "/opt/cadence/bin/genus", "-batch",
        "-log", str(output / "genus"), "-files", str(recipe),
    ], 2700, 0)
    lines = (output / "console.log").read_text().splitlines()
    assert lines.count("WAC_SOFTMAX_OUTPUT_BUDGET_CONSTRAINED") == lines.count("WAC_MAPPED_PE_CORE_COMPLETE") == 1
    for name in ("pe", "memory"):
        assert (output / f"before.{name}.tsv").read_bytes() == (output / f"after.{name}.tsv").read_bytes()
        assert sha(output / f"after.{name}.tsv") == pins[str(baseline / f"after.{name}.tsv")]
    assert "No unresolved references" in (output / "unresolved_after.rpt").read_text()
    sdc = output / "clock.sdc"
    constrained = re.findall(r"(?m)^set_output_delay[^\n]*\b0\.26\b[^\n]*softmax_out_probability\[(\d+)\]", sdc.read_text())
    assert sorted(map(int, constrained)) == list(range(16)), constrained
    setup = setup_report(output / "timing.rpt", sdc, TOP, TARGET_MHZ)
    verify(pins)
    exports = {name: sha(output / name) for name in (
        "netlist.v", "mapped.db", "clock.sdc", "timing.rpt", "area.rpt", "after.pe.tsv", "after.memory.tsv", "unresolved_after.rpt")}
    report = dict(state="mapped_core_preserved_verified_processing_array", native=native, input_sha256=pins,
                  output_sha256=exports, mapped_pe_cells=54580, memories=28, probability_output_delay_ns=float(OUTPUT_DELAY_NS),
                  preplacement_setup=setup)
    with (output / "receipt.json").open("x") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print("WAC_CORE_SOFTMAX_BUDGET_MEASURED", setup["worst_path"]["slack_ps"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("baseline", "cluster", "replay", "output"):
        parser.add_argument(name, type=lambda value: Path(value).resolve())
    args = parser.parse_args()
    run(args.baseline, args.cluster, args.replay, args.output)
