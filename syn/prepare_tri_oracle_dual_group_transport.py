"""Prepare the 1024-bit controller while retaining the raw 512-bit reader."""

import argparse
from pathlib import Path

from prepare_tri_oracle_dual_weight_groups import widen_loader
from prepare_tri_oracle_early_weight_pairs import edit


def widen_lane(source):
    return edit(source, [
        ("module tri_oracle_early_pair_lane", "module tri_oracle_dual_group_lane"),
        ("logic [511:0] load_data", "logic [1023:0] load_data"),
        ("tri_oracle_early_pair_loader loader", "tri_oracle_dual_group_loader loader"),
    ])


def widen_transport(source):
    return edit(source, [
        ("registered 512-bit-per-lane", "registered 1024-bit-per-lane"),
        ("module tri_oracle_controlled_weight_transport", "module tri_oracle_dual_group_weight_transport"),
        ("logic [1:0][511:0] load_payload", "logic [1:0][1023:0] load_payload"),
        ("logic [1:0][511:0] stream_payload", "logic [1:0][1023:0] stream_payload"),
        ("  assign load_payload = state == Indexed ? stream_payload : rsp_data;\n", ""),
        ("    tri_oracle_early_pair_lane #",
         "    assign load_payload[lane] = state == Indexed ? stream_payload[lane] : {2{rsp_data[lane]}};\n"
         "    tri_oracle_dual_group_lane #"),
    ])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("early_pair_rtl", type=Path)
    parser.add_argument("transport_rtl", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    widened = {
        "wide_loader.sv": widen_loader((args.early_pair_rtl / "loader.sv").read_text()),
        "wide_lane.sv": widen_lane((args.early_pair_rtl / "lane.sv").read_text()),
        "wide_transport.sv": widen_transport(args.transport_rtl.read_text()),
    }
    args.output.mkdir()
    for name, source in widened.items():
        (args.output / name).write_text(source)


if __name__ == "__main__":
    main()
