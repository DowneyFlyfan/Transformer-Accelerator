"""Portable exact-rational common-unit fixtures, without weights or datasets.

Run from the project root with a new output directory under .cache. Rows0..31
are token0's heads; rows32..63 are token1's. Each row contains a signed8 value
exponent above64 signed32 accumulators. Expected output is two signed9 units.
"""
from pathlib import Path
import argparse
import hashlib
import json


def unit(peak, zero):
    if peak == 0:
        return zero
    denominator = 127 * 65535
    shift = peak.bit_length() - denominator.bit_length()
    too_large = peak > denominator << shift if shift >= 0 else peak << -shift > denominator
    return shift + int(too_large)


def generate(destination):
    destination = Path(destination).resolve()
    if not destination.is_relative_to((Path.cwd()/'.cache').resolve()):
        raise ValueError('Generated fixtures must stay under project .cache')
    destination.mkdir(parents=True, exist_ok=False)
    denominator = 127 * 65535
    peaks = []
    for power in range(-22, 9):
        threshold = denominator >> -power if power < 0 else denominator << power
        peaks.append((threshold, threshold+1))
    peaks.extend([(2**31, 2**31-1), (0, 0), (0, 2**31)])
    operands, expected = [], []
    for pair in peaks:
        result = []
        for token, peak in enumerate(pair):
            result.append(unit(peak, [3, -5][token]))
            for head in range(32):
                packed = ((-peak & 0xffffffff) << (32*63)) if head == 31-token else 0
                operands.append(f'{packed:0514x}\n')
        expected.append(f'{((result[1] & 511) << 9) | (result[0] & 511):05x}\n')
    for name, lines in [('operands.hex', operands), ('expected.hex', expected)]:
        (destination/name).write_text(''.join(lines))
    receipt = dict(kind='portable_exact_common_unit_threshold_fixture', frames=len(peaks), head_rows=len(peaks)*64,
                   zero_units=[3, -5], source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   output_sha256={name:hashlib.sha256((destination/name).read_bytes()).hexdigest()
                                  for name in ['operands.hex', 'expected.hex']},
                   contains_model_data=False, rtl_verified=False, whole_chip_verified=False, paper_matching=False)
    (destination/'vectors.json').write_text(json.dumps(receipt, indent=2)+'\n')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', help='New output directory below .cache')
    print(json.dumps(generate(parser.parse_args().destination)))
