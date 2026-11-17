"""Verify the repaired chip's all-head replay with the trained reference cache."""

import argparse
from hashlib import sha256
import json
import re
from pathlib import Path

from prepare_tri_oracle_booth_packet_replay import ROOT, digest
from prepare_tri_oracle_reference_projection_attention import DECODE_ROW, PROMPT_ROW, SCOPE, prepare


ROW = re.compile(r"(?m)^REFERENCE_PROJECTION_ATTENTION_ROW_PASS head=(\d+) rank=(\d+) value_reads=(\d+)$")
HEAD = re.compile(r"(?m)^HOST_CONTROL_HEAD_PASS prediction=([0-9a-f]{12})$")
SUMMARY = re.compile(r"(?m)^REFERENCE_PROJECTION_ATTENTION_PASS (.+)$")


def read_reference(path):
    source = iter(path.read_text().splitlines())
    next(source)  # The image-token start position is consumed by the testbench.
    heads = []
    rows = []
    for head in range(32):
        head_id, _, _, inner, recent, streaming = map(int, next(source).split())
        if head_id != head or streaming != 0:
            raise ValueError(f"Unexpected reference classifier for head {head}")
        heads.append(f"{(head << 37) | (inner << 19) | (recent << 1):012x}")
        for _ in range(4):
            rank, _, requests, word = next(source).split()
            rows.append((head, int(rank), int(requests), word))
    if next(source, None) is not None:
        raise ValueError("Unexpected extra reference rows")
    return heads, rows


def verify_output(expected, output, *, complete):
    observed = output.splitlines()
    if len(observed) > len(expected) or complete and len(observed) != len(expected):
        raise ValueError(f"Unexpected attention output row count: {len(observed)}")
    for index, word in enumerate(observed):
        if re.fullmatch(r"[0-9a-f]{512}", word) is None or word != expected[index][3]:
            raise ValueError(f"Attention output mismatch at row {index}")
    return len(observed)


def verify(work, *, complete):
    prepared = work / "prepared.json"
    manifest = json.loads(prepared.read_text())
    if manifest["state"] != SCOPE:
        raise ValueError("Wrong attention run manifest")
    keys = ROOT / manifest["testbench_fixture"] / "rows.txt"
    native_log = work / "xrun.log"
    output = work / "attention.hex"
    heads, expected = read_reference(keys)
    count = verify_output(expected, output.read_text(), complete=complete)
    if not complete:
        return {"matched_attention_rows": count, "exact_accumulator_values": 64 * count}

    verified_work, _ = prepare(check=True)
    if verified_work != work:
        raise ValueError("Run path does not match the reproduced attention setup")
    status_path = work / "native_status.json"
    status = json.loads(status_path.read_text())
    if status["exit_status"] != 0 or status["stop_reason"] is not None:
        raise ValueError(f"Native attention replay failed: {status}")
    text = native_log.read_text()
    if re.search(r"\*(?:E|F|SE),", text) or text.count("Simulation complete via $finish(1)") != 1:
        raise ValueError("Native attention transcript did not finish cleanly")
    arguments = (f"-top {manifest['testbench_top']}", str(work / "bundle.sv"),
                 f"+FIXTURE={keys.parent}", f"+DUMP={output}")
    if any(f"\t{argument}\n" not in text for argument in arguments):
        raise ValueError("Native attention invocation does not match the manifest")
    if text.splitlines().count("REFERENCE_PROJECTION_CACHE_LOADED vectors=16360") != 1:
        raise ValueError("Reference projection cache load did not complete")
    if HEAD.findall(text) != heads or [tuple(map(int, row)) for row in ROW.findall(text)] != [
        (head, rank, requests) for head, rank, requests, _ in expected
    ]:
        raise ValueError("Wrong head predictions, row order or per-row attention request counts")
    summary, = SUMMARY.findall(text)
    totals = {name: int(value) for name, value in (part.split("=") for part in summary.split())}
    if (totals["rows"], totals["maps"], totals["context_words"], totals["value_reads"]) != (
        count, 576, 90, manifest["expected_external_value_requests"]
    ) or totals["wide"] <= 577:
        raise ValueError(f"Unexpected attention transfer totals: {totals}")
    return {
        "state": "repaired_chip_all_head_attention_replayed_with_reference_projections",
        "cold_netlist_sha256": manifest["cold_netlist_sha256"],
        "heads": len(heads),
        "matched_attention_rows": count,
        "exact_accumulator_values": 64 * count,
        "value_requests": totals["value_reads"],
        "native": status,
        "scope": "Physical host and memory ports of the repaired placed chip, with an externally supplied "
                 "reference projection cache. This replay exercises token merging, context restore, "
                 "head prediction and attention output.",
        "evidence_sha256": {str(path.relative_to(ROOT)): digest(path) for path in (
            prepared, native_log, output, status_path, Path(__file__).resolve(),
            Path(prepare.__code__.co_filename).resolve())},
    }


def verify_key_count_regression(work):
    reproduced, _ = prepare(check=True)
    assert reproduced == work
    original = work.with_name("reference_projection_attention")
    old_setup, new_setup = (json.loads((folder / "prepared.json").read_text()) for folder in (original, work))
    assert old_setup["cold_netlist_sha256"] == new_setup["cold_netlist_sha256"]
    assert old_setup["testbench_fixture"] == new_setup["testbench_fixture"]
    old_bench, new_bench = ((folder / "attention_tb.sv").read_text() for folder in (original, work))
    assert old_bench.count(PROMPT_ROW) == 1 and old_bench.replace(PROMPT_ROW, DECODE_ROW) == new_bench
    old_bundle, new_bundle = ((folder / "bundle.sv").read_text() for folder in (original, work))
    assert old_bundle.replace(str(original / "attention_tb.sv"), str(work / "attention_tb.sv")) == new_bundle
    new_log = work / "xrun.log"
    launch, marker, _ = new_log.read_text().partition("xcelium> run\n")
    assert marker and f"\t{work / 'bundle.sv'}\n" in launch

    old_status = original / "native_status.json"
    old_log = original / "xrun.log"
    old_capture = original / "attention.hex"
    status, transcript = json.loads(old_status.read_text()), old_log.read_text()
    assert status["exit_status"] == 2 and status["stop_reason"] is None
    assert transcript.splitlines().count("PACKET_ATTENTION_STALL expected=0005 last=0 actual=000d last=1") == 1
    assert [tuple(map(int, row)) for row in ROW.findall(transcript)] == [
        (0, 0, 1), (0, 204, 205), (0, 407, 408)]
    assert "Simulation terminated via $fatal(1)" in transcript
    manifest = ROOT / new_setup["testbench_fixture"] / "rows.txt"
    _, rows = read_reference(manifest)
    assert rows[3][:3] == (0, 408, 409)
    assert verify_output(rows, old_capture.read_text(), complete=False) == 3
    with (work / "attention.hex").open("rb") as capture:
        first_head = b"".join(capture.readline() for _ in range(4))
    assert verify_output(rows, first_head.decode(), complete=False) == 4
    assert first_head.startswith(old_capture.read_bytes())
    return {
        "state": "placed_chip_first_decode_attention_key_count_verified",
        "cold_netlist_sha256": new_setup["cold_netlist_sha256"],
        "head": 0,
        "decode_rank": 408,
        "prompt_keys": 408,
        "first_decode_keys": 409,
        "matched_attention_rows": 4,
        "exact_accumulator_values": 256,
        "capture_prefix_bytes": len(first_head),
        "capture_prefix_sha256": sha256(first_head).hexdigest(),
        "live_capture": str((work / "attention.hex").relative_to(ROOT)),
        "simulator_startup_sha256": sha256((launch + marker).encode()).hexdigest(),
        "scope": "Red-green hardware replay of the first decode descriptor with a reference projection cache. "
                 "The verified prefix covers one query head.",
        "evidence_sha256": {str(path.relative_to(ROOT)): digest(path) for path in (
            old_status, old_log, old_capture, original / "prepared.json", work / "prepared.json", manifest,
            Path(__file__).resolve(), Path(prepare.__code__.co_filename).resolve())},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--prefix", action="store_true")
    mode.add_argument("--key-count-regression", action="store_true")
    args = parser.parse_args()
    assert __debug__
    if Path.cwd() != ROOT or Path("/.dockerenv").is_file():
        parser.error("Verify attention from the project folder on the host")
    work = args.work.resolve()
    result = verify_key_count_regression(work) if args.key_count_regression else verify(work, complete=not args.prefix)
    print(json.dumps(result, indent=2, sort_keys=True))
