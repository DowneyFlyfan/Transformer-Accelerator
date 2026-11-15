"""Encode paired and down-projection images for the trained native replay."""

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
import os
from pathlib import Path
import sys

from audit_tri_oracle_placed_chip_boundary import digest


STREAMING = Path(".cache/model_reference/lossless_weight_burst_probe/streaming_probe/aligned")
PAIR_PAYLOAD_BASE = 0x1000000000
DOWN_PAYLOAD_BASE = 0x1100000000
SLOT_BYTES = 8192


def pair_tiles(source):
    length = 5632 * 2048
    assert len(source) == 2 * length
    for row_group in range(0, 704, 2):
        for part in range(4):
            for strip in range(2):
                yield tuple(source[offset:offset + 2048]
                            for matrix in (0, length)
                            for row in (row_group, row_group + 1)
                            for offset in (matrix + 2048 * (8 * row + 2 * part + strip),))


def down_tiles(source):
    assert len(source) == 2048 * 5632
    for bank in range(64):
        for part in range(4):
            for strip in range(6):
                first_word = part * 176 + strip * 32
                count = min(32, 176 - strip * 32)
                yield tuple(source[offset:offset + count * 64]
                            for group in range(4)
                            for offset in (64 * ((bank * 4 + group) * 704 + first_word),))


def words(groups):
    assert len({len(group) for group in groups}) == 1
    for offset in range(0, len(groups[0]), 64):
        yield tuple(group[offset:offset + 64] for group in groups)


def encode_tile(groups):
    # Reuse the established image format and a separate software decoder.
    from make_stream_fixture import encode_pair
    from verify_stream_images import decode_word

    raw = b"".join(word for row in words(groups) for word in row)
    encoded = b"".join(piece for row in words(groups)
                       for piece in (encode_pair(*row[:2]), encode_pair(*row[2:])))
    if len(encoded) >= len(raw):
        return raw, len(raw), True
    cursor = 0
    for row in words(groups):
        for group in range(0, 4, 2):
            w0, n0, w1, n1 = encoded[cursor:cursor + 4]
            cursor += 4
            for width, length, expected in ((w0, n0, row[group]), (w1, n1, row[group + 1])):
                decoded = bytes(decode_word(width, encoded[cursor:cursor + length]))
                assert decoded == expected
                cursor += (length + 3) & ~3
    assert cursor == len(encoded)
    return encoded, len(raw), False


def write_image(pool, name, tiles, base, output):
    raw_count = compressed_count = payload_beats = 0
    with (output / f"{name}_index.bin").open("xb") as index, (
        output / f"{name}_payload.bin"
    ).open("xb") as payload:
        for data, raw_bytes, bypass in pool.map(encode_tile, tiles, chunksize=8):
            offset = payload.tell()
            assert 2176 <= len(data) <= raw_bytes <= SLOT_BYTES
            entry = (base + offset) | (len(data) << 64) | (int(bypass) << 78)
            index.write(entry.to_bytes(64, "little"))
            payload.write(data.ljust(SLOT_BYTES, b"\x00"))
            raw_count += raw_bytes
            compressed_count += int(not bypass)
            payload_beats += (len(data) + 63) // 64
        return {"exact_bytes": raw_count, "payload_base": base, "encoded_tiles": compressed_count,
                "payload_beats": payload_beats, "index_entries": index.tell() // 64}


def main():
    assert __debug__, "Use Python assertions"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pair", type=Path)
    parser.add_argument("down", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    assert STREAMING.is_dir()
    sys.path.insert(0, str(STREAMING.resolve()))
    args.output.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(max_workers=len(os.sched_getaffinity(0))) as pool:
        paired = write_image(pool, "pair", pair_tiles(args.pair.read_bytes()),
                             PAIR_PAYLOAD_BASE, args.output)
        down = write_image(pool, "down", down_tiles(args.down.read_bytes()),
                           DOWN_PAYLOAD_BASE, args.output)
    assert paired["index_entries"] == 2816 and paired["exact_bytes"] == 2 * 5632 * 2048
    assert down["index_entries"] == 1536 and down["exact_bytes"] == 2048 * 5632
    sources = (args.pair, args.down, Path(__file__),
               STREAMING / "make_stream_fixture.py", STREAMING / "verify_stream_images.py")
    names = [args.output / f"{part}_{kind}.bin"
             for part in ("pair", "down") for kind in ("index", "payload")]
    result = {"state": "native_trained_weight_images_encoded_and_decoded_exactly",
              "pair": paired, "down": down, "sha256": {str(p): digest(p) for p in (*sources, *names)}}
    with (args.output / "image.json").open("x") as receipt:
        json.dump(result, receipt, indent=2, sort_keys=True)
        receipt.write("\n")
    print(json.dumps({"pair": paired, "down": down}), flush=True)


if __name__ == "__main__":
    main()
