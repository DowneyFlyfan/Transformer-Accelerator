"""Replay host commands and attention on the exact assembled chip netlist."""

import argparse
import json
from pathlib import Path
import re
import shutil
import sys

from check_tri_oracle_paper300_gate import sha


ROOT = Path(__file__).resolve().parents[1]
PHYSICAL = ROOT / ".cache/physical"
SHARED = PHYSICAL / "context_external/shared_decoder"
TOP = "tri_oracle_attention430_tb"
MACRO_LINE = re.compile(r"(?m)^TRI_ORACLE_MAPPED_CENSUS TS[56]N28[^\n]+$")


def read(path):
    return json.loads(path.read_text())


def verify(pins):
    for name, expected in pins.items():
        assert sha(name) == expected, name


def run(output):
    for directory in (
        "shared_memory_layer_boundary", "shared437/aggregator_local_merge/cluster_native",
        "wac_budgeted_parent_boundary", "wac_budgeted_parent_boundary/compact_load_transport",
        "context_external/shared_decoder", "external_read_mux", "external_write_mux",
    ):
        sys.path.append(str(PHYSICAL / directory))
    import replay_fully_mapped_layer as native

    assembly = SHARED / "mapped_context_chip"
    chip = assembly / "chip.v"
    handoff_path = SHARED / "mapped_context_chip_physical_inputs/handoff.json"
    handoff = read(handoff_path)
    assert handoff["state"] == "verified_gate_replays_and_static_chip_inputs_ready"
    verify(handoff["evidence_sha256"])
    assert sha(chip) == handoff["chip_netlist_sha256"]
    mapped = SHARED / "chip_command_context_mapped"
    mapped_receipt = mapped / "receipt.json"
    prior = read(mapped_receipt)
    assert prior["state"] == "mapped_chip_controller_restored_context_on_corrected_gate_decoder"
    assert prior["smoke"]["native_exit_status"] == 0
    assert prior["decoder_netlist_sha256"] == handoff["decoder_netlist_sha256"]
    verify(prior["input_sha256"])

    full_source = SHARED / "chip_command_context_full_source"
    reference_path = full_source / "receipt.json"
    reference = read(reference_path)
    reference_log = full_source / "replay/xrun.log"
    assert reference["state"] == "mapped_chip_controller_passed_full_source_context_attention_replay"
    assert reference["replay"]["native_exit_status"] == 0 and sha(reference_log) == reference["replay"]["log_sha256"]
    assert reference["controller_sha256"] == prior["controller_sha256"]
    verify(reference["input_sha256"])
    fixture, = set(re.findall(r"(?m)^\s*\+FIXTURE=(\S+)$", reference_log.read_text()))
    fixtures = tuple(Path(fixture) / name for name in (
        "activation.hex", "weights.hex", "cos.hex", "sin.hex", "shifts.hex", "biases.hex", "expected.hex",
        "seed_0.hex", "seed_1.hex", "seed_2.hex", "map.hex", "signs.hex", "rows.txt",
    ))

    bundle_path = mapped / "bundle.sv"
    smoke = mapped / "smoke/xrun.log"
    assert prior["input_sha256"][str(bundle_path)] == sha(bundle_path)
    assert prior["smoke"]["log_sha256"] == sha(smoke)
    original = re.findall(r'(?m)^`include "([^"]+)"$', bundle_path.read_text())
    decoder = str(SHARED / "linked_context_decoder_complete_attention/candidate.v")
    separate = {
        str(PHYSICAL / "chip_dispatch/mapped_flat/netlist.v"),
        str(SHARED / "chip_command_context_source/tri_oracle_chip_command_layer.sv"),
    }
    assert len(original) == len(set(original)) and {decoder, *separate} <= set(original)
    includes = [str(chip) if path == decoder else path for path in original if path not in separate]
    topology_path = ROOT / "records/wac_mapped_paper_topology_result.json"
    topology = read(topology_path)
    assert topology["candidate_netlist_sha256"] == prior["decoder_netlist_sha256"]
    prior_hashes = prior["input_sha256"] | topology["input_sha256"]
    assert all(sha(path) == prior_hashes[path] for path in includes if path != str(chip))
    assert shutil.disk_usage(output.parent).free >= 15 * 2**30
    output.mkdir()
    bundle = output / "bundle.sv"
    bundle.write_text("`define UNIT_DELAY\n" + "".join(f'`include "{path}"\n' for path in includes))
    pins = {str(path): sha(path) for path in (Path(__file__), handoff_path, mapped_receipt, bundle_path, smoke,
                                             reference_path, reference_log, topology_path, bundle, *includes, *fixtures)}
    assert pins[str(chip)] == handoff["chip_netlist_sha256"]
    native.OUTPUT = output
    snapshot = output / "xcelium.d"
    command = ["/opt/cadence/bin/xrun", "-64bit", "-xmlibdirname", str(snapshot), "-notimingchecks"]
    try:
        elaborate, compile_proof = native.stage("elaborate", [
            *command, "-sv", "-nospecify", "-sequdp_nba_delay", "-xmerror", "RECOME", "-elaborate",
            "-top", TOP, "-defparam", f"{TOP}.INTEGRATE=1", str(bundle),
        ], 16.5, 13, 8, 900)
        assert f"Writing initial simulation snapshot: worklib.{TOP}:sv" in elaborate.read_text()
        log, replay = native.stage("replay", [
            *command, "-R", f"+FIXTURE={fixture}", f"+DUMP={output/'unused.hex'}",
        ], 16, 13, 6, 1800)
        content = log.read_text()
        assert f"Loading snapshot worklib.{TOP}:sv" in content
        assert all(content.splitlines().count(line) == 1 for line in reference["markers"])
        assert content.count("Simulation complete via $finish(1)") == 1
        assert "Exiting on " in content.splitlines()[-1]
        marker, = re.findall(r"(?m)^COMPOSE430_PASS (.+)$", content)
        counters = {key: int(value) for key, value in (field.split("=") for field in marker.split())}
        assert counters.keys() == reference["counters"].keys()
        assert all(value == reference["counters"][key] for key, value in counters.items() if key != "stalls")
        macros = MACRO_LINE.findall(content)
        assert len(macros) == len(set(macros)) == prior["compiled_memory_instances"]
        assert set(macros) == set(MACRO_LINE.findall(smoke.read_text()))
        verify(pins)
        pins.update({str(path): sha(path) for path in (elaborate, log)})
        result = {
            "state": "assembled_mapped_context_chip_passed_full_command_attention_replay",
            "chip_netlist_sha256": pins[str(chip)], "decoder_netlist_sha256": prior["decoder_netlist_sha256"],
            "counters": counters, "compiled_memory_instances": len(macros), "elaboration": compile_proof,
            "replay": replay, "input_sha256": pins,
        }
        (output / "receipt.json").write_text(json.dumps(result, indent=2) + "\n")
        print(result["state"], counters, flush=True)
    finally:
        if snapshot.is_dir():
            shutil.rmtree(snapshot)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=lambda value: Path(value).resolve())
    run(parser.parse_args().output)
