"""Build the ordered line-cache request control from the trained sign fixture."""

import argparse
from hashlib import file_digest
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GROUPS, STRIPS, TOKENS = 176, 256, 16
BASE = 0x0000000BFFFFFF00


def sha(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def fold(word, width):
    index = 0
    while word:
        index ^= word & ((1 << width) - 1)
        word >>= width
    return index


def run(entries, output):
    native = ROOT / ".cache/physical/sign_word_cache_native/trained_masks/receipt.json"
    norm = ROOT / ".cache/model_reference/batch403/norm.hex"
    proof = json.loads(native.read_text())
    assert sha(norm) == proof["input_sha256"][str(norm.relative_to(ROOT))]
    values = [int(word, 16) for word in norm.read_text().split()]
    assert len(values) == TOKENS * STRIPS * 8 and all(0 <= word < 65536 for word in values)
    signed = [word if word < 32768 else word - 65536 for word in values]
    active = [strip for token in range(TOKENS) for strip in range(STRIPS)
              if any(abs(value) > 768 for value in signed[(token*STRIPS+strip)*8:(token*STRIPS+strip+1)*8])]
    count = [0, 0, 0]  # Cache hits, primary misses and auxiliary misses.
    tags = [None] * entries
    with output.open("x") as stream:
        for group in range(GROUPS):
            for strip in active:
                word = (BASE >> 6) + group * STRIPS + strip
                index = fold(word, entries.bit_length() - 1)
                event = 0
                if tags[index] != word:
                    tags[index] = word
                    event = 1 if fold(word, 5) < (9 if entries == 128 else 8) else 2
                count[event] += 1
                stream.write(f"{(event << 64) | (word << 6):017x}\n")
    result = {"entries": entries, "requests": sum(count), "hits": count[0], "primary": count[1], "auxiliary": count[2],
              "input_sha256": {str(norm.relative_to(ROOT)): sha(norm), str(native.relative_to(ROOT)): sha(native)},
              "request_sha256": sha(output)}
    with output.with_suffix(".json").open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(result["requests"], result["primary"], result["auxiliary"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("entries", type=int, choices=(128, 256))
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    run(args.entries, args.output)
