"""Generate the SRAM compute core variant with a separate upper-bank port."""

import argparse
from pathlib import Path

TOP = "tri_oracle_sram_residual_core"


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError(f"Expected exactly one core declaration matching {old!r}")
    return source.replace(old, new, 1)


def residual_core(source):
    core = source.split("\nendmodule", 1)[0] + "\nendmodule\n"
    core = replace_once(core, "module tri_oracle_sram_memory_compute (", f"module {TOP} (")
    core = replace_once(
        core, "  output logic [1023:0] result_data\n);", """  output logic [1023:0] result_data,
  input logic residual_reserved, residual_ce_n, residual_we_n,
  input logic [8:0] residual_addr,
  input logic [63:0] residual_d,
  output logic [63:0] residual_q
);""",
    )
    core = replace_once(
        core, "  always_comb begin\n    cmd_ready = array_ready && !load_valid;", """
  // Reserve only between native upper-bank accesses. The lower bank
  // remains available to the native pipeline during the reservation.
  assign residual_q = residual_reserved ? input_q[127:64] : '0;

  always_comb begin
    cmd_ready = array_ready && !load_valid && !(residual_reserved && cmd_activation[9]);""",
    )
    core = replace_once(
        core, """    .CLK(clk), .CEB(input_ceb), .WEB(input_web), .A(input_address),
    .D(load_data[63:0]), .Q(input_q)""", """    .CLK(clk),
    .CEB({residual_reserved ? (!rst_n || residual_ce_n) : input_ceb[1], input_ceb[0]}),
    .WEB({residual_reserved ? residual_we_n : input_web[1], input_web[0]}),
    .A({residual_reserved ? residual_addr : input_address, input_address}),
    .D({residual_reserved ? residual_d : load_data[63:0], load_data[63:0]}),
    .Q(input_q)""",
    )
    return replace_once(
        core, "      load_error <= load_valid && (load_kind == 3",
        """      load_error <= load_valid && (load_kind == 3
                                  || (residual_reserved && load_kind == 1 && load_addr[9])""",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    original = root / "verilog/tri_oracle_sram_memory_compute.sv"
    with args.output.open("x") as output:
        output.write(residual_core(original.read_text()))
