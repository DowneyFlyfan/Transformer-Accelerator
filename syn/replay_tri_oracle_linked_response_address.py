"""Check the archived attention trace on the relinked response-address candidate."""

import argparse
from collections import Counter
from contextlib import ExitStack
import json
from pathlib import Path
import re
import shutil
import time

from adapt_linked_parent_probes import score_connections
from audit_linked_layer_memory import observed
from link_tri_oracle_response_address_candidate import BUFFERED, ROOT, block, index, open_map, read, sha
from run_linked_layer_replay import (
    BENCH, check_replay, checked_simulator_log, shared_memory_stage, wait_for_shared_memory,
)
from run_tri_oracle_parallel_chip_synthesis import proc_identity


def wait_for_worker(pid):
    identity = proc_identity(pid)
    if not identity:
        return
    command = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    assert any(item.endswith(b"/replay_dual_weight_handoff.py") for item in command)
    deadline = time.monotonic() + 12 * 3600
    print("Waiting for the queued dual-lane handoff replay", pid, flush=True)
    while proc_identity(pid) == identity:
        assert time.monotonic() < deadline
        time.sleep(5)


def replace_include(code, original, updated):
    line = f'`include "{original}"'
    assert code.count(line) == 1, original
    return code.replace(line, f'`include "{updated}"')


def run(candidate_directory, worker):
    receipt_path = candidate_directory / "receipt.json"
    link = read(receipt_path)
    assert link["state"] == "mapped_response_address_logic_linked_with_buffered_fabric_preserved"
    candidate = candidate_directory / "candidate.v"
    assert sha(candidate) == link["candidate_sha256"]
    reference = BUFFERED / "integrated_attention"
    prior_path = reference / "receipt.json"
    prior = read(prior_path)
    assert prior["state"] == "attention_capture_select_buffer_candidate_replayed_exactly"
    assert prior["elaboration"]["native_exit_status"] == prior["replay"]["native_exit_status"] == 0
    baseline = reference / "positive/xrun.log"
    original_bundle = reference / "bundle.sv"
    source = original_bundle.read_text()
    original_probe, = [Path(path) for path in re.findall(r'(?m)^`include "([^"]+)"$', source)
                       if Path(path).name == "observers.sv"]
    pins = prior["input_sha256"].copy()
    for name, digest in link["input_sha256"].items():
        key = str(ROOT / name)
        assert pins.setdefault(key, digest) == digest, key
    assert all(sha(path) == pins[str(path)] for path in (baseline, original_bundle, original_probe))
    assert all(sha(path) == digest for path, digest in pins.items())
    memories = observed(baseline, f"{BENCH}.dut.")
    targets = Counter(line.split(maxsplit=2)[1] for line in baseline.read_text().splitlines()
                      if line.startswith("TRI_ORACLE_MAPPED_CENSUS "))
    assert len(memories) == 623 and sum(targets.values()) == 648
    fixture = Path(prior["fixture"])
    assert fixture.is_dir()

    tensor = link["tensor"]
    with ExitStack() as stack:
        netlist = open_map(stack, candidate)
        connections = score_connections(block(netlist, index(netlist), tensor).decode())
    first_core = "{(local_scores ? score_cluster : 3'd0), (single_core_scores ? score_core : 2'b00)}"
    observer_code = original_probe.read_text()
    for name, fields in (("cluster", connections), ("core", f".first_core({first_core}), {connections}")):
        header = f"bind {tensor} tri_oracle_{name}_local_score_probe score_{name}_probe "
        observer_code, count = re.subn(r"(?m)^" + re.escape(header) + r"\([\s\S]*?\);",
                                       lambda _: f"{header}({fields});", observer_code)
        assert count == 1, name

    output = candidate_directory / "integrated_attention"
    output.mkdir()
    bundle, observers, snapshot = (output / name for name in ("bundle.sv", "observers.sv", "xcelium.d"))
    observers.write_text(observer_code)
    source = replace_include(source, BUFFERED / "candidate.v", candidate)
    bundle.write_text(replace_include(source, original_probe, observers))
    for path in (receipt_path, prior_path, candidate, bundle, observers, Path(__file__).resolve(),
                 Path(score_connections.__code__.co_filename).resolve()):
        assert pins.setdefault(str(path), sha(path)) == sha(path)
    elaborate, positive = output / "elaborate", output / "positive"
    elaborate.mkdir()
    positive.mkdir()
    command = ["/opt/cadence/bin/xrun", "-64bit", "-xmlibdirname", str(snapshot),
               "-notimingchecks", "-mce", "-mce_sim_thread_count", "4"]
    wait_for_worker(worker)
    try:
        wait_for_shared_memory("linked response-address elaboration", 17)
        assert all(sha(path) == digest for path, digest in pins.items())
        build = shared_memory_stage("response_address_linked_elaboration", elaborate, [
            *command, "-sv", "-nospecify", "-sequdp_nba_delay", "-mce_build_thread_count", "4",
            "-xmerror", "RECOME", "-elaborate", "-top", BENCH,
            "-defparam", f"{BENCH}.INTEGRATE=1", "-defparam", f"{BENCH}.HOLD_DISABLED_RESTORE=1", str(bundle),
        ], 1800, 0)
        assert "Writing initial simulation snapshot:" in (elaborate / "console.log").read_text()
        wait_for_shared_memory("linked response-address replay", 17)
        native = shared_memory_stage("response_address_linked_replay", positive, [
            *command, "-R", f"+FIXTURE={fixture}", f"+DUMP={positive/'dump.hex'}",
        ], 10800, 0)
        log, replay = checked_simulator_log(positive, native, pins)
        check_replay(log, baseline, memories, targets)
        time_match, = re.findall(r"(?m)^Simulation complete via \$finish\(1\) at time (\d+) NS \+ 0$", log.read_text())
        assert int(time_match) == prior["simulation_end_ns"]
        assert all(sha(path) == digest for path, digest in pins.items())
        result = {
            "state": "response_address_linked_netlist_preserved_archived_attention",
            "candidate_sha256": pins[str(candidate)], "compiled_memory_macros": len(memories),
            "simulation_end_ns": int(time_match), "elaboration": build, "replay": replay, "input_sha256": pins,
        }
        with (output / "receipt.json").open("x") as stream:
            json.dump(result, stream, indent=2, sort_keys=True)
            stream.write("\n")
        print(result["state"], len(memories), time_match, flush=True)
    finally:
        if snapshot.is_dir():
            shutil.rmtree(snapshot)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate_directory", type=lambda path: Path(path).resolve())
    parser.add_argument("--after", type=int, default=0)
    args = parser.parse_args()
    run(args.candidate_directory, args.after)
