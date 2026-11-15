"""Replace the decoder definition used exclusively by the two widened tiles."""

import argparse
import mmap
from pathlib import Path
import re

from audit_tri_oracle_packed_weight_path import pins
from audit_tri_oracle_placed_chip_boundary import digest
from link_tri_oracle_dual_group_whole_chip import DECODER, WIDE_TILE
from link_tri_oracle_indexed_whole_chip import MODULE, module_at, signature, spans, stream_copy, update_instance


BOUNDED = "tri_oracle_bounded_weight_decode"


def replace_decoder(source, implementation, output, expected_source_sha256):
    assert digest(source) == expected_source_sha256
    mapped_index = spans(implementation)
    assert set(mapped_index) == {BOUNDED}
    mapped = module_at(implementation, mapped_index, BOUNDED)
    header = MODULE.match(mapped)
    assert header and header[1].decode() == BOUNDED
    with source.open("rb") as old, mmap.mmap(old.fileno(), 0, access=mmap.ACCESS_READ) as native:
        index = spans(native)
        assert BOUNDED not in index
        previous = module_at(native, index, DECODER)
        tile = module_at(native, index, WIDE_TILE)
        ports = signature(previous)
        assert signature(mapped) == ports
        users = [user.start() for user in re.finditer(rb"(?m)^[ \t]*" + DECODER.encode() + rb"\s+", native)]
        tile_start, tile_end = index[WIDE_TILE]
        assert sum(tile_start <= user < tile_end for user in users) == 2
        instances = [rf"\word_decoder[{word}].decoder" for word in range(2)]
        assert all(pins(tile, DECODER, instance).keys() == ports.keys() for instance in instances)

        if len(users) == 2:
            start, end = index[DECODER]
            replacement = mapped[:header.start(1)] + DECODER.encode() + mapped[header.end(1):]
        else:
            # Cold exports can retain the narrow parser definition as well.
            # Keep its decoder intact and bind only the widened parser.
            start, end = tile_start, tile_end
            replacement = tile
            for instance in instances:
                replacement = update_instance(replacement, DECODER, instance, replacement=BOUNDED)
            assert signature(tile) == signature(replacement)
        with output.open("xb") as linked:
            stream_copy(linked, native, 0, start)
            linked.write(replacement)
            stream_copy(linked, native, end, len(native))
            if len(users) > 2:
                linked.write(b"\n" + mapped + b"\n")
    print("BOUNDED_WEIGHT_DECODE_LINKED", digest(output), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "mapped_decoder", "output"):
        parser.add_argument(name, type=Path)
    parser.add_argument("source_sha256")
    args = parser.parse_args()
    replace_decoder(args.source, args.mapped_decoder.read_bytes(), args.output, args.source_sha256)


if __name__ == "__main__":
    main()
