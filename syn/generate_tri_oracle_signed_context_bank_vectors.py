"""Generate portable context-bank fixtures without model weights or datasets.

Run from the project root; outputs stay under .cache. The 64 rows cover both
directions and every five-bit shift, including both encodings of shift zero.
Expected bytes use exact integer ratios, independent of the hardware folding.
"""
from pathlib import Path
import argparse
import hashlib
import json
import random


def generate(destination):
    destination = Path(destination).resolve()
    if not destination.is_relative_to((Path.cwd() / ".cache").resolve()):
        raise ValueError("Generated fixtures must stay under project .cache")
    destination.mkdir(parents=True, exist_ok=False)
    randomizer = random.Random(20261121)
    operands, expected = [], []
    for row in range(64):
        right, shift = divmod(row, 32)
        values = [-2**31, -2**31 + 1, -65535, -1, 0, 1, 65535, 2**31 - 1]
        # Include reachable nearest-rounding thresholds and their neighbors.
        for code in [0, 1, 63, 126, 127, 128]:
            numerator = (2 * code + 1) * 65535
            if right and shift:
                boundary = numerator << (shift - 1)
            else:
                divisor = 1 << (shift + 1)
                boundary = (numerator + divisor - 1) // divisor
            for delta in [-1, 0, 1]:
                for sign in [-1, 1]:
                    value = sign * (boundary + delta)
                    if -2**31 <= value < 2**31:
                        values.append(value)
        values = values[:64]
        while len(values) < 64:
            values.append(randomizer.randrange(-2**31, 2**31))
        packed_input = packed_output = 0
        for lane, accumulator in enumerate(values):
            packed_input |= (accumulator & 0xffffffff) << (32 * lane)
            magnitude = abs(accumulator)
            numerator = magnitude if right else magnitude << shift
            denominator = 65535 << shift if right else 65535
            quotient, remainder = divmod(numerator, denominator)
            rounded = quotient + int(2 * remainder >= denominator)
            signed = -rounded if accumulator < 0 else rounded
            code = max(-128, min(127, signed))
            packed_output |= (code & 255) << (8 * lane)
        packed_input |= ((right << 5) | shift) << 2048
        operands.append(f"{packed_input:0514x}\n")
        expected.append(f"{packed_output:0128x}\n")
    for name, lines in [("operands.hex", operands), ("expected.hex", expected)]:
        (destination / name).write_text("".join(lines))
    receipt = {
        "kind": "portable_integer_boundary_fixture",
        "rows": 64,
        "scalar_codes": 4096,
        "shift_magnitudes": [0, 31],
        "directions": ["left", "right"],
        "seed": 20261121,
        "output_sha256": {
            name: hashlib.sha256((destination / name).read_bytes()).hexdigest()
            for name in ["operands.hex", "expected.hex"]
        },
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "model_data": False,
        "rtl_verified": False,
        "whole_chip_verified": False,
        "paper_matching": False,
    }
    (destination / "vectors.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", help="New output directory below .cache")
    print(json.dumps(generate(parser.parse_args().destination)))
