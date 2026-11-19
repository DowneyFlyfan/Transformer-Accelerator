"""Correct the decode descriptor while retaining every real projection step."""
from pathlib import Path
from hashlib import sha256
import argparse
import json


PROMPT_ROW = "7'(shift), 11'd408, 11'(position), 5'(head)"
DECODE_ROW = "7'(shift), 11'(rank == Slots - 1 ? Slots : Slots - 1), 11'(position), 5'(head)"


def render_full_projection_bench(source):
    if source.count(PROMPT_ROW) != 1:
        raise ValueError('Expected one uncorrected row descriptor')
    # Prediction uses the prompt keys. The first decode row also sees its own
    # projected key, already written through the same projection transaction.
    return source.replace(PROMPT_ROW, DECODE_ROW, 1)


def prepare(source, output):
    before = source.read_bytes()
    after = render_full_projection_bench(before.decode('utf-8')).encode('utf-8')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as stream:
        stream.write(after)
    return dict(source=str(source.resolve()), output=str(output.resolve()),
        source_sha256=sha256(before).hexdigest(), output_sha256=sha256(after).hexdigest(),
        state='full_projection_testbench_decode_key_count_corrected',
        projection_flow_preserved=True, native_simulation_verified=False,
        paper_matching_verified=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.source, args.output), indent=2))
