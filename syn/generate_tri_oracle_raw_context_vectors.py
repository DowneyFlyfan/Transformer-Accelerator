"""Portable raw-context storage/conversion vectors; no model data or fitting.

Three single-token frames contain32 heads of64 signed25-bit values. Output
words0..799 pack those values; words800..831 hold signed8 value exponents.
Exact integer ratios determine the common exponent and256 projection words.
"""
from pathlib import Path
import argparse
import hashlib
import json
import random


def generate(destination):
    destination = Path(destination).resolve()
    if not destination.is_relative_to((Path.cwd()/'.cache').resolve()):
        raise ValueError('Generated fixtures must stay under project .cache')
    destination.mkdir(parents=True, exist_ok=False)
    rng = random.Random(20261121)
    rows, raw_words, code_words, units = [], [], [], []
    for limit in [8000000, 4000000, 0]:
        values = [[rng.randrange(-limit, limit+1) if limit else 0 for _ in range(64)] for head in range(32)]
        exponents = [-9 if head < 8 else -8 for head in range(32)]
        minimum = min(exponents)
        peak = max(abs(value) << (exponents[head]-minimum) for head,row in enumerate(values) for value in row)
        common = 0
        if peak:
            denominator = 127*65535
            shift = peak.bit_length()-denominator.bit_length()
            too_large = peak > denominator << shift if shift >= 0 else peak << -shift > denominator
            common = minimum+shift+int(too_large)
        units.append(f'{common & 511:03x}\n')
        for head,row in enumerate(values):
            original = sum((value & 0xffffffff) << (32*lane) for lane,value in enumerate(row))
            rows.append(f'{((exponents[head] & 255) << 2048) | original:0514x}\n')
            packed = sum((value & ((1 << 25)-1)) << (25*lane) for lane,value in enumerate(row))
            raw_words.extend(f'{(packed >> (64*word)) & ((1 << 64)-1):016x}\n' for word in range(25))
            transfer = exponents[head]-common
            assert -31 <= transfer <= 31
            packed_codes = 0
            for lane,value in enumerate(row):
                numerator = abs(value) << transfer if transfer >= 0 else abs(value)
                denominator = 65535 if transfer >= 0 else 65535 << -transfer
                magnitude, remainder = divmod(numerator, denominator)
                magnitude += int(2*remainder >= denominator)
                code = max(-128, min(127, -magnitude if value < 0 else magnitude))
                packed_codes |= (code & 255) << (8*lane)
            code_words.extend(f'{(packed_codes >> (64*word)) & ((1 << 64)-1):016x}\n' for word in range(8))
        raw_words.extend(f'{exponent & 255:016x}\n' for exponent in exponents)
    outputs = {'rows.hex': rows, 'raw_words.hex': raw_words, 'code_words.hex': code_words, 'units.hex': units}
    for name, lines in outputs.items():
        (destination/name).write_text(''.join(lines))
    result = dict(kind='portable_lossless_raw_context_and_exact_conversion', frames=3, heads=32,
                  lanes=64, raw_words_each=832, code_words_each=256, seed=20261121,
                  source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  output_sha256={name:hashlib.sha256((destination/name).read_bytes()).hexdigest() for name in outputs},
                  contains_model_data=False, hardware_verified=False, whole_chip_verified=False, paper_matching=False)
    (destination/'vectors.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', help='New output directory below .cache')
    print(json.dumps(generate(parser.parse_args().destination)))
