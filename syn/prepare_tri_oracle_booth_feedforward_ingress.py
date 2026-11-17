"""Pack the audited trained layer 10 feed-forward input for the mapped ingress test."""

import argparse
import json
import mmap
import re
from pathlib import Path

from audit_tri_oracle_placed_chip_boundary import digest
from link_tri_oracle_indexed_whole_chip import spans


ROOT = Path(__file__).resolve().parents[1]
MODULES = (
    "tri_oracle_host_serial_pads",
    "tri_oracle_flit_from_pads_WORD_BITS18_PAD_BITS4",
    "tri_oracle_flit_to_pads_WORD_BITS17_PAD_BITS4",
    "tri_oracle_host_boundary_rx",
    "tri_oracle_host_command_link",
    "tri_oracle_indexed_chip_dispatch",
)
TAG = 0x39300001
STRIPS_PER_TOKEN = 256
TOKENS = 2


def read_json(path):
    return json.loads(path.read_text())


def verify(path, expected):
    actual = digest(path)
    if actual != expected:
        raise ValueError(f"Unexpected SHA-256 for {path}: {actual}")
    return actual


def read_hex(path, count, bits):
    values = [int(word, 16) for word in path.read_text().split()]
    if len(values) != count or any(not 0 <= word < 1 << bits for word in values):
        raise ValueError(f"Invalid count or word width in {path}")
    return values


def write_hex(path, words, bits):
    digits = (bits + 3) // 4
    path.write_text("".join(f"{word:0{digits}x}\n" for word in words))


def pack(fields):
    result = 0
    offset = 0
    for width, value in fields:
        if not 0 <= value < 1 << width:
            raise ValueError(f"{value} is outside the unsigned {width}-bit field")
        result |= value << offset
        offset += width
    return result


def segments(value, count):
    return [(value >> (16 * index)) & 0xffff for index in range(count)]


def archived_descriptor(archive, prepared):
    params = dict(re.findall(r"\.(TOKENS|HIDDEN|INTERMEDIATE|OUTPUTS|TRAINED)=(\d+)",
                             " ".join(prepared["argv"])))
    if params != {"TOKENS": "2", "HIDDEN": "2048", "INTERMEDIATE": "5632",
                  "OUTPUTS": "2048", "TRAINED": "1"}:
        raise ValueError(f"Unexpected archived geometry: {params}")
    original = (archive / "trained_tb.sv").read_text()
    bases = {name: int(value, 16) for name, value in re.findall(
        r"\b([A-Z_]+_BASE)=64'h([0-9a-f]+);", original)}
    stride = int(re.search(r"\bACT_STRIDE=HIDDEN\+(\d+)", original)[1]) + int(params["HIDDEN"])
    epsilon = int(re.search(r"cfg_epsilon_q16=TRAINED \? 32'd(\d+)", original)[1])
    shifts = read_hex(archive / "fixture/shifts.hex", TOKENS * 3, 6)
    activation = read_hex(archive / "learned/shifts.hex", TOKENS, 6)
    fields = [
        ("tokens", 5, TOKENS),
        ("input_features", 16, int(params["HIDDEN"])),
        ("intermediate_features", 16, int(params["INTERMEDIATE"])),
        ("output_features", 17, int(params["OUTPUTS"])),
        ("activation_base", 64, bases["ACT_BASE"]),
        ("activation_stride", 32, stride),
        ("gate_base", 64, bases["GATE_BASE"]),
        ("up_base", 64, bases["UP_BASE"]),
        ("down_base", 64, bases["DOWN_BASE"]),
        ("intermediate_base", 64, bases["SCRATCH_BASE"]),
        ("gate_sign_base", 64, bases["GATE_SIGN_BASE"]),
        ("up_sign_base", 64, bases["UP_SIGN_BASE"]),
        ("gate_shifts", 96, pack((6, value) for value in shifts[0::3])),
        ("up_shifts", 96, pack((6, value) for value in shifts[1::3])),
        ("down_shifts", 96, pack((6, value) for value in shifts[2::3])),
        ("activation_shifts", 96, pack((6, value) for value in activation)),
        ("epsilon_q16", 32, epsilon),
    ]
    order = ",".join("cfg_" + name for name, _, _ in reversed(fields))
    if f"descriptor=960'({{{order}}});" not in original or f"32'h{TAG:08x}" not in original:
        raise ValueError("The archived testbench uses a different descriptor or command tag")
    return pack((width, value) for _, width, value in fields)


def packet_fixture(descriptor, raw, gamma):
    flits = segments(TAG, 2) + [0]  # Start a feed-forward command using opcode zero.
    for word in range(15):
        payload = segments(descriptor >> (64 * word), 4)
        payload[0] |= 0x10000
        if word == 14:
            payload[0] |= 0x20000
        flits.extend(payload)

    stats, replay = [], []
    for token in range(TOKENS):
        start = token * STRIPS_PER_TOKEN
        token_strips = raw[start:start + STRIPS_PER_TOKEN]
        for strip, raw_word in enumerate(token_strips):
            last = strip == STRIPS_PER_TOKEN - 1
            flits.extend([0x2a67a + last, *segments(raw_word, 8)])
            stats.append(pack(((128, raw_word), (1, last))))
        for strip, raw_word in enumerate(token_strips):
            last = strip == STRIPS_PER_TOKEN - 1
            coefficients = gamma[8 * strip:8 * (strip + 1)]
            gamma_word = pack((16, value) for value in coefficients)
            flits.extend([0x2a67c + last, *segments(raw_word, 8), *coefficients])
            replay.append(pack(((128, raw_word), (128, gamma_word), (1, last))))
    return {"flits.hex": (flits, 18), "descriptor.hex": ([descriptor], 960),
            "stats.hex": (stats, 129), "replay.hex": (replay, 257)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--cold-netlist", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    archive = args.archive.resolve()
    netlist = args.cold_netlist.resolve()
    output = args.output.resolve()
    placement = read_json(ROOT / "records/tri_oracle_corrected_booth_buffered_placement_roundtrip.json")
    earlier = read_json(ROOT / "records/tri_oracle_layer10_mapped_feedforward.json")
    receipt_path = archive / "receipt.json"
    receipt_hash = verify(receipt_path, earlier["evidence_sha256"][str(receipt_path.relative_to(ROOT))])
    receipt = read_json(receipt_path)
    inputs = {}
    for name in ("prepared.json", "trained_tb.sv", "fixture/raw.hex", "fixture/shifts.hex",
                 "learned/gamma.hex", "learned/shifts.hex"):
        path = archive / name
        inputs[name] = verify(path, receipt["input_sha256"][str(path)])
    prepared = read_json(archive / "prepared.json")
    positions = earlier["positions"]
    if prepared["positions"] != positions or receipt["positions"] != positions:
        raise ValueError("Archived stimulus positions differ from the verified run")
    candidate_hash = verify(netlist, placement["evidence_sha256"][str(netlist.relative_to(ROOT))])
    descriptor = archived_descriptor(archive, prepared)
    raw = read_hex(archive / "fixture/raw.hex", TOKENS * STRIPS_PER_TOKEN, 128)
    gamma = read_hex(archive / "learned/gamma.hex", STRIPS_PER_TOKEN * 8, 16)

    output.mkdir(parents=True, exist_ok=True)
    with netlist.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as source:
        locations = spans(source)
        with (output / "mapped_ingress.v").open("wb") as mapped:
            for name in MODULES:
                start, end = locations[name]
                mapped.write(source[start:end] + b"\n")

    fixture = packet_fixture(descriptor, raw, gamma)
    for name, (words, bits) in fixture.items():
        write_hex(output / name, words, bits)
    prepared_ingress = {
        "cold_netlist_sha256": candidate_hash,
        "earlier_feedforward_receipt_sha256": receipt_hash,
        "positions": positions,
        "archived_input_sha256": inputs,
        "mapped_modules": list(MODULES),
        "fixture_counts": {name: len(words) for name, (words, _) in fixture.items()},
        "output_sha256": {name: digest(output / name) for name in (*fixture, "mapped_ingress.v")},
    }
    (output / "prepared.json").write_text(json.dumps(prepared_ingress, indent=2) + "\n")


if __name__ == "__main__":
    main()
