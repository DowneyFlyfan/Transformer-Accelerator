"""Generate the existing dual-format weight transport with write backpressure."""

import argparse
from pathlib import Path

from prepare_tri_oracle_dual_group_transport import widen_transport
from prepare_tri_oracle_early_weight_pairs import edit


RAW = "tri_oracle_backpressured_raw_weight_loader"
TRANSPORT = "tri_oracle_backpressured_weight_transport"


def raw_loader(source):
    return edit(source, [
        ("module tri_oracle_parallel_weight_loader (", f"module {RAW} ("),
        ("  output logic [1:0] load_valid,", "  input logic [1:0] load_ready,\n  output logic [1:0] load_valid,"),
        ("  logic conflict, next_grant;\n", ""),
        ("  assign conflict = (&raw_load_valid) && load_core[0][4:2] == load_core[1][4:2];\n"
         "  assign write_grant = conflict ? (next_grant ? 2'b10 : 2'b01) : 2'b11;",
         "  weight_stream_write_arbiter arbiter (\n"
         "    .clk, .rst_n, .offered(raw_load_valid), .core(load_core), .memory_ready(load_ready),\n"
         "    .granted(write_grant)\n"
         "  );"),
        ("      next_grant <= 0;\n", ""),
        ("      if (conflict) next_grant <= !next_grant;\n", ""),
    ])


def transport(source):
    return edit(widen_transport(source), [
        ("module tri_oracle_dual_group_weight_transport (", f"module {TRANSPORT} ("),
        ("  output logic [1:0] load_valid,", "  input logic [1:0] load_ready,\n  output logic [1:0] load_valid,"),
        ("tri_oracle_parallel_weight_loader raw_loader (", f"{RAW} raw_loader ("),
        (".load_valid(raw_load),.load_core(raw_core)", ".load_ready,.load_valid(raw_load),.load_core(raw_core)"),
        (".memory_ready(2'b11)", ".memory_ready(load_ready)"),
    ])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    output = parser.parse_args().output
    output.mkdir(parents=True, exist_ok=True)
    for base, master, convert in (
        ("tri_oracle_parallel_weight_loader", RAW, raw_loader),
        ("tri_oracle_controlled_weight_transport", TRANSPORT, transport),
    ):
        source = Path(f"verilog/{base}.sv").read_text()
        (output / f"{master}.sv").write_text(convert(source))


if __name__ == "__main__":
    main()
