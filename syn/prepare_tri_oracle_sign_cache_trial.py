"""Insert a command-local sign cache into a copy of the dual-lane source chip."""

import argparse
import json
from pathlib import Path

from prepare_tri_oracle_packed_tensor import rewrite
from prepare_tri_oracle_parallel_chip_synthesis import BASE, includes, pin, read, verify
from verify_tri_oracle_packed_down_weights import ROOT


FETCH_PORTS = """        .req_valid(req_valid), .req_ready(req_ready), .req_address(req_address),
        .req_length(req_length), .rsp_valid(rsp_valid), .rsp_ready(rsp_ready),
        .rsp_last(rsp_last), .rsp_error(rsp_error), .rsp_data(rsp_data)
    );"""
CACHE_BINDING = """
    tri_oracle_sign_word_cache sign_cache (
        .clk, .rst_n, .frame_start(cfg_valid && cfg_ready),
        .client_req_valid(cache_req_valid), .client_req_ready(cache_req_ready),
        .client_req_address(cache_req_address), .client_req_length(cache_req_length),
        .client_rsp_valid(cache_rsp_valid), .client_rsp_ready(cache_rsp_ready),
        .client_rsp_last(cache_rsp_last), .client_rsp_error(cache_rsp_error), .client_rsp_data(cache_rsp_data),
        .mem_req_valid(req_valid), .mem_req_ready(req_ready), .mem_req_address(req_address),
        .mem_req_length(req_length), .mem_rsp_valid(rsp_valid), .mem_rsp_ready(rsp_ready),
        .mem_rsp_last(rsp_last), .mem_rsp_error(rsp_error), .mem_rsp_data(rsp_data)
    );"""


def predictor(text):
    return rewrite(text, (
        ("    tri_oracle_sign_fetch sign_memory (", """    logic cache_req_valid, cache_req_ready, cache_rsp_valid, cache_rsp_ready;
    logic cache_rsp_last, cache_rsp_error;
    logic [63:0] cache_req_address, cache_rsp_data;
    logic [4:0] cache_req_length;

    tri_oracle_sign_fetch sign_memory ("""),
        (FETCH_PORTS, """        .req_valid(cache_req_valid), .req_ready(cache_req_ready), .req_address(cache_req_address),
        .req_length(cache_req_length), .rsp_valid(cache_rsp_valid), .rsp_ready(cache_rsp_ready),
        .rsp_last(cache_rsp_last), .rsp_error(cache_rsp_error), .rsp_data(cache_rsp_data)
    );""" + CACHE_BINDING),
    ))


def bench(text):
    source = "dut.layer.layer.feedforward.predictor.replay_table"
    return rewrite(text, (
        ("  int sign_requests=0,contended_cycles=0,valid_masks=0,abort_masks=0;",
         "  int sign_requests=0,contended_cycles=0,valid_masks=0,abort_masks=0;\n  int logical_sign_reads=0;"),
        ("    if((TRAINED ? (sign_requests!=55616 || expected_sign_group!=INTERMEDIATE/32 ||\n"
         "                   expected_sign_token!=0 || expected_sign_up) : sign_requests!=TOKENS*(INTERMEDIATE/32)*4) ||",
         "    if(TRAINED || FAULT!=0 || logical_sign_reads!=36 || sign_requests!=24 ||"),
        ("  initial begin #(TRAINED ?", f"""  always @(posedge clk) begin
    if ({source}.cache_req_valid && {source}.cache_req_ready) logical_sign_reads++;
  end
  initial begin #(TRAINED ?"""),
    ))


def run(candidate, output):
    setup = candidate / "prepared.json"
    native = read(setup)
    assert native["state"] == "source_chip_connects_two_packed_read_lanes_to_compiled_clusters"
    pins = native["input_sha256"].copy()
    verify(pins)
    original = candidate / "bundle.sv"
    source, = (path for path in includes(original) if path.name == "tri_oracle_batched_outlier_replay404.sv")
    source_test = candidate / "trained_tb.sv"
    cache = ROOT / "verilog/tri_oracle_sign_word_cache.sv"
    for path in (setup, source, source_test, original, cache, Path(__file__).resolve()):
        pin(pins, path)
    output.mkdir()
    modified = output / source.name
    test = output / source_test.name
    modified.write_text(predictor(source.read_text()))
    test.write_text(bench(source_test.read_text()))
    bundle = output / "bundle.sv"
    bundle.write_text(rewrite(original.read_text(), (
        (f'`include "{source}"', f'`include "{cache}"\n`include "{modified}"'),
        (f'`include "{source_test}"', f'`include "{test}"'),
    )))
    for path in (modified, test, bundle):
        pin(pins, path)
    verify(pins)
    result = {"state": "dual_lane_source_sign_cache_directed_trial_prepared", "input_sha256": pins}
    (output / "prepared.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=lambda value: Path(value).resolve())
    parser.add_argument("--candidate", type=lambda value: Path(value).resolve(), default=BASE / "parallel_chip_v3")
    args = parser.parse_args()
    run(args.candidate, args.output)
