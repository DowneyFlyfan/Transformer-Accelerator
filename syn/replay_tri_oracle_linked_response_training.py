"""Replay the archived trained layer after the linked attention gate passes."""

import argparse
import json
from pathlib import Path
import shutil
import time

from link_tri_oracle_response_address_candidate import COMPACT, ROOT, read, sha
from replay_trained_compact_tensor import baseline_inputs
from run_linked_layer_replay import check_census, checked_simulator_log, shared_memory_stage, wait_for_shared_memory
from run_linked_trained_replay import BENCH, verify_trained
from run_tri_oracle_parallel_chip_synthesis import proc_identity


def wait_for_attention(worker):
    identity = proc_identity(worker)
    if not identity:
        return
    argv = Path(f"/proc/{worker}/cmdline").read_bytes().split(b"\0")
    assert any(item.endswith(b"/replay_tri_oracle_linked_response_address.py") for item in argv)
    deadline = time.monotonic() + 24 * 3600
    print("Waiting for the linked attention replay", worker, flush=True)
    while proc_identity(worker) == identity:
        assert time.monotonic() < deadline
        time.sleep(5)


def run(directory, worker):
    link_path = directory / "receipt.json"
    link = read(link_path)
    assert link["state"] == "mapped_response_address_logic_linked_with_buffered_fabric_preserved"
    candidate = directory / "candidate.v"
    assert sha(candidate) == link["candidate_sha256"]
    pins, archive, counters, memories, targets, command, old_bundle, old_progress = baseline_inputs()
    compact_path = COMPACT / "linked_tensor_trained/receipt.json"
    compact = read(compact_path)
    assert compact["state"] == "compact_mapped_tensor_preserved_exact_trained_replay"
    assert compact["native"]["native_exit_status"] == 0 and compact["compiled_memory_macros"] == len(memories) == 623
    assert compact["counters"] == counters and counters["exact_outputs"] == 32768
    compact_progress = compact_path.with_name("progress.log")
    assert compact["input_sha256"][str(compact_progress)] == sha(compact_progress) == sha(old_progress)
    output = directory / "integrated_trained"
    output.mkdir()
    bundle, progress, snapshot = (output / name for name in ("bundle.sv", "progress.log", "xcelium.d"))
    original = COMPACT.parent / "fully_mapped_layer_replays_split/linked/linked_layer.v"
    include = f'`include "{original}"'
    source = old_bundle.read_text()
    assert source.count(include) == 1
    bundle.write_text(source.replace(include, f'`include "{candidate}"'))
    arguments = {str(old_bundle): str(bundle), str(old_bundle.parent / "xcelium.d"): str(snapshot),
                 f"+PROGRESS={old_progress}": f"+PROGRESS={progress}"}
    assert all(command.count(arg) == 1 for arg in arguments)
    command = [arguments.get(arg, arg) for arg in command]
    invocation = output / "invocation.json"
    invocation.write_text(json.dumps({"argv": command}, indent=2) + "\n")
    for path in (candidate, link_path, compact_path, compact_progress, bundle, invocation, Path(__file__).resolve()):
        assert pins.setdefault(str(path), sha(path)) == sha(path), path

    wait_for_attention(worker)
    attention_path = directory / "integrated_attention/receipt.json"
    attention = read(attention_path)
    assert attention["state"] == "response_address_linked_netlist_preserved_archived_attention"
    assert attention["replay"]["native_exit_status"] == attention["elaboration"]["native_exit_status"] == 0
    assert attention["compiled_memory_macros"] == 623 and attention["candidate_sha256"] == pins[str(candidate)]
    for name, digest in attention["input_sha256"].items():
        key = str(ROOT / name)
        assert pins.setdefault(key, digest) == digest, key
    pins[str(attention_path)] = sha(attention_path)
    assert all(sha(path) == digest for path, digest in pins.items())

    try:
        wait_for_shared_memory("linked response-address trained replay", 17)
        native = shared_memory_stage("linked_response_address_trained_replay", output, command, 21600, 0)
        log, native = checked_simulator_log(output, native, pins)
        actual = verify_trained(log, progress, archive)
        assert actual == counters and sha(progress) == pins[str(compact_progress)]
        check_census(log, memories, targets, BENCH)
        pins[str(progress)] = sha(progress)
        assert all(sha(path) == digest for path, digest in pins.items())
        result = {
            "state": "response_address_linked_netlist_preserved_trained_layer",
            "candidate_sha256": pins[str(candidate)], "native": native, "counters": actual,
            "compiled_memory_macros": len(memories), "progress_matches_archived_cycles": True, "input_sha256": pins,
        }
        with (output / "receipt.json").open("x") as stream:
            json.dump(result, stream, indent=2, sort_keys=True)
            stream.write("\n")
        print(result["state"], actual["exact_outputs"], flush=True)
    finally:
        if snapshot.is_dir():
            shutil.rmtree(snapshot)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate_directory", type=lambda path: Path(path).resolve())
    parser.add_argument("--after", type=int, default=0)
    args = parser.parse_args()
    run(args.candidate_directory, args.after)
