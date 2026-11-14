"""Test signed attention-to-projection quantization in Xcelium."""
import argparse
import json
from pathlib import Path
import random
import re
import subprocess
from tempfile import TemporaryDirectory

from check_tri_oracle_paper300_gate import CONCURRENT_GROUP, sha
from run_tri_oracle_batch396_masks import GIB, check_memory
from tri_oracle_process_guard import terminate_process_group

ROOT = Path(__file__).resolve().parents[1]
MODULE = "tri_oracle_attention_projection_scale"
TOP = f"{MODULE}_tb"
GROUP = ROOT / CONCURRENT_GROUP
FIXTURE = GROUP / "trained_grouped_output_projection"
HANDOFF = FIXTURE / "native_attention_handoff"
SCHEDULE = GROUP / "trained_offload_benchmark_traffic"


def code(value, shift):
    rounded = ((abs(value) << shift) + 32767) // 65535
    return min(127, max(-128, -rounded if value < 0 else rounded))


def vector(value, shift, result):
    assert -(1 << 31) <= value < (1 << 31) and 0 <= shift <= 31
    return f"{(value & 0xFFFFFFFF) << 13 | shift << 8 | (result & 255):012x}"


def trained_vectors():
    receipt_path = HANDOFF / "receipt.json"
    receipt = json.loads(receipt_path.read_text())
    placement = ROOT / "records/tri_oracle_localized_native_full_chip_placement.json"
    assert receipt["candidate_sha256"] == json.loads(placement.read_text())["mapped_candidate_sha256"]
    assert receipt["state"] == "mapped_grouped_attention_to_output_projection_verified"
    assert receipt["native"]["native_exit_status"] == 0 and receipt["positions"] == [607, 608]
    routes, results, expected = HANDOFF / "routes.hex", SCHEDULE / "expected.hex", FIXTURE / "activation.hex"
    pins = {path: receipt["input_sha256"][str(path)] for path in (routes, results, expected)}
    assert all(sha(path) == digest for path, digest in pins.items())
    pins.update({path: sha(path) for path in (receipt_path, placement)})
    ordered = [None] * 64
    for route, line in zip(routes.read_text().splitlines(), results.read_text().splitlines(), strict=True):
        route = int(route, 16)
        if route == 0:
            continue
        assert route >> 11 == 1
        destination, shift = route & 63, (route >> 6) & 31
        assert ordered[destination] is None and len(line) == 512
        values = [int.from_bytes(bytes.fromhex(line[i:i+8]), "big", signed=True) for i in range(504, -1, -8)]
        ordered[destination] = [(value, shift, code(value, shift)) for value in values]
    assert all(row is not None for row in ordered)
    flattened = [item for row in ordered for item in row]
    expected_bytes = b"".join(bytes.fromhex(line)[::-1] for line in expected.read_text().splitlines())
    assert len(flattened) == 4096 and bytes(result & 255 for _, _, result in flattened) == expected_bytes
    return [vector(*item) for item in flattened], pins


def directed_vectors():
    seed = random.Random(316)
    for shift in range(32):
        values = {-(1 << 31), (1 << 31) - 1, -1, 0, 1}
        values.update(seed.randrange(-(1 << 31), 1 << 31) for _ in range(32))
        for output in range(1, 129):
            threshold = (output * 65535 - 32767 + (1 << shift) - 1) >> shift
            for magnitude in range(max(0, threshold - 1), threshold + 2):
                values.add(magnitude)
                values.add(-magnitude)
        yield from (vector(value, shift, code(value, shift)) for value in sorted(values))


def run(source, log, cell_model, mutate):
    assert Path("/.dockerenv").is_file()
    check_memory(8 * GIB)
    vectors, pins = trained_vectors()
    vectors.extend(directed_vectors())
    bench = ROOT / "verilog" / f"{TOP}.sv"
    pins.update({path: sha(path) for path in (source, bench, Path(__file__).resolve())})
    if cell_model is not None:
        pins[cell_model] = sha(cell_model)
    if mutate:
        vectors[0] = f"{int(vectors[0], 16) ^ 1:012x}"
    with TemporaryDirectory(prefix="projection_scale_xcelium_", dir=ROOT / ".cache") as temporary:
        directory = Path(temporary)
        fixture = directory / "vectors.hex"
        fixture.write_text("\n".join(vectors) + "\n")
        native_log = directory / "xrun.log"
        command = ["/usr/bin/prlimit", "--as=4294967296", "--", "/opt/cadence/bin/xrun", "-64bit",
                   "-sv", "-top", TOP, "-l", str(native_log), "-history_file", str(directory / "xrun.history")]
        if cell_model is not None:
            command.extend(["-nospecify", "-notimingchecks", str(cell_model)])
        command.extend([str(source), str(bench), f"+VECTORS={fixture}"])
        with log.open("x") as stream:
            child = subprocess.Popen(command, cwd=directory, stdout=stream, stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL, start_new_session=True)
            try:
                status = child.wait(timeout=60)
            finally:
                terminate_process_group(child, log_argument=str(native_log))
    assert all(sha(path) == digest for path, digest in pins.items())
    text = log.read_text()
    for line in text.splitlines():
        if line.startswith("PROJECTION_SCALE_") or re.search(r"\*[EF],", line):
            print(line, flush=True)
    if mutate:
        assert status and "PROJECTION_SCALE_MISMATCH vector=0" in text and "PROJECTION_SCALE_PASS" not in text
        return 0
    if status == 0:
        assert text.splitlines().count(f"PROJECTION_SCALE_PASS vectors={len(vectors)}") == 1
        assert not re.search(r"\*[EF],", text)
    return status


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "verilog" / f"{MODULE}.sv")
    parser.add_argument("--cell-model", type=Path)
    parser.add_argument("--mutate", action="store_true")
    parser.add_argument("log", type=Path)
    args = parser.parse_args()
    raise SystemExit(run(args.source.resolve(), args.log.resolve(),
                         args.cell_model.resolve() if args.cell_model else None, args.mutate))
