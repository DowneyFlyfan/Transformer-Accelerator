"""Verify the active physical replay's trained projection and residual operands."""

import argparse
import json
from pathlib import Path
import struct

import torch

from audit_tri_oracle_placed_chip_boundary import digest
from prepare_tri_oracle_booth_feedforward_ingress import ROOT, STRIPS_PER_TOKEN, TAG, TOKENS, read_hex
from run_tri_oracle_booth_feedforward_replay import verify_inputs


REPLAY = Path("records/tri_oracle_corrected_booth_feedforward_replay_preflight.json")
GROUPED = Path("records/tri_oracle_grouped_reset_replay.json")
EARLIER = Path("records/tri_oracle_layer10_mapped_projection_residual.json")
NORMALIZATION = Path("records/tri_oracle_layer10_residual_normalization.json")
LANES = 8


def decode_lanes(word, bits):
    mask, sign = (1 << bits) - 1, 1 << (bits - 1)
    return [(((word >> (lane * bits)) & mask) ^ sign) - sign for lane in range(LANES)]


def decode_transport(words):
    assert words[:3] == [TAG & 0xffff, TAG >> 16, 0]
    remaining = iter(words[3:])
    descriptor = []
    for index in range(15):
        fields = [next(remaining) for _ in range(4)]
        marker = 0x30000 if index == 14 else 0x10000
        assert fields[0] & 0x30000 == marker
        assert all(field < 0x10000 for field in fields[1:])
        descriptor.extend([fields[0] & 0xffff, *fields[1:]])
    payload = sum(field << (16 * index) for index, field in enumerate(descriptor))
    residuals, shifts, gamma = [], [], []
    for _ in range(TOKENS):
        for _ in range(STRIPS_PER_TOKEN):
            assert next(remaining) == 0x2a678
            fields = [next(remaining) for _ in range(18)]
            assert all(field < 0x10000 for field in fields)
            packed = sum(field << (16 * index) for index, field in enumerate(fields))
            assert packed >> 285 == 0
            residuals.append(decode_lanes(packed, 35))
            shifts.append((packed >> 280) & 31)
        for _ in range(STRIPS_PER_TOKEN):
            assert next(remaining) == 0x2a679
            coefficients = [next(remaining) for _ in range(8)]
            assert all(field < 0x10000 for field in coefficients)
            gamma.append(sum(value << (16 * index) for index, value in enumerate(coefficients)))
    assert next(remaining, None) is None
    return payload, residuals, shifts, gamma


def round_clip(values, dropped, bits):
    """Round signed integer lanes [token, strip, lane] to nearest, ties away from zero."""
    magnitude = (values.abs() + (1 << (dropped - 1))) >> dropped
    signed = torch.where(values < 0, -magnitude, magnitude)
    return signed.clamp(-(1 << (bits - 1)), (1 << (bits - 1)) - 1)


@torch.inference_mode()
def residual_codes(residuals, projected, shifts):
    """Combine [token, strip, lane] signed codes with per-strip [token, strip, 1] shifts."""
    total = residuals + torch.bitwise_left_shift(projected, shifts + 6)
    assert int(total.abs().max()) < (1 << 45)
    return round_clip(total, 6, 29), round_clip(total, 19, 16)


def verify(work, archive):
    packets = verify_inputs(work, archive)
    evidence = {}

    def pin(path, expected=None):
        actual = digest(path)
        assert expected is None or actual == expected, path
        evidence[str(path.relative_to(ROOT))] = actual
        return path

    proof, grouped, earlier, normalization = (
        json.loads(pin(ROOT / path).read_text()) for path in (REPLAY, GROUPED, EARLIER, NORMALIZATION)
    )
    path = work / "prepared.json"
    manifest = json.loads(pin(path, proof["evidence_sha256"][str(path.relative_to(ROOT))]).read_text())
    assert manifest["cold_netlist_sha256"] == proof["cold_netlist_sha256"]
    handoff = archive.parent
    original_packets = handoff / "output.hex"
    old_projection = pin(original_packets, earlier["evidence_sha256"][str(original_packets.relative_to(ROOT))])
    current_projection = pin(packets, grouped["evidence_sha256"][str(packets.relative_to(ROOT))])
    assert old_projection.read_bytes() == current_projection.read_bytes()
    assert grouped["native"]["xcelium_exit_status"] == 0 and earlier["exact_projection_codes"] == 4096
    assert manifest["positions"] == earlier["positions"] == [607, 608]

    original_proofs = normalization["evidence_sha256"]
    normal_path = pin(handoff / "layer10_normalization/receipt.json", original_proofs["normalization_receipt"])
    residual_dir = handoff / "layer10_residual"
    residual_path = pin(residual_dir / "receipt.json", original_proofs["residual_receipt"])
    normal_receipt, residual_receipt = (json.loads(path.read_text()) for path in (normal_path, residual_path))
    assert normal_receipt["positions"] == residual_receipt["positions"] == manifest["positions"]
    residual = pin(residual_dir / "residual_f32.bin", residual_receipt["residual_sha256"])
    norm_input = pin(ROOT / manifest["external_inputs"]["NORM_INPUTS"], normal_receipt["output_sha256"]["norm_input.hex"])
    handoff_rows = pin(ROOT / manifest["external_inputs"]["WRITEBACK"], manifest["input_sha256"]["WRITEBACK"])
    flits = pin(work / "host_input.hex", manifest["output_sha256"]["host_input.hex"])
    payload, residuals, shifts, gamma = decode_transport(read_hex(flits, manifest["host_flits"], 18))
    assert [payload >> shift & 31 for shift in (950, 955)] == manifest["writeback_shifts"]
    values = struct.unpack("<4096f", residual.read_bytes())
    assert [lane for row in residuals for lane in row] == [int(value * (1 << 32)) for value in values]
    scales = normal_receipt["projection_output_exponents"]
    assert len(scales) == 32
    assert shifts == [scale + 26 for _ in range(TOKENS) for scale in scales for _ in range(8)]
    norms = read_hex(norm_input, TOKENS * STRIPS_PER_TOKEN, 256)
    assert gamma == [row >> 128 for row in norms]

    raw_packets = [value.to_bytes(64, "little") for value in read_hex(packets, 64, 512)]
    interleaved = [b"".join(raw_packets[token::TOKENS]) for token in range(TOKENS)]
    assert torch.cuda.mem_get_info()[0] >= 1024**3
    torch.cuda.set_per_process_memory_fraction(0.10)
    # Archived, token-major [token, strip, lane] projection and residual inputs.
    shape = TOKENS, STRIPS_PER_TOKEN, LANES
    projected = torch.tensor(struct.unpack("<4096b", b"".join(interleaved)), dtype=torch.int64,
                             device="cuda").reshape(shape)
    widened = torch.tensor(residuals, dtype=torch.int64, device="cuda").reshape(shape)
    scale_shifts = torch.tensor(shifts, dtype=torch.int64, device="cuda").reshape(TOKENS, STRIPS_PER_TOKEN, 1)
    # Both expected outputs are fixture codes with axes [token, strip, lane].
    rows = read_hex(handoff_rows, TOKENS * STRIPS_PER_TOKEN, 621)
    expected_bypass = torch.tensor([decode_lanes(row, 29) for row in rows], device="cuda").reshape(shape)
    expected_norm = torch.tensor([decode_lanes(row, 16) for row in norms], device="cuda").reshape(shape)
    bypass, norm = residual_codes(widened, projected, scale_shifts)
    assert torch.equal(bypass, expected_bypass) and torch.equal(norm, expected_norm)

    swapped = projected.clone()  # Same axes. Exchange just the first group of 64 projection values.
    swapped[:, :8, :] = projected.flip(0)[:, :8, :]
    bad_bypass, bad_norm = residual_codes(widened, swapped, scale_shifts)
    mismatches = (int((bad_bypass != expected_bypass).sum()), int((bad_norm != expected_norm).sum()))
    assert all(mismatches)
    pin(Path(__file__).resolve())
    return {
        "state": "active_booth_feedforward_projection_and_residual_handoff_verified_on_host_gpu",
        "cold_netlist_sha256": manifest["cold_netlist_sha256"],
        "source_buffered_netlist_sha256": grouped["buffered_netlist_sha256"],
        "positions": manifest["positions"],
        "identical_archived_projection_packets": len(raw_packets),
        "decoded_residual_stream_values": widened.numel(),
        "exact_bypass_values": bypass.numel(),
        "exact_normalization_input_values": norm.numel(),
        "swapped_projection_packet_mismatches": {"bypass": mismatches[0], "normalization_input": mismatches[1]},
        "gpu": torch.cuda.get_device_name(),
        "peak_gpu_bytes": torch.cuda.max_memory_allocated(),
        "scope": "Host verification of the placed-chip replay's operand flits and captured projection data. The projection "
                 "packets came from older mapped hardware. This verifies continuity at the replay stimulus boundary.",
        "evidence_sha256": evidence,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args()
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").is_file()
    print(json.dumps(verify(args.work.resolve(), args.archive.resolve()), indent=2, sort_keys=True))
