"""Interleave gate/up sign words into one 512-bit line per feature strip."""

import argparse
from itertools import batched
from pathlib import Path
import re


WORD = re.compile(r"[0-9a-fA-F]{16}")
PAIRS_PER_LINE = 4


def pack(gate_path, up_path, output):
    lines = 0
    with gate_path.open() as gate, up_path.open() as up, output.open("x") as packed:
        try:
            for pairs in batched(zip(gate, up, strict=True), PAIRS_PER_LINE):
                words = [word.strip() for pair in pairs for word in pair]
                if len(words) != 2 * PAIRS_PER_LINE or not all(WORD.fullmatch(word) for word in words):
                    raise ValueError(f"Incomplete or malformed sign line at index {lines}")
                # The first pair occupies the least significant 128 bits.
                packed.write("".join(reversed(words)) + "\n")
                lines += 1
            if not lines:
                raise ValueError("Sign planes are empty")
        except BaseException:
            output.unlink()
            raise
    return lines


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gate", type=Path)
    parser.add_argument("up", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print("Packed sign lines:", pack(args.gate, args.up, args.output))
