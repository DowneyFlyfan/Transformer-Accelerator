"""Verify the dual-lane linked netlist against the archived trained workloads."""

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import shutil

from prepare_tri_oracle_parallel_chip_synthesis import pin, read, verify
from replay_tri_oracle_parallel_chip import ATTENTION_FIXTURE, BASE, MODELS, XRUN, record
from run_tri_oracle_parallel_chip_synthesis import check_source, wait_for_receipt
from verify_tri_oracle_packed_down_weights import ROOT


ATTENTION_TOP = "tri_oracle_attention430_tb"
IMAGE_ARGUMENTS = {"PACKED_IMAGE": "down", "PAIR_IMAGE": "gate_up"}
TRAINED_MARKERS = (
    "PARALLEL_CHIP_DOWN_IMAGE bytes=11534336",
    "PARALLEL_CHIP_PAIR_IMAGE bytes=23068672",
    "UNIFIED_CHIP_FEEDFORWARD_RESPONSE tag=39300001 error=0",
    "UNIFIED_CHIP_FEEDFORWARD_PASS descriptor_words=15 commands=1 responses=1",
)


def check_attention(log, expected, markers):
    content = log.read_text()
    lines = Counter(content.splitlines())
    for marker in markers:
        assert lines[marker] == 1, marker
    assert content.count("Simulation complete via $finish(1)") == 1
    fields, = re.findall(r"(?m)^COMPOSE430_PASS (.*)$", content)
    actual = {name: int(value) for name, value in (item.split("=") for item in fields.split())}
    assert actual.keys() == expected.keys() and actual["rows"] == 4 and actual["maps"] == 576
    assert all(actual[name] == expected[name] for name in expected if name != "stalls"), actual
    return actual


def check_lane_activity(content, source):
    lanes = re.findall(r"(?m)^PARALLEL_CHIP_BRANCHES lane=([01]) gate=(\d+) up=(\d+) down=(\d+)$", content)
    assert [lane[0] for lane in lanes] == ["0", "1"], lanes
    responses = [dict(zip(("gate", "up", "down"), map(int, lane[1:]), strict=True)) for lane in lanes]
    assert responses == source["responses_by_lane"], responses
    assert all(value > 0 for lane in responses for value in lane.values())
    overlap, = re.findall(r"(?m)^PARALLEL_CHIP_READS simultaneous_responses=(\d+)$", content)
    cycles, = re.findall(r"(?m)^PACKED_DECODER_PASS .* cycles=(\d+)$", content)
    assert int(overlap) == source["simultaneous_responses"] > 0
    assert int(cycles) == source["simulated_cycles"], cycles
    return {"responses_by_lane": responses, "simultaneous_responses": int(overlap), "simulated_cycles": int(cycles)}


def run(prepared, candidate, output):
    import replay_fully_mapped_layer as native
    from run_linked_layer_replay import check_census
    from run_linked_trained_replay import BENCH, PARAMETERS, archived_inputs, verify_trained

    setup = read(prepared)
    assert setup["state"] == "linked_parallel_chip_gate_replay_prepared"
    pins = setup["input_sha256"].copy()
    link = prepared.parent.parent / "linked_chip/receipt.json"
    gate = link.with_name("chip.v")
    linked = read(link)
    assert linked["chip_sha256"] == setup["candidate_sha256"]
    pin(pins, gate, setup["candidate_sha256"])
    for file in (prepared, link, Path(__file__).resolve(), Path(native.__file__).resolve(),
                 Path(check_census.__code__.co_filename).resolve(), Path(verify_trained.__code__.co_filename).resolve()):
        pin(pins, file)

    source_attention = candidate / "full_native/attention_receipt.json"
    source_training = candidate / "full_native/trained_receipt.json"
    check_source(source_training, source_attention, candidate, pins)
    attention, trained = read(source_attention), read(source_training)
    attention_archive = BASE / "unified_chip/full_native/attention_receipt.json"
    pin(pins, attention_archive)
    archived_attention = read(attention_archive)
    for file in ATTENTION_FIXTURE.iterdir():
        key = str(file.relative_to(ROOT))
        assert attention["input_sha256"][key] == archived_attention["input_sha256"][key]
        pin(pins, file, attention["input_sha256"][key])

    archive, trained_pins, fixture_args = archived_inputs()
    for file, digest in trained_pins.items():
        pin(pins, Path(file), digest)
    image_args = []
    for argument, name in IMAGE_ARGUMENTS.items():
        manifest = MODELS / f"packed_{name}_export/v1/manifest.json"
        image = manifest.with_name("weights.bin")
        for file in (manifest, image):
            pin(pins, file, trained["input_sha256"][str(file.relative_to(ROOT))])
        image_args.append(f"+{argument}={image}")

    memories = setup["expected_memory_census"]
    targets = Counter(memories.values())
    assert dict(targets) == linked["compiled_memories"] and sum(targets.values()) == 623
    verify(pins)
    output.mkdir()
    native.OUTPUT = output
    invocation = output / "invocation.json"
    progress = output / "trained/progress.log"
    commands = {
        "attention": [*XRUN, "-top", ATTENTION_TOP, "-defparam", f"{ATTENTION_TOP}.INTEGRATE=1",
                      str(prepared.parent / "attention_bundle.sv"), f"+FIXTURE={ATTENTION_FIXTURE}",
                      f"+DUMP={output/'attention.hex'}"],
        "trained": [*XRUN, "-mce", "-mce_sim_thread_count", "4", "-mce_build_thread_count", "4", "-top", BENCH,
                    *(item for name, value in PARAMETERS.items() for item in ("-defparam", f"{BENCH}.{name}={value}")),
                    str(prepared.parent / "trained_bundle.sv"), f"+PROGRESS={progress}", *image_args, *fixture_args],
    }
    invocation.write_text(json.dumps(commands, indent=2) + "\n")
    try:
        log, execution = native.stage("attention", commands["attention"], 18.5, 13, 8, 5400)
        check_census(log, memories, targets, ATTENTION_TOP)
        counters = check_attention(log, attention["counters"], archived_attention["markers"])
        attention_result = output / "attention_receipt.json"
        record(output, attention_result.name, {
            "state": "linked_parallel_chip_replayed_archived_attention", "native": execution,
            "candidate_sha256": setup["candidate_sha256"], "counters": counters, "compiled_memories": len(memories),
        }, pins, invocation, log)
        print("LINKED_PARALLEL_CHIP_ATTENTION_PASS", counters, flush=True)

        log, execution = native.stage("trained", commands["trained"], 18.5, 13, 8, 21600)
        counters = verify_trained(log, progress, archive)
        assert counters == trained["counters"] and counters["exact_outputs"] == 32768
        check_census(log, memories, targets, BENCH)
        content = log.read_text()
        lines = Counter(content.splitlines())
        assert all(lines[marker] == 1 for marker in TRAINED_MARKERS)
        activity = check_lane_activity(content, trained)
        record(output, "receipt.json", {
            "state": "linked_parallel_chip_replayed_attention_and_exact_trained_feedforward",
            "candidate_sha256": setup["candidate_sha256"], "compiled_memories": len(memories),
            "trained_counters": counters, "trained_native": execution, **activity,
        }, pins, invocation, log, progress, attention_result)
        print("LINKED_PARALLEL_CHIP_TRAINED_PASS", counters["exact_outputs"], flush=True)
    finally:
        for name in commands:
            for directory in ("xcelium.d", "mcesim.run"):
                snapshot = output / name / directory
                if snapshot.is_dir():
                    shutil.rmtree(snapshot)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("prepared", "candidate", "output"):
        parser.add_argument(name, type=lambda value: Path(value).resolve())
    parser.add_argument("--prepare-worker", type=int)
    args = parser.parse_args()
    if args.prepare_worker is not None:
        wait_for_receipt(args.prepared, args.prepare_worker, "prepare_tri_oracle_parallel_gate_replay.py")
    run(args.prepared, args.candidate, args.output)
