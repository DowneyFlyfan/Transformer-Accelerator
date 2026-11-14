"""Replay the trained layer-10 feed-forward fixture on the buffered netlist."""

import argparse
from hashlib import file_digest
import json
from pathlib import Path
import re
import shutil
import subprocess
import time

from audit_tri_oracle_placed_fanout import GIB, memory
from tri_oracle_process_guard import terminate_process_group


ROOT = Path(__file__).resolve().parents[1]
TOP = "tri_oracle_batched406_learned_tb"
FLAGS = ("SIGN_READS", "PACKED_IMAGE", "PAIR_IMAGE", "FIXTURE", "RAW_FIXTURE", "LEARNED_FIXTURE",
         "INTERMEDIATE_FIXTURE")
MILESTONES = (
    "BATCH408_ACTIVATION_PASS", "BATCH408_SHARED_BUS", "DUAL_LANE_PACKED_SIGN_PASS",
    "PACKED_PAIR_BRANCHES", "PACKED_DECODER_PASS", "BATCH408_PASS", "UNIFIED_CHIP_FEEDFORWARD_PASS",
)


def digest(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def read_record(name):
    return json.loads((ROOT / "records" / name).read_bytes())


def verify_log(observed, reference):
    assert observed.count("Simulation complete via $finish(1)") == 1
    assert not re.search(r"(?m)^\S+: \*[EF],", observed)
    for marker in MILESTONES:
        pattern = rf"(?m)^{marker} .+$"
        rows = re.findall(pattern, observed)
        assert len(rows) == 1 and rows == re.findall(pattern, reference), marker
    pattern = r"(?m)^TRI_ORACLE_MAPPED_CENSUS (.+)$"
    macros = sorted(re.findall(pattern, observed))
    assert len(macros) == len(set(macros)) == 631 and macros == sorted(re.findall(pattern, reference))


def checked_fixture(candidate, reference):
    graph = read_record("tri_oracle_grouped_active_graph.json")
    reset = read_record("tri_oracle_grouped_reset_replay.json")
    prior = read_record("tri_oracle_layer10_mapped_feedforward.json")
    assert graph["parent_netlist_sha256"] == reset["buffered_netlist_sha256"]
    assert reset["reference_netlist_sha256"] == prior["candidate_sha256"]
    assert prior["positions"] == [607, 608] and prior["exact_feedforward_outputs"] == 4096
    assert digest(candidate) == graph["candidate_netlist_sha256"]
    archived_path = reference / "receipt.json"
    archived_log = reference / "trained/xrun.log"
    for path in (archived_path, archived_log):
        assert digest(path) == prior["evidence_sha256"][str(path.relative_to(ROOT))]
    archived = json.loads(archived_path.read_bytes())
    assert archived["candidate_sha256"] == prior["candidate_sha256"]
    assert archived["native"]["native_exit_status"] == 0
    assert archived["positions"] == prior["positions"] and archived["exact_feedforward_words"] == 4096
    pins = {ROOT / name: value for name, value in archived["input_sha256"].items()}
    archived_bundle = reference / "bundle.sv"
    assert digest(archived_bundle) == pins[archived_bundle]
    source = archived_bundle.read_text()
    includes = [Path(path) for path in re.findall(r'(?m)^`include "([^"]+)"$', source)]
    original, = [path for path in includes if path.name == "linked_physical.v"]
    assert prior["candidate_sha256"] == pins[original]
    assert all(path in pins for path in includes)
    assert all(digest(path) == expected for path, expected in pins.items())
    assert source.count(str(original)) == 1

    previous = archived_log.read_text()
    flag_values = {}
    for flag in FLAGS:
        value, = set(re.findall(rf"(?m)^\s*\+{flag}=(\S+)\s*$", previous))
        path = Path(value)
        assert path.is_relative_to(reference)
        if path.is_file():
            assert path in pins, path
        else:
            assert path.is_dir() and any(p.is_relative_to(path) for p in pins), path
        flag_values[flag] = value
    verify_log(previous, previous)
    return graph, prior, pins, archived_path, archived_log, previous, source.replace(str(original), str(candidate)), flag_values


def replay(candidate, reference, out):
    assert __debug__ and Path("/.dockerenv").is_file()
    assert out.is_relative_to(ROOT / ".cache") and out.is_dir()
    graph, prior, pins, archived_path, archived_log, previous, source, flag_values = checked_fixture(candidate, reference)

    available, anonymous = memory()
    assert available >= 15 * GIB and anonymous < 3 * GIB and shutil.disk_usage(out).free >= 10 * GIB
    bundle, log = out / "bundle.sv", out / "xrun.log"
    with bundle.open("x") as stream:
        stream.write(source)
    argv = ["/opt/cadence/bin/xrun", "-64bit", "-sv", "-nospecify", "-notimingchecks",
            "-sequdp_nba_delay", "-xmerror", "RECOME", "-top", TOP, "-log", str(log)]
    for name, value in (("TOKENS", 2), ("HIDDEN", 2048), ("INTERMEDIATE", 5632), ("OUTPUTS", 2048), ("TRAINED", 1)):
        argv.extend(["-defparam", f"{TOP}.{name}={value}"])
    flag_values["PROGRESS"] = str(out / "progress.log")
    argv.extend([str(bundle), *(f"+{name}={value}" for name, value in flag_values.items())])

    minimum, peak = available, anonymous
    started = time.monotonic()
    with (out / "console.log").open("x") as stream:
        worker = subprocess.Popen(argv, cwd=out, stdin=subprocess.DEVNULL, stdout=stream,
                                  stderr=subprocess.STDOUT, start_new_session=True)
        print(f"BUFFERED_TRAINED_FEEDFORWARD_STARTED {worker.pid}", flush=True)
        try:
            while worker.poll() is None:
                available, anonymous = memory()
                minimum, peak = min(minimum, available), max(peak, anonymous)
                if minimum < 5 * GIB or peak > 14 * GIB or time.monotonic() - started > 7200:
                    raise RuntimeError(f"Buffered feed-forward resource guard: {minimum} {peak}")
                time.sleep(0.5)
        finally:
            terminate_process_group(worker, log_argument=str(log))
    assert worker.returncode == 0, worker.returncode
    text = log.read_text()
    assert f"file: {bundle}" in text and f"-top {TOP}" in text
    assert all(f"+{name}={value}" in text for name, value in flag_values.items())
    verify_log(text, previous)
    assert digest(candidate) == graph["candidate_netlist_sha256"]
    assert all(digest(path) == expected for path, expected in pins.items())
    result = dict(
        state="buffered_chip_layer10_trained_feedforward_verified",
        candidate_netlist_sha256=graph["candidate_netlist_sha256"], positions=prior["positions"],
        exact_feedforward_outputs=prior["exact_feedforward_outputs"], memory_macros=631,
        feedforward_cycles=prior["measured_feedforward_cycles"],
        native=dict(seconds=time.monotonic() - started, exit_status=worker.returncode,
                    peak_anonymous_bytes=peak, minimum_host_available_bytes=minimum),
        evidence_sha256={str(path.relative_to(ROOT)): digest(path) for path in
                         (bundle, log, archived_path, archived_log, Path(__file__).resolve(),
                          ROOT / "records/tri_oracle_grouped_active_graph.json", out / "progress.log")},
        scope="Functional feed-forward replay with archived host residual inputs at two layer-10 positions. "
              "The replay disables timing checks and uses the same expected codes and memory fixtures as the imported chip.",
    )
    with (out / "receipt.json").open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    shutil.rmtree(out / "xcelium.d")
    print("BUFFERED_TRAINED_FEEDFORWARD_PASS", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("candidate", "reference", "out"):
        parser.add_argument(name, type=lambda path: Path(path).resolve())
    replay(**vars(parser.parse_args()))
