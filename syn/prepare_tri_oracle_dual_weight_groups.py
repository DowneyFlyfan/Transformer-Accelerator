"""Prepare the 1024-bit indexed parser and loader from the verified 512-bit RTL."""

import argparse
from pathlib import Path

from prepare_tri_oracle_early_weight_pairs import edit


def widen_tile(source):
    return edit(source, [
        ("module tri_oracle_early_pair_tile (", "module tri_oracle_dual_group_tile ("),
        ("output logic [511:0] write_data,", "output logic [1023:0] write_data,"),
        ("logic raw, ended, pair_half, pop,", "logic raw, ended, pop,"),
        ("// Both decoder outputs hold the pair until the second group is accepted.",
         "// Transfer both groups of the same weight word on one handshake."),
        ("(decode_error || (pair_half && write_ready))", "(decode_error || write_ready)"),
        ("assign write_group = {produced_pairs[0],pair_half};",
         "assign write_group = {produced_pairs[0],1'b0};"),
        ("assign write_data = decoded[pair_half];", "assign write_data = {decoded[1],decoded[0]};"),
        ("      pair_half <= 0;\n      produced_pairs <= 0;", "      produced_pairs <= 0;"),
        ("          pair_half <= 0;\n          produced_pairs <= 0;", "          produced_pairs <= 0;"),
        ("""            pair_half <= !pair_half;
            if (pair_half) begin
              produced_pairs <= produced_pairs + 1'b1;
              if ({1'b0,produced_pairs} == PAIR_COUNT - 7'd1) state <= Done;
            end""",
         """            produced_pairs <= produced_pairs + 1'b1;
            if ({1'b0,produced_pairs} == PAIR_COUNT - 7'd1) state <= Done;"""),
    ])


def widen_loader(source):
    return edit(source, [
        ("tri_oracle_early_pair_loader (", "tri_oracle_dual_group_loader ("),
        ("tri_oracle_early_pair_tile decoder", "tri_oracle_dual_group_tile decoder"),
        ("logic [511:0] load_data", "logic [1023:0] load_data"),
        ("logic [511:0] decoded_data", "logic [1023:0] decoded_data"),
        ("32'hff << {decoded_group,3'b0}", "32'hffff << {decoded_group,3'b0}"),
        ("    assign load_data[8*byte_id+:8] = decoded_data[511-8*byte_id-:8];",
         """    assign load_data[8*byte_id+:8] = decoded_data[511-8*byte_id-:8];
    assign load_data[512+8*byte_id+:8] = decoded_data[1023-8*byte_id-:8];"""),
    ])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("early_pair_rtl", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    widened = {
        "wide.sv": widen_tile((args.early_pair_rtl / "tile.sv").read_text()),
        "wide_loader.sv": widen_loader((args.early_pair_rtl / "loader.sv").read_text()),
    }
    args.output.mkdir()
    for name, source in widened.items():
        (args.output / name).write_text(source)


if __name__ == "__main__":
    main()
