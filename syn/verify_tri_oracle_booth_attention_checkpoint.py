"""Validate a saved Xcelium checkpoint and the output prefix it commits."""

from argparse import ArgumentParser
from decimal import Decimal
import fcntl
from hashlib import sha256
import json
from pathlib import Path
import re

from prepare_tri_oracle_booth_packet_replay import ROOT, WORK as ATTENTION, digest


WORK = ROOT / ATTENTION.parent / "unseeded_packet_layer"
NATIVE = WORK / "native"
LOCK = ROOT / ".cache/physical/carry_lookahead_comparison/placed_drive_strength/native_lane.lock"
DRIVER = ROOT / "syn/tri_oracle_booth_attention_checkpoint.tcl"
CHECKPOINT = re.compile(r"(?m)^TRI_UNSEEDED_PACKET_CHECKPOINT (checkpoint_[ab])$")
SAVED = re.compile(r"(?m)^Saved snapshot worklib\.(checkpoint_[ab]):sv$")
TIME = re.compile(r"(?m)^Ran until (\d+(?:\.\d+)?) (FS|PS|NS|US|MS|S) \+ 0$")
GROUP = re.compile(r"(?m)^UNSEEDED_PACKET_PROJECTION_GROUP_PASS group=(\d+) vectors=409$")
BATCH = re.compile(r"^UNSEEDED_PACKET_PROJECTION_BATCH_PASS group=(\d+) slot=(\d+) tokens=(\d+)"
                   r" weights=(\d+) skipped_columns=(\d+)$")
PROJECTION = re.compile(r"(?m)^UNSEEDED_PACKET_PROJECTION_(?:BATCH|GROUP)_PASS[^\n]*$")
ROW = re.compile(r"(?m)^UNSEEDED_PACKET_ATTENTION_ROW_PASS head=(\d+) rank=(\d+) value_reads=(\d+)$")
RECOVERY_FOLDER = re.compile(r"recovery_after_(\d+)ns")
TO_NS = {"FS": Decimal("0.000001"), "PS": Decimal("0.001"), "NS": Decimal(1),
         "US": Decimal(10**3), "MS": Decimal(10**6), "S": Decimal(10**9)}


def checkpoint_prefix(transcript):
    markers = list(CHECKPOINT.finditer(transcript))
    if not markers:
        raise ValueError("Xcelium has yet to report a saved checkpoint")
    previous = 0
    for index, marker in enumerate(markers):
        step = transcript[previous:marker.start()]
        times = list(TIME.finditer(step))
        saves = list(SAVED.finditer(step))
        assert len(times) == len(saves) == 1 and times[0].end() < saves[0].start()
        time, unit = times[0].groups()
        assert Decimal(time) * TO_NS[unit] == 1_200_000 + index * 15_000_000
        slot = "checkpoint_b" if index % 2 else "checkpoint_a"
        assert marker[1] == saves[0][1] == slot
        previous = marker.end()
    prefix = transcript[:previous] + "\n"
    assert not re.search(r"\*[EF],", prefix)
    groups = [int(group) for group in GROUP.findall(prefix)]
    assert groups == list(range(len(groups))) and len(groups) <= 40
    rows = [tuple(map(int, fields)) for fields in ROW.findall(prefix)]
    assert len(rows) <= 128 and (not rows or len(groups) == 40)
    return {
        "snapshot": f"worklib.{slot}:sv",
        "checkpoint_time_ns": int(Decimal(time) * TO_NS[unit]),
        "checkpoint_count": len(markers),
        "projection_groups_at_checkpoint": len(groups),
    }, rows, prefix


def expected_rows(reference):
    lines = iter(reference.read_text().splitlines())
    next(lines)
    for head in range(32):
        assert int(next(lines).split()[0]) == head
        for _ in range(4):
            rank, _, count, value = next(lines).split()
            yield (head, int(rank), int(count)), value.encode() + b"\n"
    assert next(lines, None) is None


def checked_output_prefix(path, rows):
    expected = b"".join(rows)
    with path.open("rb") as source:
        assert source.read(len(expected)) == expected, path
    return expected


def trim_output(path, expected, discarded):
    """Retain only saved rows. Xcelium reopens an existing output in append mode."""
    with path.open("r+b") as stream:
        assert stream.read(len(expected)) == expected, path
        remainder = stream.read()
        if remainder:
            with discarded.open("xb") as archive:
                archive.write(remainder)
            stream.truncate(len(expected))
    return len(remainder)


def projection_prefix(plan, fixture, prefix):
    """Verify the chronological batch and group prefix, including sparse reads."""
    schedule = WORK / "projection_commands.txt"
    activation = fixture / "activation.hex"
    assert digest(schedule) == plan["schedule_sha256"]
    assert digest(activation) == plan["evidence_sha256"][str(activation.relative_to(ROOT))]
    words = [bool(int(word, 16)) for word in activation.read_text().splitlines()]
    words_per_token = 256
    assert len(words) == 409 * words_per_token
    commands = schedule.read_text().splitlines()
    assert len(commands) == plan["projection_commands"]

    expected = []
    skipped_by_batch = {}
    for command in commands:
        group, first, count = map(int, command.split()[:3])
        if first == 0 and group > 0:
            expected.append(f"UNSEEDED_PACKET_PROJECTION_GROUP_PASS group={group - 1} vectors=409")
        key = first, count
        if key not in skipped_by_batch:
            active = words[first * words_per_token:(first + count) * words_per_token]
            skipped_by_batch[key] = sum(not any(active[column::words_per_token])
                                        for column in range(words_per_token))
        skipped = skipped_by_batch[key]
        reads = 64 * (words_per_token - skipped)
        expected.append(f"UNSEEDED_PACKET_PROJECTION_BATCH_PASS group={group} slot={first}"
                        f" tokens={count} weights={reads} skipped_columns={skipped}")
    expected.append(f"UNSEEDED_PACKET_PROJECTION_GROUP_PASS group={group} vectors=409")

    observed = PROJECTION.findall(prefix)
    if observed != expected[:len(observed)]:
        raise ValueError("Saved projection batch or group trace disagrees with the trained schedule")
    batches = [tuple(map(int, match.groups())) for line in observed if (match := BATCH.fullmatch(line))]
    return {
        "projection_batches_at_checkpoint": len(batches),
        "projection_vectors_at_checkpoint": sum(count for _, _, count, _, _ in batches),
        "projection_weight_reads_at_checkpoint": sum(reads for _, _, _, reads, _ in batches),
        "projection_skipped_columns_at_checkpoint": sum(skipped for _, _, _, _, skipped in batches),
    }


def recovery_time(folder):
    match = RECOVERY_FOLDER.fullmatch(folder.name)
    assert folder.resolve() == WORK / folder.name and match is not None
    return int(match[1])


def previous_recovery(recovery, definition):
    name = definition.get("source_recovery")
    if name is None:
        return None
    assert RECOVERY_FOLDER.fullmatch(name), name
    previous = WORK / name
    assert recovery_time(previous) < recovery_time(recovery)
    return previous


def verify_stopped_log(status_path, text, status_hash=None):
    content = status_path.read_bytes()
    if status_hash is not None:
        assert sha256(content).hexdigest() == status_hash
    status = json.loads(content)
    assert status["exit_status"] != 0 or status["stop_reason"], "Preserve the successful run"
    assert status["log_sha256"] == sha256(text.encode()).hexdigest()
    assert not re.search(r"\*[EF],", text), "Diagnose the simulator error before resuming"


def resumed_checkpoint_text(recovery, initial_text, prepared):
    """Reconstruct all committed segments before the most recent snapshot load."""
    when = recovery_time(recovery)
    definition = json.loads((recovery / "prepared_recovery.json").read_text())
    previous = previous_recovery(recovery, definition)
    if previous is None:
        verify_stopped_log(NATIVE / "native_status.json", initial_text)
        source_text = initial_text
    else:
        source_text, _ = resumed_checkpoint_text(previous, initial_text, prepared)
        verify_stopped_log(previous / "resume_status.json", (previous / "resume.log").read_text(),
                           definition["source_status_sha256"])
    initial, _, prefix = checkpoint_prefix(source_text)
    assert initial["checkpoint_time_ns"] == when
    assert definition["state"] == "checkpoint_output_prepared_for_restore"
    assert all(definition[key] == value for key, value in initial.items())
    assert definition["cold_netlist_sha256"] == prepared["cold_netlist_sha256"]
    archived = recovery / "checkpoint_prefix.log"
    assert digest(archived) == definition["replay_prefix_sha256"] == sha256(prefix.encode()).hexdigest()
    plan = definition["restore"]
    assert plan["driver_sha256"] == digest(DRIVER)
    snapshot = initial["snapshot"]
    expected_index = str(initial["checkpoint_count"] - 1)
    assert plan["environment"] == {"TRI_ORACLE_REPLAY_FROM_CHECKPOINT": expected_index}
    log = recovery / "resume.log"
    tail = log.read_text()
    assert re.findall(r"(?m)^Loading snapshot (\S+)\s+\.+ Done$", tail) == [snapshot]
    assert re.findall(r"(?m)^TRI_UNSEEDED_PACKET_RESTORE (\d+)$", tail) == [expected_index]
    assert f"\t-r {snapshot}\n" in tail and f"\t-input {DRIVER}\n" in tail
    assert f"\t-log {log.resolve()}\n" in tail
    return prefix + tail, initial["checkpoint_time_ns"]


def checkpoint_artifacts(recovery=None):
    prepared = json.loads((NATIVE / "prepared_native.json").read_text())
    plan_path = WORK / "prepared_schedule.json"
    assert digest(plan_path) == prepared["schedule_receipt_sha256"]
    plan = json.loads(plan_path.read_text())
    fixture = ROOT / plan["prepared_fixture"]
    source = fixture / "rows.txt"
    assert digest(source) == plan["evidence_sha256"][str(source.relative_to(ROOT))]
    driver = WORK / "checkpoint.tcl"
    assert digest(driver) == prepared["evidence_sha256"][str(driver.relative_to(ROOT))]
    testbench = WORK / "layer_tb.sv"
    assert digest(testbench) == prepared["evidence_sha256"][str(testbench.relative_to(ROOT))]
    log = NATIVE / "xrun.log"
    transcript = log.read_text()
    if recovery is not None:
        transcript, restored_at = resumed_checkpoint_text(recovery, transcript, prepared)
    facts, rows, prefix = checkpoint_prefix(transcript)
    if recovery is not None:
        facts["restored_from_time_ns"] = restored_at
    facts.update(projection_prefix(plan, fixture, prefix))
    expected = list(expected_rows(source))
    assert rows == [key for key, _ in expected[:len(rows)]]
    output = NATIVE / "attention.hex"
    validated = checked_output_prefix(output, (value for _, value in expected[:len(rows)]))
    if facts["projection_groups_at_checkpoint"] == 40:
        assert digest(NATIVE / "attention.hex.projections") == plan["evidence_sha256"][
            str((fixture / "expected.hex").relative_to(ROOT))]
    facts.update(cold_netlist_sha256=prepared["cold_netlist_sha256"],
                 replay_prefix_sha256=sha256(prefix.encode()).hexdigest(),
                 rows_at_checkpoint=len(rows), committed_output_bytes=len(validated),
                 committed_output_sha256=sha256(validated).hexdigest())
    return facts, prefix, validated


def restore_invocation(prepared, facts, log):
    """Use the original simulator and limits with a new log and the saved state."""
    checkpoint_index = facts["checkpoint_count"] - 1
    slot = "checkpoint_b" if checkpoint_index % 2 else "checkpoint_a"
    assert facts["snapshot"] == f"worklib.{slot}:sv"
    assert 0 <= checkpoint_index < 140
    command = prepared["command"]
    launcher = command[:command.index("-64bit")]
    assert launcher[-1] == "/opt/cadence/bin/xrun"
    assert not log.exists(), log
    return {
        "command": [*launcher, "-64bit", "-r", facts["snapshot"],
                    "-input", str(DRIVER), "-log", str(log)],
        "environment": {"TRI_ORACLE_REPLAY_FROM_CHECKPOINT": str(checkpoint_index)},
        "driver_sha256": digest(DRIVER),
    }


def prepare_recovery(previous=None):
    """Prepare files for a stopped run. Preserve the full trace and unsaved output."""
    with LOCK.open("r") as lane:
        fcntl.flock(lane, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if previous is None:
            status = NATIVE / "native_status.json"
            log = NATIVE / "xrun.log"
        else:
            recovery_time(previous)
            status = previous / "resume_status.json"
            log = previous / "resume.log"
        verify_stopped_log(status, log.read_text())
        facts, prefix, rows = checkpoint_artifacts(previous)
        recovery = WORK / f"recovery_after_{facts['checkpoint_time_ns']}ns"
        if previous is not None:
            assert recovery_time(previous) < recovery_time(recovery), "No newer saved checkpoint to resume"
            facts.update(source_recovery=previous.name, source_status_sha256=digest(status))
        prepared = json.loads((NATIVE / "prepared_native.json").read_text())
        facts["restore"] = restore_invocation(prepared, facts, recovery / "resume.log")
        recovery.mkdir()
        (recovery / "checkpoint_prefix.log").write_text(prefix)
        discarded = trim_output(NATIVE / "attention.hex", rows, recovery / "unsaved_attention.hex")
        projections = NATIVE / "attention.hex.projections"
        if facts["projection_groups_at_checkpoint"] < 40 and projections.exists():
            projections.rename(recovery / "unsaved_projection.hex")
        facts.update(discarded_attention_bytes=discarded, state="checkpoint_output_prepared_for_restore")
        (recovery / "prepared_recovery.json").write_text(json.dumps(facts, indent=2, sort_keys=True) + "\n")
        return facts


def verify(recovery=None):
    facts, _, _ = checkpoint_artifacts(recovery)
    return facts


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    parser = ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--prepare-recovery", action="store_true", help="Trim outputs of a stopped run")
    modes.add_argument("--resume-directory", type=Path, help="Check the latest checkpoint across a restart")
    parser.add_argument("--source-recovery", type=Path, help="Prepare a new restore after this stopped segment")
    args = parser.parse_args()
    if args.source_recovery is not None and not args.prepare_recovery:
        parser.error("--source-recovery requires --prepare-recovery")
    print(json.dumps(prepare_recovery(args.source_recovery) if args.prepare_recovery else verify(args.resume_directory),
                     indent=2, sort_keys=True))
