"""Bind completed dual-lane mapped replays to the exact candidate and workload."""

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys

from check_tri_oracle_paper300_gate import sha


ROOT = Path(__file__).resolve().parents[1]
PHYSICAL = ROOT / ".cache/physical"
BASE = PHYSICAL / "wide_weight_loader"
MODELS = ROOT / ".cache/model_reference"
ATTENTION = PHYSICAL / "shared437/fixture"
ATTENTION_TOP = "tri_oracle_attention430_tb"
TRAINED_TOP = "tri_oracle_batched406_learned_tb"
TRAINED_PARAMETERS = {"TOKENS": 16, "HIDDEN": 2048, "INTERMEDIATE": 5632, "OUTPUTS": 2048, "TRAINED": 1}
INCLUDE = re.compile(r'(?m)^`include "([^"]+)"$')
XRUN_ERROR = re.compile(r"\*[EF],|\*ERROR|Simulation terminated via \$fatal")


def read(path):
    return json.loads(path.read_text())


def verify_pins(pins):
    for path, expected in pins.items():
        assert sha(ROOT / path) == expected, path


def bind_native_log(text, bundle, top, parameters, plusargs):
    """Check the compiler input and effective arguments in the native transcript."""
    lines = Counter(text.splitlines())
    start = text.index("\nxrun\n")
    invocation = text[start:].split("\n\n", 1)[0].splitlines()
    assert invocation.count(f"\t{bundle}") == 1 and lines[f"file: {bundle}"] == 1
    assert [line for line in invocation if line.startswith("\t-top ")] == [f"\t-top {top}"]
    assert Counter(line for line in invocation if line.startswith("\t-defparam ")) == Counter(
        f"\t-defparam {top}.{name}={value}" for name, value in parameters.items()
    )
    assert Counter(line.strip() for line in invocation if line.startswith("\t+")) == Counter(plusargs)
    assert len(re.findall(rf"(?m)^Loading snapshot worklib\.{re.escape(top)}:sv\b", text)) == 1
    assert text.count("Simulation complete via $finish(1)") == 1 and not XRUN_ERROR.search(text)
    assert "Exiting on " in text.splitlines()[-1]


def verify_bundle(prepared, bundle, gate, bench, source_bundle, pins):
    assert pins[str(bundle.relative_to(ROOT))] == sha(bundle)
    includes = INCLUDE.findall(bundle.read_text())
    source_models = [name for name in INCLUDE.findall(source_bundle.read_text())
                     if Path(name).parent.name in ("VERILOG", "library") and Path(name).suffix == ".v"]
    census = prepared / "memory_census.sv"
    assert len(source_models) == len(set(source_models)) == 7
    assert includes == [*source_models, str(gate), str(bench), str(census)]
    for path in includes:
        assert pins[str(Path(path).relative_to(ROOT))] == sha(path), path


def verify(synthesis, candidate):
    if not __debug__:
        raise RuntimeError("Run the mapped execution verifier with assertions enabled")
    prepared = synthesis / "gate_replay_prepared"
    replay = synthesis / "gate_replay"
    linked = synthesis / "linked_chip"
    path = replay / "receipt.json"
    if not path.is_file():
        raise FileNotFoundError(f"Completed mapped replay is required: {path}")

    for directory in (
        "wac_budgeted_parent_boundary", "shared_memory_layer_boundary", "context_external/shared_decoder",
        "shared437/aggregator_local_merge/cluster_native", "wac_budgeted_parent_boundary/compact_load_transport",
        "external_read_mux", "external_write_mux",
    ):
        sys.path.append(str(PHYSICAL / directory))
    from run_linked_layer_replay import check_census
    from run_linked_trained_replay import archived_inputs, verify_trained
    from run_tri_oracle_parallel_gate_replay import TRAINED_MARKERS, check_attention, check_lane_activity
    from verify_tri_oracle_mapped_paper_topology import audit_chip_hierarchy

    gate = linked / "chip.v"
    link_path, setup_path = linked / "receipt.json", prepared / "prepared.json"
    attention_path = replay / "attention_receipt.json"
    link, setup, attention, trained = map(read, (link_path, setup_path, attention_path, path))
    assert link["state"] == "parallel_chip_parent_linked_with_verified_mapped_imports"
    assert setup["state"] == "linked_parallel_chip_gate_replay_prepared"
    assert attention["state"] == "linked_parallel_chip_replayed_archived_attention"
    assert trained["state"] == "linked_parallel_chip_replayed_attention_and_exact_trained_feedforward"
    identity = sha(gate)
    assert identity == link["chip_sha256"] == setup["candidate_sha256"]
    assert identity == attention["candidate_sha256"] == trained["candidate_sha256"]
    assert setup["top"] == link["top"]
    for report in (link, setup, attention, trained):
        verify_pins(report["input_sha256"])
    pins = trained["input_sha256"]
    for artifact in (gate, link_path, setup_path, attention_path):
        assert pins[str(artifact.relative_to(ROOT))] == sha(artifact)
    assert pins[str(gate.relative_to(ROOT))] == identity

    source_bundle = candidate / "bundle.sv"
    assert pins[str(source_bundle.relative_to(ROOT))] == sha(source_bundle)
    prior = candidate / "full_native"
    source_paths = tuple(prior / name for name in ("attention_receipt.json", "trained_receipt.json"))
    assert all(pins[str(item.relative_to(ROOT))] == sha(item) for item in source_paths)
    source_attention, source_training = map(read, source_paths)
    assert source_attention["native"]["native_exit_status"] == source_training["native"]["native_exit_status"] == 0
    attention_archive_path = BASE / "unified_chip/full_native/attention_receipt.json"
    assert pins[str(attention_archive_path.relative_to(ROOT))] == sha(attention_archive_path)
    archived_attention = read(attention_archive_path)
    for asset in ATTENTION.iterdir():
        key = str(asset.relative_to(ROOT))
        assert pins[key] == archived_attention["input_sha256"][key] == sha(asset)
    archive, archive_pins, fixture_args = archived_inputs()
    for name, expected in archive_pins.items():
        assert pins[str(Path(name).relative_to(ROOT))] == expected
    images = {"PACKED_IMAGE": "down", "PAIR_IMAGE": "gate_up"}
    for name in images.values():
        asset = MODELS / f"packed_{name}_export/v1/weights.bin"
        key = str(asset.relative_to(ROOT))
        assert pins[key] == source_training["input_sha256"][key] == sha(asset)
    image_args = [f"+{argument}={MODELS}/packed_{name}_export/v1/weights.bin" for argument, name in images.items()]

    progress = replay / "trained/progress.log"
    assert pins[str(progress.relative_to(ROOT))] == sha(progress)
    memories = setup["expected_memory_census"]
    targets = Counter(memories.values())
    assert len(memories) == attention["compiled_memories"] == trained["compiled_memories"] == 623
    assert dict(targets) == link["compiled_memories"]
    for mode, top, parameters, plusargs, native in (
        ("attention", ATTENTION_TOP, {"INTEGRATE": 1},
         (f"+FIXTURE={ATTENTION}", f"+DUMP={replay/'attention.hex'}"), attention["native"]),
        ("trained", TRAINED_TOP, TRAINED_PARAMETERS, (f"+PROGRESS={progress}", *image_args, *fixture_args),
         trained["trained_native"]),
    ):
        log = replay / mode / "xrun.log"
        bundle = prepared / f"{mode}_bundle.sv"
        verify_bundle(prepared, bundle, gate, prepared / f"{mode}_tb.sv", source_bundle, pins)
        assert native["native_exit_status"] == 0
        assert sha(log) == native["log_sha256"] == pins[str(log.relative_to(ROOT))]
        bind_native_log(log.read_text(), bundle, top, parameters, plusargs)
        check_census(log, memories, targets, top)

    counters = check_attention(replay / "attention/xrun.log", source_attention["counters"], archived_attention["markers"])
    assert counters == attention["counters"]
    trained_log = replay / "trained/xrun.log"
    counters = verify_trained(trained_log, progress, archive)
    assert counters == trained["trained_counters"] == source_training["counters"]
    assert counters["exact_outputs"] == TRAINED_PARAMETERS["TOKENS"] * TRAINED_PARAMETERS["OUTPUTS"]
    text = trained_log.read_text()
    assert all(text.splitlines().count(marker) == 1 for marker in TRAINED_MARKERS)
    activity = check_lane_activity(text, source_training)
    assert all(trained[key] == value for key, value in activity.items())
    hierarchy_pins = {}

    def pin_hierarchy(path, expected=None):
        key = str(path.relative_to(ROOT))
        digest = sha(path)
        assert expected is None or digest == expected, path
        assert hierarchy_pins.setdefault(key, digest) == digest, path

    attention_bundle = prepared / "attention_bundle.sv"
    included = [Path(name) for name in INCLUDE.findall(attention_bundle.read_text())]
    hierarchy = audit_chip_hierarchy(gate.read_text(), link["top"], memories, included, pin_hierarchy)
    verify_pins(hierarchy_pins)
    evidence = (path, attention_path, link_path, setup_path, gate, progress, trained_log,
                replay / "attention/xrun.log", Path(__file__).resolve())
    return {
        "state": "linked_mapped_dual_lane_execution_independently_verified",
        "candidate_sha256": identity, "compiled_memories": len(memories), "attention_rows": attention["counters"]["rows"],
        "trained_exact_outputs": counters["exact_outputs"], **activity,
        "mapped_hierarchy": hierarchy,
        "evidence_sha256": {str(item.relative_to(ROOT)): sha(item) for item in evidence} | hierarchy_pins,
        "scope": "Native mapped workload execution before placement. Timing, model accuracy and energy are separate proofs.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("synthesis", "candidate", "output"):
        parser.add_argument(name, type=lambda value: Path(value).resolve())
    args = parser.parse_args()
    result = verify(args.synthesis, args.candidate)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(result["state"], result["trained_exact_outputs"], flush=True)
