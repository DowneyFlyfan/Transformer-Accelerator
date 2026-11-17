"""Verify and prepare trained operands for the full placed-chip physical replay."""

import argparse
import json
from pathlib import Path

import numpy as np
import torch

from prepare_tri_oracle_booth_feedforward_ingress import (
    ROOT, STRIPS_PER_TOKEN, TAG, TOKENS, archived_descriptor, read_hex, read_json,
    segments, verify, write_hex,
)
from prepare_tri_oracle_channel_writeback import codes, writeback
from tri_oracle_integer_reference import _dot
from audit_tri_oracle_placed_chip_boundary import digest


HIDDEN = 2048
INTERMEDIATE = 5632


def writeback_packets(rows):
    packets = []
    for tile in range(0, HIDDEN, 160):
        for token in range(TOKENS):
            for start in range(tile, min(tile + 160, HIDDEN), 8):
                row = rows[token * STRIPS_PER_TOKEN + start // 8]
                final = token == TOKENS - 1 and start == HIDDEN - 8
                flags = (int(final) << 8) | (8 << 4) | token
                words = [0xa67e, *segments(TAG, 2), start, flags, *segments(row >> 493, 8)]
                packets.append(sum(word << (16 * index) for index, word in enumerate(words)))
    return packets


def physical_commands(descriptor, vectors, normalization, shifts):
    # The two 5-bit writeback shifts occupy the ten bits above the layer descriptor.
    descriptor |= shifts[0] << 950 | shifts[1] << 955
    command = [*segments(TAG, 2), 0]
    for index in range(15):
        word = segments(descriptor >> (64 * index), 4)
        word[0] |= 0x10000 | (0x20000 if index == 14 else 0)
        command.extend(word)
    for token in range(TOKENS):
        start = token * STRIPS_PER_TOKEN
        stop = start + STRIPS_PER_TOKEN
        for row in vectors[start:stop]:
            record = (row & ((1 << 280) - 1)) | (((row >> 344) & 31) << 280)
            command.extend([0x2a678, *segments(record, 18)])
        for row in normalization[start:stop]:
            command.extend([0x2a679, *segments(row >> 128, 8)])
    return command


def check_weights(archive, output):
    # Archive weights are [neuron, incoming feature] signed bytes. The packed
    # images store [neuron group / 8, feature group / 8, neuron lane, feature lane].
    gate = codes(archive / "fixture/gate.hex", 8, (INTERMEDIATE, HIDDEN))
    up = codes(archive / "fixture/up.hex", 8, (INTERMEDIATE, HIDDEN))
    down = codes(archive / "fixture/down.hex", 8, (HIDDEN, INTERMEDIATE))
    for path, matrices in (("pair.bin", (gate, up)), ("down.bin", (down,))):
        with (archive / path).open("rb") as packed:
            for weights in matrices:
                rows, columns = weights.shape
                tile_order = weights.reshape(rows // 8, 8, columns // 8, 8).transpose(0, 2, 1, 3)
                if packed.read(weights.size) != tile_order.tobytes():
                    raise ValueError(f"Packed weight mismatch in {path}")
            if packed.read(1):
                raise ValueError(f"Trailing bytes in {path}")

    # Signs are [32-neuron group, feature pair, branch, feature lane, neuron lane].
    sign_shape = (INTERMEDIATE // 32, HIDDEN // 2, 2, 32)
    gate_sign = gate.reshape(-1, 32, HIDDEN).transpose(0, 2, 1).reshape(sign_shape) < 0
    up_sign = up.reshape(-1, 32, HIDDEN).transpose(0, 2, 1).reshape(sign_shape) < 0
    sign_bits = np.stack((gate_sign, up_sign), axis=2)
    (output / "packed_sign.bin").write_bytes(np.packbits(sign_bits, axis=-1, bitorder="little").tobytes())
    return down


def check_results(archive, down, strips, shifts):
    # Intermediate [token, intermediate neuron] and down [output feature, intermediate neuron]
    # are archived int8 codes. Their exact GPU dot must reproduce [token, output feature] int32.
    intermediate = codes(archive / "fixture/intermediate.hex", 8, (TOKENS, INTERMEDIATE))
    expected_accum = codes(archive / "learned/expected.hex", 32, (TOKENS, HIDDEN))
    available_bytes, _ = torch.cuda.mem_get_info()
    if available_bytes < 1024**3:
        raise RuntimeError("The independent CUDA calculation requires 1 GiB free GPU memory")
    torch.cuda.set_per_process_memory_fraction(0.10)
    lhs = torch.from_numpy(intermediate).to("cuda")
    rhs = torch.from_numpy(down).to("cuda")
    with torch.inference_mode():
        accum = _dot(lhs, rhs).cpu().numpy()
    np.testing.assert_array_equal(accum, expected_accum)

    def strip_lanes(offset, bits):
        # Each archived strip encodes eight adjacent output features, low lane first.
        words = ((row >> (offset + lane * bits)) & ((1 << bits) - 1)
                 for row in strips for lane in range(8))
        sign = 1 << (bits - 1)
        return np.fromiter(((word ^ sign) - sign for word in words),
                           dtype=np.int64, count=TOKENS * HIDDEN).reshape(TOKENS, HIDDEN)

    np.testing.assert_array_equal(strip_lanes(232, 32), accum)
    np.testing.assert_array_equal(
        writeback(strip_lanes(0, 29), accum, np.asarray(shifts)[:, None]), strip_lanes(493, 16),
    )
    return {"exact_accumulators": accum.size, "exact_writeback_values": accum.size,
            "gpu": torch.cuda.get_device_name(), "gpu_peak_allocated_bytes": torch.cuda.max_memory_allocated()}


def prepare_native_sources(ingress, output, cold_hash):
    prior = read_json(ROOT / "records/tri_oracle_corrected_booth_streaming_packet.json")
    streaming = ingress.parent.parent / "streaming_packet"
    manifest_path = streaming / "prepared.json"
    verify(manifest_path, prior["evidence_sha256"][str(manifest_path.relative_to(ROOT))])
    manifest = read_json(manifest_path)
    if manifest["cold_netlist_sha256"] != cold_hash:
        raise ValueError("The physical pad peer was tested with a different cold netlist")
    originals = {}
    for name in ("attention_tb.sv", "bundle.sv"):
        path = streaming / name
        originals[name] = verify(path, manifest["evidence_sha256"][str(path.relative_to(ROOT))])
    bench = (streaming / "attention_tb.sv").read_text()
    start = bench.index("  logic host_rx_pad_valid")
    end = bench.index("  tb_memory_forward_rx peer", start)
    (output / "tri_oracle_booth_feedforward_pad_peer.svh").write_text(bench[start:end])
    fixture = ROOT / "verilog/tri_oracle_booth_feedforward_replay_tb.sv"
    bundle = (streaming / "bundle.sv").read_text()
    if not bundle.endswith(f'`include "{streaming / "attention_tb.sv"}"\n'):
        raise ValueError("Unexpected end of the validated streaming bundle")
    (output / "bundle.sv").write_text(bundle[:bundle.rfind("`include")] + f'`include "{fixture}"\n')
    return {**originals, "replay_testbench_sha256": digest(fixture)}


def prepare(archive, previous_launch, ingress, output):
    records = ROOT / "records"
    earlier = read_json(records / "tri_oracle_repaired_native_trained_writeback.json")
    launch = read_json(previous_launch)
    launch_hash = verify(previous_launch, earlier["evidence_sha256"][str(previous_launch.relative_to(ROOT))])
    config = read_json(archive / "prepared.json")
    scalar_files = ("prepared.json", "trained_tb.sv", "fixture/raw.hex", "fixture/shifts.hex",
                    "learned/shifts.hex", "learned/activation.hex",
                    "fixture/gate.hex", "fixture/up.hex", "fixture/down.hex", "fixture/intermediate.hex",
                    "learned/expected.hex", "down.bin", "pair.bin", "sign_reads.hex")
    inputs = {}
    previous = launch["inputs"]
    ingress_record = read_json(records / "tri_oracle_corrected_booth_feedforward_ingress.json")
    ingress_hash = verify(ingress, ingress_record["evidence_sha256"][str(ingress.relative_to(ROOT))])
    ingress_manifest = read_json(ingress)
    for name in scalar_files:
        path = archive / name
        expected = ingress_manifest["archived_input_sha256"].get(name, previous.get(str(path)))
        inputs[name] = verify(path, expected)
    external = {}
    for name in ("VECTORS", "NORM_INPUTS", "NORM_EXPECTED", "PACKETS", "WRITEBACK"):
        path, = (Path(arg.split("=", 1)[1]) for arg in launch["args"] if arg.startswith(f"+{name}="))
        external[name] = path
        inputs[name] = verify(path, previous[str(path)])

    vectors = read_hex(external["VECTORS"], 576, 709)
    normalization = read_hex(external["NORM_INPUTS"], 512, 256)
    writeback_rows = read_hex(external["WRITEBACK"], 512, 621)
    raw_rows = read_hex(archive / "fixture/raw.hex", 512, 128)
    if config["positions"] != [607, 608] or any(
            (row & ((1 << 128) - 1)) != raw for row, raw in zip(normalization, raw_rows, strict=True)):
        raise ValueError("The trained replay operands disagree on token order or raw residuals")
    shifts = [(writeback_rows[token * STRIPS_PER_TOKEN] >> 488) & 31 for token in range(TOKENS)]
    for index, row in enumerate(writeback_rows):
        if ((row >> 488) & 31) != shifts[index // STRIPS_PER_TOKEN] or (
                row & ((1 << 232) - 1)) != ((vectors[index] >> 349) & ((1 << 232) - 1)):
            raise ValueError(f"Projection residual or writeback scale mismatch at strip {index}")

    output.mkdir(parents=True, exist_ok=True)
    sources = prepare_native_sources(ingress, output, ingress_manifest["cold_netlist_sha256"])
    weights = check_weights(archive, output)
    metrics = check_results(archive, weights, writeback_rows, shifts)
    commands = physical_commands(archived_descriptor(archive, config), vectors, normalization, shifts)
    packets = writeback_packets(writeback_rows)
    write_hex(output / "host_input.hex", commands, 18)
    write_hex(output / "host_writeback.hex", packets, 208)
    result = {
        "state": "host_reference_verified_for_trained_placed_chip_feedforward_replay",
        "cold_netlist_sha256": ingress_manifest["cold_netlist_sha256"],
        "archived_launch_sha256": launch_hash,
        "mapped_ingress_manifest_sha256": ingress_hash,
        "positions": config["positions"],
        "frame_tag": f"{TAG:08x}",
        "writeback_shifts": shifts,
        "host_flits": len(commands),
        "writeback_packets": len(packets),
        "input_sha256": inputs,
        "external_inputs": {name: str(path.relative_to(ROOT)) for name, path in external.items()},
        "native_source_sha256": sources,
        "output_sha256": {name: digest(output / name)
                          for name in ("host_input.hex", "host_writeback.hex", "packed_sign.bin",
                                       "bundle.sv", "tri_oracle_booth_feedforward_pad_peer.svh")},
        **metrics,
    }
    (output / "prepared.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--previous-launch", type=Path, required=True)
    parser.add_argument("--ingress-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = prepare(args.archive.resolve(), args.previous_launch.resolve(),
                   args.ingress_manifest.resolve(), args.output.resolve())
    print(json.dumps({name: data[name] for name in ("state", "host_flits", "writeback_packets",
                                                   "exact_accumulators", "exact_writeback_values")}))
