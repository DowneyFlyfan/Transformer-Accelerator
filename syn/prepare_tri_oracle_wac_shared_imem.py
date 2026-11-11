"""Build a weight-attention core with matrix and softmax access to its input banks."""

import argparse
from pathlib import Path
import re

from run_tri_oracle_wac_softmax_imem import CORE, RTL, replace, source

TOP = "tri_oracle_wac_compute_softmax"
EXTRA_PORTS = """  output logic load_ready,
  input logic activation_reloaded,
  output logic activation_reload_required,
  input logic softmax_cfg_valid,
  output logic softmax_cfg_ready, softmax_cfg_error,
  input logic [10:0] softmax_cfg_length,
  input logic softmax_in_valid,
  output logic softmax_in_ready,
  input logic signed [15:0] softmax_in_score,
  input logic [9:0] softmax_in_size,
  output logic softmax_out_valid, softmax_out_last,
  input logic softmax_out_ready,
  output logic [15:0] softmax_out_probability,
"""
SHARED_SIGNALS = """  logic accepted_load, compute_enabled, softmax_configure, softmax_owns_input;
  logic simd_cfg_ready;
  logic [1:0] simd_mem_ce_n, simd_mem_we_n;
  logic [8:0] simd_mem_address;
  logic [1:0][63:0] simd_mem_d, imem_d;
  logic [1:0] imem_ce_n, imem_we_n;
  logic [8:0] imem_address;

  assign accepted_load = load_valid && load_ready;
  assign softmax_cfg_ready = softmax_configure && simd_cfg_ready;
  assign imem_ce_n = softmax_owns_input ? simd_mem_ce_n : input_ceb;
  assign imem_we_n = softmax_owns_input ? simd_mem_we_n : input_web;
  assign imem_address = softmax_owns_input ? simd_mem_address : input_address;
  assign imem_d = softmax_owns_input ? simd_mem_d : {2{load_data[63:0]}};

  tri_oracle_wac_imem_owner input_owner (
    .clk, .rst_n, .load_ready, .activation_reloaded, .activation_reload_required,
    .compute_enabled, .compute_accepted(accept_command), .compute_done(done_valid),
    .softmax_request(softmax_cfg_valid), .softmax_start(softmax_cfg_valid && softmax_cfg_ready),
    .softmax_configure, .softmax_owns_input,
    .softmax_end(softmax_cfg_error || (softmax_out_valid && softmax_out_ready && softmax_out_last)),
    .softmax_wrote_input(simd_mem_we_n != 2'b11)
  );

  tri_oracle_wac_softmax simd (
    .clk, .rst_n, .cfg_valid(softmax_cfg_valid && softmax_configure), .cfg_ready(simd_cfg_ready),
    .cfg_error(softmax_cfg_error), .cfg_length(softmax_cfg_length),
    .in_valid(softmax_in_valid), .in_ready(softmax_in_ready), .in_score(softmax_in_score), .in_size(softmax_in_size),
    .out_valid(softmax_out_valid), .out_ready(softmax_out_ready), .out_last(softmax_out_last),
    .out_probability(softmax_out_probability), .mem_ce_n(simd_mem_ce_n), .mem_we_n(simd_mem_we_n),
    .mem_address(simd_mem_address), .mem_d(simd_mem_d), .mem_q(input_q)
  );

"""


def core_source(text):
    module, _, _ = text.partition("\nendmodule")
    header, separator, body = module.partition("\n);\n")
    assert separator
    header = replace(header, "module tri_oracle_sram_memory_compute (", f"module {TOP} (")
    header = replace(header, "  input logic load_valid,\n", "  input logic load_valid,\n" + EXTRA_PORTS)
    body = re.sub(r"\bload_valid\b", "accepted_load", body)
    body = replace(body, "    cmd_ready = array_ready && !accepted_load;",
                   "    cmd_ready = compute_enabled && array_ready && !accepted_load;")
    body = replace(body, "  always_comb begin\n    cmd_ready", SHARED_SIGNALS + "  always_comb begin\n    cmd_ready")
    body = replace(body, ".CLK(clk), .CEB(input_ceb), .WEB(input_web), .A(input_address),\n    .D(load_data[63:0]), .Q(input_q)",
                   ".CLK(clk), .CEB(imem_ce_n), .WEB(imem_we_n), .A(imem_address),\n    .D(imem_d), .Q(input_q)")
    return header + separator + body + "\nendmodule\n"


def prepare(output):
    output.mkdir(exist_ok=True)
    core = output / f"{TOP}.sv"
    simd = output / f"{CORE}.sv"
    with core.open("x") as stream:
        stream.write(core_source((RTL / "tri_oracle_sram_memory_compute.sv").read_text()))
    with simd.open("x") as stream:
        stream.write(source((RTL / "tri_oracle_proportional_softmax.sv").read_text()))
    return core, simd


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    prepare(parser.parse_args().output.resolve())
