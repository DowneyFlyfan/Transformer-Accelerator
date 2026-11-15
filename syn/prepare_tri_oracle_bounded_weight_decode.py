"""Specialize the shared weight decoder for the existing 64-byte tile record."""

import argparse
from pathlib import Path

from prepare_tri_oracle_early_weight_pairs import edit


def bounded_decoder(source):
    return edit(source, [
        ("module weight_decode_flush (", "module tri_oracle_bounded_weight_decode ("),
        ("  logic [511:0] decoded, literals, decoded_stage, literals_stage, assembled;",
         "  logic [511:0] decoded, decoded_stage, assembled;\n"
         "  // A tile body holds at most 64 bytes, including at least 32 code bytes.\n"
         "  logic [255:0] literals_stage;"),
        ("    literals = escapes;\n", ""),
        ("""      case (group_offset[group][5:3])
        0: pair = literals_stage[511:384];
        1: pair = literals_stage[447:320];
        2: pair = literals_stage[383:256];
        3: pair = literals_stage[319:192];
        4: pair = literals_stage[255:128];
        5: pair = literals_stage[191:64];
        6: pair = literals_stage[127:0];
        7: pair = {literals_stage[63:0],64'b0};""",
         """      case (group_offset[group][6:3])
        0: pair = literals_stage[255:128];
        1: pair = literals_stage[191:64];
        2: pair = literals_stage[127:0];
        3: pair = {literals_stage[63:0],64'b0};"""),
        ("        literals_stage <= literals;", "        literals_stage <= escapes[511:256];"),
        ("        invalid_width_stage <= !valid_width;",
         "        invalid_width_stage <= !valid_width || expected_escapes > 7'd32;"),
    ]).replace("invalid_width_stage", "invalid_input_stage")


def use_bounded_decoder(tile):
    return edit(tile, [("weight_decode_flush decoder (", "tri_oracle_bounded_weight_decode decoder (")])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ("baseline_decoder", "baseline_tile", "output"):
        parser.add_argument(argument, type=Path)
    args = parser.parse_args()
    decoder = bounded_decoder(args.baseline_decoder.read_text())
    tile = use_bounded_decoder(args.baseline_tile.read_text())
    for name, source in (("bounded_decoder.sv", decoder), ("bounded_tile.sv", tile)):
        with (args.output / name).open("x") as stream:
            stream.write(source)


if __name__ == "__main__":
    main()
