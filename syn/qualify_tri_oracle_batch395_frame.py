"""Bind the joined small-frame runs and complete trained software fixture.

The trained hardware run, mapped timing, and paper benchmarks are separate.
Run in the Cadence simulation container with the original local evidence.
"""

import datetime
import gzip
import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
HIERARCHY = "BATCH357_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=600"
GATE_TILES = [(0, 80), (80, 16)]
DOWN_TILES = [(0, 160), (160, 13)]


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def events(log, prefix, event):
    pattern = rf"^{prefix}_{event} start=(\d+) count=(\d+)$"
    return [tuple(map(int, pair)) for pair in re.findall(pattern, log, re.MULTILINE)]


def live_groups():
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            try:
                fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                continue
            if fields[0] not in ("Z", "X"):
                yield int(fields[2])


def main():
    output = ROOT / "records/batch395_frame_qualification.json"
    archive = ROOT / "records/batch395_native_logs.json.gz"
    assert not output.exists() and not archive.exists()
    evidence = {}
    logs = {}

    def bind(name, expected=None):
        path = (ROOT / name).resolve()
        if path not in evidence:
            evidence[path] = sha256(path)
        assert expected is None or expected == evidence[path], f"Evidence changed: {path}"
        return path

    def record(name):
        return json.loads(bind("records/" + name).read_text())

    def bind_sources(sources):
        for path, digest in sources.items():
            bind(path, digest)

    def read_log(name, digest):
        path = bind(name, digest)
        assert str(path) not in logs
        logs[str(path)] = path.read_text()
        return logs[str(path)]

    fixture = record("batch389_fixture_preparation.json")
    guard = record("batch389_gpu_guard_result.json")
    assert guard["state"] == "completed" and guard["native_exit_status"] == 0
    assert guard["input_drift"] == []
    bind("records/batch389_fixture_preparation.json", guard["summary_sha256"])
    assert read_log(".cache/batch389_gpu_native.log", guard["native_log_sha256"]).strip() == (
        "BATCH389_COMPLETE_LAYER_FIXTURE_READY"
    )
    assert fixture["state"] == "complete_trained_layer_fixture_scalar_cuda_equal"
    tokens, hidden, intermediate, outputs = (
        fixture[key] for key in ("tokens", "input_features", "intermediate_features", "output_features")
    )
    assert (tokens, hidden, intermediate, outputs) == (16, 2048, 5632, 2048)
    assert fixture["original_layer"] == 0
    assert fixture["original_token_positions"] == [(i * 605 + 7) // 15 for i in range(16)]
    assert all(fixture[key] is True for key in (
        "all_original_rows_preserved", "complete_canonical_output_reconstruction_equal",
        "prior379_gated_and_down_subsets_equal", "prior386_complete_down_inputs_and_selected_outputs_equal",
        "independent_scalar_complete_layer_equal",
    ))
    assert fixture["exact_gate_up_words"] == 2 * tokens * intermediate
    assert fixture["exact_intermediate_bytes"] == tokens * intermediate
    assert fixture["exact_final_outputs"] == tokens * outputs
    bind_sources(fixture["source_sha256"])
    bind_sources(guard["source_sha256"])
    bind_sources(fixture["files_sha256"])

    fixture_dir = Path(fixture["fixture"])
    layouts = {
        "activation": (tokens * hidden, 3), "gate": (intermediate * hidden, 3),
        "up": (intermediate * hidden, 3), "down": (outputs * intermediate, 3),
        "keep": (tokens * intermediate, 3), "intermediate": (tokens * intermediate, 3),
        "shifts": (tokens * 3, 3), "expected": (tokens * outputs, 9),
    }
    assert set(fixture["files_sha256"]) == {str(fixture_dir / f"{name}.hex") for name in layouts}
    for name, (count, stride) in layouts.items():
        path = fixture_dir / f"{name}.hex"
        assert path.stat().st_size == count * stride
        with path.open("rb") as stream:
            lines = sum(block.count(b"\n") for block in iter(lambda: stream.read(1024 * 1024), b""))
        assert lines == count, f"Invalid line count: {path}"
    keep = (fixture_dir / "keep.hex").read_text().splitlines()
    assert set(keep) == {"00", "01"}
    assert keep.count("00") == fixture["predicted_skipped_pairs"] == 5231
    shifts = (fixture_dir / "shifts.hex").read_text().split()
    assert [int(value, 16) for value in shifts] == [
        value for row in fixture["hardware_shifts"] for value in row
    ]

    literal = record("batch393_literal_result.json")
    cancel = record("batch394_mask_control.json")
    assert literal["state"] == "literal_joined_feedforward_and_six_recoveries_passed"
    assert cancel["state"] == "held_mask_flow_cancel_recovery_and_stale_rejection_verified"
    for receipt in (literal, cancel):
        assert receipt["temporary_builds_removed"] is True
        assert receipt["full_paper_results_matched"] is False
        bind_sources(receipt["source_sha256"])
    frame_sources = [
        path for path in literal["source_sha256"] if "/verilog/" in path and not path.endswith("_tb.sv")
    ]
    assert len(frame_sources) == 11
    assert all(literal["source_sha256"][path] == cancel["source_sha256"][path] for path in frame_sources)
    assert sorted(run["fault"] for run in literal["runs"]) == list(range(7))
    assert sorted((run["fault"], run["honor_cancel"]) for run in cancel["runs"]) == [(0, 1), (1, 0), (1, 1)]
    groups = {literal["supervisor_pid"], cancel["supervisor_pid"]}
    totals = []
    recovery_masks = {0: [], 1: [(0, 80)], 2: GATE_TILES, 3: GATE_TILES, 4: [(1, 80)], 5: [], 6: []}
    for batch, receipt in ((393, literal), (394, cancel)):
        prefix = f"BATCH{batch}"
        total = 0
        for run in receipt["runs"]:
            fault = run["fault"]
            log = read_log(run["log"], run["log_sha256"])
            assert log.splitlines().count(HIERARCHY) == 1
            groups.add(run["process_group"])
            command = run["command"]
            assert command[0] == "/opt/cadence/bin/xrun" and "-notimingchecks" in command
            assert not Path(command[command.index("-xmlibdirname") + 1]).parent.exists()
            masks = events(log, prefix, "MASK_ACCEPTED")
            down = events(log, prefix, "OUTPUT_TILE")
            pass_lines = re.findall(rf"^{prefix}_PASS (.+)$", log, re.MULTILINE)
            fault_lines = re.findall(rf"^{prefix}_FAULT_DRAINED (.+)$", log, re.MULTILINE)
            assert fault_lines == ([f"fault={fault} output_prefix_packets={3 if fault == 3 else 0}"] if fault else [])
            if batch == 394 and not run["honor_cancel"]:
                assert run["native_exit_status"] == 2 and run["state"] == "stale_offer_rejected"
                assert not pass_lines and masks == [(0, 80)] and not down
                assert re.search(r"^BATCH394_STALE_MASK_REJECTED_AFTER_IGNORED_CANCEL$", log, re.MULTILINE)
                assert log.count("xmsim: *F,FATSEV") == 1
                continue
            assert run["native_exit_status"] == 0 and len(pass_lines) == 1
            assert not re.search(r"\*(?:E|F),|\*ERROR|Simulation terminated via \$fatal", log)
            inventory = {name: int(value) for name, value in (item.split("=") for item in pass_lines[0].split())}
            assert inventory == dict(tokens=3, hidden=64, intermediate=96, outputs=173,
                exact_outputs=519, intermediate_bytes=288, output_packets=6,
                read_requests=1500, read_bytes=29728, fault=fault, trained=0)
            if batch == 393:
                assert inventory == run["inventory"]
                assert masks == recovery_masks[fault] + GATE_TILES
                assert down == ([(0, 160)] if fault == 3 else []) + DOWN_TILES
            else:
                assert masks == ([(0, 80)] if fault else []) + GATE_TILES
                assert down == DOWN_TILES
                flow = re.findall(r"^BATCH394_MASK_FLOW held_cycles=(\d+) cancelled=(\d+)$", log, re.MULTILINE)
                assert len(flow) == 1 and int(flow[0][0]) > 0 and int(flow[0][1]) == fault
                if fault:
                    held = re.findall(r"^BATCH394_MASK_CANCELLED start=80 held_cycles=(\d+)$", log, re.MULTILINE)
                    assert len(held) == 1 and int(held[0]) > 0
            total += inventory["exact_outputs"]
        assert total == receipt["exact_output_comparisons"]
        totals.append(total)

    assert totals == [3633, 1038] and len(logs) == 11
    assert not groups.intersection(live_groups()), "Finished run still has a live process group"
    payload = json.dumps(logs, sort_keys=True, separators=(",", ":")).encode()
    archive.write_bytes(gzip.compress(payload, mtime=0))
    assert json.loads(gzip.decompress(archive.read_bytes())) == logs
    report = {
        "state": "shared_feedforward_small_frames_and_trained_fixture_qualified",
        "verified_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "qualifier_sha256": sha256(Path(__file__)),
        "source_and_evidence_sha256": {str(path): digest for path, digest in sorted(evidence.items())},
        "actual_cores": 20,
        "actual_clusters": 5,
        "actual_vendor_memory_models": 600,
        "small_frame_output_comparisons": sum(totals),
        "small_frame_intermediate_bytes_checked": 9 * 288,
        "small_frame_successful_runs": 9,
        "literal_recovery_cases": 6,
        "held_mask_cancellation_and_stale_rejection_verified": True,
        "trained_reference_output_comparisons": fixture["exact_final_outputs"],
        "trained_reference_intermediate_bytes": fixture["exact_intermediate_bytes"],
        "native_logs": len(logs),
        "logs_archive_sha256": sha256(archive),
        "trained_hardware_pass_established": False,
        "whole_model_verified": False,
        "routed_timing_qualified": False,
        "full_paper_results_matched": False,
        "scope": __doc__,
    }
    output.write_text(json.dumps(report, indent=2) + "\n")
    print("BATCH395_QUALIFIED small_frame_outputs=4671 intermediate_bytes=2592 native_logs=11")


if __name__ == "__main__":
    main()
