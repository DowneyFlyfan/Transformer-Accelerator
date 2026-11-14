"""Replay the archived layer-10 projection/residual boundary in Xcelium."""

import argparse
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
from tempfile import TemporaryDirectory

from check_tri_oracle_paper300_gate import CONCURRENT_GROUP, sha
from run_tri_oracle_batch396_masks import GIB, check_memory
from tri_oracle_process_guard import terminate_process_group


ROOT = Path(__file__).resolve().parents[1]
TOP = "tri_oracle_residual_add_tb"
GROUP = ROOT / CONCURRENT_GROUP / "trained_grouped_output_projection"
HANDOFF = GROUP / "native_attention_handoff"
NORM = HANDOFF / "layer10_normalization"
Q25_PER_Q13 = 1 << 12
PINNED_LAYER = ROOT / "records/tri_oracle_layer10_residual_normalization.json"


def rounded(value):
    return int(value.to_integral_value(rounding=ROUND_HALF_UP))


def pack(values, width):
    return sum((value & ((1 << width) - 1)) << (lane * width) for lane, value in enumerate(values))


def vector(residual, projection, shift, result):
    operands = (shift << 280) | (pack(projection, 8) << 216) | pack(residual, 27)
    return f"{(pack(result, 16) << 285) | operands:0104x}"


def fixture_inputs(native):
    projection_reference = GROUP / "expected.bin"
    record = json.loads(PINNED_LAYER.read_text())
    norm_path = NORM / "receipt.json"
    residual_receipt = HANDOFF / "layer10_residual/receipt.json"
    assert sha(norm_path) == record["evidence_sha256"]["normalization_receipt"]
    assert sha(residual_receipt) == record["evidence_sha256"]["residual_receipt"]
    norm = json.loads(norm_path.read_text())
    residual = json.loads(residual_receipt.read_text())
    assert norm["positions"] == residual["positions"] == [607, 608]
    bypass = residual_receipt.with_name("residual_f32.bin")
    inputs = NORM / "norm_input.hex"
    expected_outputs = NORM / "norm_expected.hex"
    pins = {
        projection_reference: norm["input_sha256"][str(projection_reference)],
        bypass: residual["residual_sha256"],
        inputs: norm["output_sha256"][inputs.name],
        expected_outputs: norm["output_sha256"][expected_outputs.name],
        norm_path: record["evidence_sha256"]["normalization_receipt"],
        residual_receipt: record["evidence_sha256"]["residual_receipt"],
    }
    assert norm["activation_exponents"] == [-6, -6]
    if native:
        receipt = HANDOFF / "receipt.json"
        current = json.loads(receipt.read_text())
        placement = ROOT / "records/tri_oracle_localized_native_full_chip_placement.json"
        assert current["candidate_sha256"] == json.loads(placement.read_text())["mapped_candidate_sha256"]
        assert current["state"] == "mapped_grouped_attention_to_output_projection_verified"
        assert current["native"]["native_exit_status"] == 0 and current["positions"] == norm["positions"]
        pins[receipt] = sha(receipt)
        dump = HANDOFF / "output.hex"
        pins[dump] = current["input_sha256"][str(dump)]
    assert all(sha(path) == digest for path, digest in pins.items())
    projection = projection_reference.read_bytes()
    if native:
        rows = dump.read_text().splitlines()
        assert len(rows) == 64 and all(re.fullmatch(r"[0-9a-f]{128}", row) for row in rows)
        reassembled = b"".join(bytes.fromhex(row)[::-1] for row in rows)
        assert reassembled == projection
        projection = reassembled
    projected = struct.unpack("4096b", projection)
    residual_codes = [rounded(Decimal.from_float(value) * 2**25)
                      for value in struct.unpack("<4096f", bypass.read_bytes())]
    assert all(-2**26 <= value < 2**26 for value in residual_codes)
    strips = []
    expected = inputs.read_text().splitlines()
    exponents = norm["projection_output_exponents"]
    for token in range(2):
        for head, exponent in enumerate(exponents):
            shift = 25 + exponent
            assert 0 <= shift <= 25
            for lane in range(0, 64, 8):
                index = token * 2048 + head * 64 + lane
                projection_index = (head * 2 + token) * 64 + lane
                expected_codes = struct.unpack("<8h", bytes.fromhex(expected[index // 8][32:])[::-1])
                strips.append(vector(residual_codes[index:index + 8], projected[projection_index:projection_index + 8],
                                     shift, expected_codes))
    assert len(strips) == 512
    return strips, pins, inputs, expected_outputs


def corners():
    strips = []
    bypass = [2047, 2048, -2047, -2048, 2049, -2049, 2**26 - 1, -2**26]
    for shift in (0, 1, 7, 11, 12, 15, 25, 31):
        for projection in ((0, 0, 0, 0, 0, 0, 127, -128), (-128, 127, 127, -128, -1, 1, -128, 127)):
            summed = [value + code * 2**shift for value, code in zip(bypass, projection, strict=True)]
            expected = [max(-32768, min(32767, rounded(Decimal(value) / Q25_PER_Q13))) for value in summed]
            strips.append(vector(bypass, projection, shift, expected))
    return strips


def run(source, native, output, mutate=False):
    assert __debug__ and Path("/.dockerenv").is_file()
    check_memory(8 * GIB)
    assert shutil.disk_usage(ROOT).free > 10 * GIB
    bench = ROOT / "verilog" / f"{TOP}.sv"
    normalization_sources = [ROOT / "verilog" / f"{name}.sv" for name in
                             ("tri_oracle_rmsnorm", "tri_oracle_affine_quantizer", "tri_oracle_rms_activation")]
    data, pins, norm_inputs, norm_expected = fixture_inputs(native)
    pins.update({path: sha(path) for path in (source, bench, *normalization_sources,
                                             PINNED_LAYER, Path(__file__).resolve())})
    with TemporaryDirectory(prefix="residual_add_xcelium_", dir=ROOT / ".cache") as temporary:
        work = Path(temporary)
        vectors = work / "vectors.hex"
        vectors.write_text("\n".join(data + corners()) + "\n")
        if mutate:
            packets = norm_expected.read_text().splitlines()
            packets[0] = f"{int(packets[0], 16) ^ 1:062x}"
            norm_expected = work / "norm_expected_mutated.hex"
            norm_expected.write_text("\n".join(packets) + "\n")
        native_log = work / "native.log"
        command = ["/usr/bin/prlimit", "--as=4294967296", "--", "/opt/cadence/bin/xrun",
                   "-64bit", "-sv", "-top", TOP, "-xmlibdirname", str(work / "xcelium.d"),
                   "-l", str(native_log), "-history_file", str(work / "history"),
                   *map(str, (*normalization_sources, source, bench)), f"+VECTORS={vectors}",
                   f"+NORM_INPUTS={norm_inputs}", f"+NORM_EXPECTED={norm_expected}"]
        with output.open("x") as stream:
            child = subprocess.Popen(command, cwd=work, stdin=subprocess.DEVNULL, stdout=stream,
                                     stderr=subprocess.STDOUT, start_new_session=True)
            try:
                status = child.wait(timeout=60)
            finally:
                terminate_process_group(child, log_argument=str(native_log))
    assert all(sha(path) == digest for path, digest in pins.items())
    text = output.read_text()
    print(f"Xcelium exit {status}: {output}", flush=True)
    for line in text.splitlines():
        if line.startswith("RESIDUAL_") or "*F," in line or "*E," in line:
            print(line)
    if mutate:
        assert status != 0 and "RESIDUAL_NORMALIZATION_MISMATCH word=0" in text
        assert "RESIDUAL_NORMALIZATION_PASS" not in text
        return 0
    if status == 0:
        assert text.splitlines().count("RESIDUAL_ADD_PASS fixture_words=512 corner_words=16") == 1
        assert text.splitlines().count("RESIDUAL_NORMALIZATION_PASS words=512") == 1
        assert not re.search(r"\*[EF],|Simulation terminated via \$fatal", text)
    return status


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "verilog/tri_oracle_residual_add.sv")
    parser.add_argument("--native-projection", action="store_true")
    parser.add_argument("--mutate-normalization", action="store_true")
    parser.add_argument("log", type=Path)
    args = parser.parse_args()
    raise SystemExit(run(args.source.resolve(), args.native_projection, args.log.resolve(), args.mutate_normalization))
