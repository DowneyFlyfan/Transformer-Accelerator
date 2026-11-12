"""Pack row-major signed-byte weights for the 512-bit weight loader."""

import argparse
from binascii import unhexlify
from pathlib import Path


def pack_weights(source, destination, rows, features):
    """Write [row group, feature word, row lane, feature byte] in that order.

    A group has eight rows. A word has eight feature bytes per row. Byte zero
    of the file drives response bits [7:0] and lane zero drives bits [63:0].
    The source stores one two-digit hexadecimal byte per line.
    """
    if rows <= 0 or features <= 0 or rows % 8 or features % 8:
        raise ValueError("Rows and features must be positive multiples of eight")

    row_bytes = features * 3
    for group in range(rows // 8):
        lane_rows = []
        for lane in range(8):
            row = source.read(row_bytes)
            if len(row) != row_bytes or row[2::3] != b"\n" * features:
                raise ValueError(f"Invalid hexadecimal weight row {group * 8 + lane}")
            lane_rows.append(unhexlify(row.replace(b"\n", b"")))
        packed = bytearray(features * 8)
        for offset in range(0, features, 8):
            beat_offset = offset * 8
            for lane, row in enumerate(lane_rows):
                begin = beat_offset + lane * 8
                packed[begin:begin + 8] = row[offset:offset + 8]
        destination.write(packed)

    if source.read(1):
        raise ValueError("Trailing data after the final weight row")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--rows", type=int, required=True)
    parser.add_argument("--features", type=int, required=True)
    args = parser.parse_args()

    with args.source.open("rb") as source, args.destination.open("xb") as destination:
        try:
            pack_weights(source, destination, args.rows, args.features)
        except Exception:
            destination.close()
            args.destination.unlink()
            raise


if __name__ == "__main__":
    main()
