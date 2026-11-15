"""Exercise explicit raw and indexed format selection with the existing fixtures."""

import argparse
from pathlib import Path

from prepare_tri_oracle_early_weight_pairs import edit, testbench


def raw_test(source):
    return edit(source, [
        ("module tri_oracle_parallel_weight_loader_tb;", "module raw_weight_mode_tb;"),
        ("  tri_oracle_parallel_weight_loader dut (.*);", """  logic cfg_indexed=0;
  logic [1:0][511:0] load_payload;
`ifdef EXISTING_RAW
  tri_oracle_parallel_weight_loader dut (.*);
  assign load_payload=rsp_data;
`else
  tri_oracle_controlled_weight_transport dut (.*);
`endif"""),
        ("        if (seen[branch][group][feature_word])", """        if (load_payload[lane]!==rsp_data[lane]) $fatal(1,"RAW_MODE_DATA_MUX");
        if (seen[branch][group][feature_word])"""),
        ("    cfg_paired = paired;", "    cfg_paired = paired;\n    cfg_indexed = 0;"),
        ("    cfg_paired = 'x;", "    cfg_paired = 'x;\n    cfg_indexed = 1;"),
        ('    $display("PARALLEL_WEIGHT_LOADER_PASS tiles=6");', """    cfg_indexed=1;
    cfg_paired=0;
    cfg_base=GATE;
    cfg_up_base=UP;
    cfg_first_row=8;
    cfg_count=8;
    cfg_tile_start=0;
    cfg_keep='1;
    cfg_active_words='1;
    cfg_valid=1;
    @(negedge clk);
    cfg_valid=0;
    cfg_indexed=0;
    repeat (3) begin
      if (req_valid!==0 || rsp_ready!==0 || load_valid!==0 || !done_valid || !done_error || cfg_ready)
        $fatal(1,"INDEXED_INVALID_NOT_REJECTED");
      @(negedge clk);
    end
    done_ready=1;
    @(negedge clk);
    if (!cfg_ready || done_valid) $fatal(1,"INDEXED_INVALID_RETIRE");
    $display("RAW_WEIGHT_MODE_PASS tiles=6 unsupported_indexed_rejected=1");"""),
    ])


def indexed_test(source):
    source = testbench(source)
    arbiter = source.index("  weight_stream_write_arbiter arbiter (")
    stage = source.index("  tri_oracle_packed_write_stage_mapped stage (", arbiter)
    source = source[:arbiter] + """  logic cfg_indexed=0, transport_ready, transport_done, transport_error;
  assign cfg_ready={2{transport_ready}};
  assign done_valid={2{transport_done}};
  assign done_error={2{transport_error}};
  assign offered=dut.stream_offered;
  assign granted=dut.stream_granted;
  assign request_grant=2'b11;
  tri_oracle_controlled_weight_transport dut (
    .clk,.rst_n,.cfg_valid,.cfg_paired(1'b0),.cfg_indexed,.cfg_ready(transport_ready),
    .cfg_base(INDEX),.cfg_up_base(64'b0),.cfg_first_row(first_row),
    .cfg_dense_rows(17'd2048),.cfg_feature_words(10'd704),
    .cfg_count(row_count),.cfg_tile_start(tile_start),.cfg_keep(keep),.cfg_active_words(active_words),
    .req_valid,.req_ready,.req_address,.req_length,.rsp_valid,.rsp_last,.rsp_error(2'b00),.rsp_data,.rsp_ready,
    .load_valid,.load_core,.load_addr,.load_row_enable,.load_payload(load_data),
    .done_valid(transport_done),.done_error(transport_error),.done_ready(stage_ready)
  );
""" + source[stage:]
    lane = source.index("    tri_oracle_early_pair_lane #(")
    response = source.index("    assign rsp_valid[lane]", lane)
    source = source[:lane] + """    assign req_ready[lane]=!active[lane] && cycle%5!=lane;
    assign load_ready[lane]=1'b1;
    assign segment_rows[lane]=load_row_enable[lane];
    assign segment_payload[lane]=load_data[lane];
""" + source[response:]
    return edit(source, [
        (".load_valid(offered & granted)", ".load_valid(load_valid)"),
        ("    cfg_valid=1;\n    @(negedge clk);\n    cfg_valid=0;", """    cfg_indexed=1;
    cfg_valid=1;
    @(negedge clk);
    cfg_valid=0;
    cfg_indexed=0;"""),
        ("""    $display("LANE_STATE %0d %0d loader=%0d %0d decoder=%0d %0d",
        lanes[0].dut.state,lanes[1].dut.state,lanes[0].dut.loader.state,lanes[1].dut.loader.state,
        lanes[0].dut.loader.decoder.state,lanes[1].dut.loader.decoder.state);
""", ""),
        ("    $finish;", """    keep='0;
    cfg_valid=1;
    @(negedge clk);
    cfg_valid=0;
    while (stage_done!==1'b1) begin
      if (req_valid!==0 || load_valid!==0 || staged_valid!==0 || transport_ready)
        $fatal(1,"WEIGHT_MODE_SWITCH_TRAFFIC");
      @(negedge clk);
    end
    if (stage_error!==1'b0) $fatal(1,"WEIGHT_MODE_SWITCH_STATUS");
    done_ready='1;
    @(negedge clk);
    if (!transport_ready || staged_valid!==0) $fatal(1,"WEIGHT_MODE_SWITCH_RETIRE");
    $display("INDEXED_WEIGHT_MODE_PASS switched_to_raw=1");
    $finish;"""),
    ])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("indexed_testbench", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    raw = Path("verilog/tri_oracle_parallel_weight_loader_tb.sv").read_text()
    (args.output / "raw_tb.sv").write_text(raw_test(raw))
    (args.output / "indexed_tb.sv").write_text(indexed_test(args.indexed_testbench.read_text()))


if __name__ == "__main__":
    main()
