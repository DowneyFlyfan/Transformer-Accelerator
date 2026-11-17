"""Apply asymmetric stalls to the existing raw and indexed weight scoreboards."""

import argparse
from pathlib import Path
import re

from prepare_tri_oracle_backpressured_weight_transport import TRANSPORT
from prepare_tri_oracle_early_weight_pairs import edit


def indexed(source):
    start = source.index("  tri_oracle_packed_write_stage_mapped stage (")
    end = source.index("\n  );", start) + len("\n  );")
    stage = """  logic [1:0] stage_pending, write_ready, held_response;
  int written_while_other_blocked[2];
  assign write_ready = ideal_writes ? 2'b11 : {cycle%43>=13, cycle%131>=70};
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) held_response <= 0;
    else held_response <= rsp_valid & ~rsp_ready;
  end
  tri_oracle_weight_write_buffer stage (
    .clk,.rst_n,.load_valid,.load_ready,.pending(stage_pending),
    .load_core,.load_addr,.load_row_enable(segment_rows),.load_payload(segment_payload),
    .write_ready,.write_valid(staged_valid),.write_core(staged_core),.write_addr(staged_addr),
    .write_row_enable(staged_rows),.write_payload(staged_payload),
    .loader_done_valid(&done_valid),.loader_done_error(|done_error),
    .done_ready(&done_ready),.loader_done_ready(stage_ready),
    .done_valid(stage_done),.done_error(stage_error)
  );"""
    return edit(source[:start] + stage + source[end:], [
        ("tri_oracle_dual_group_weight_transport dut", f"{TRANSPORT} dut"),
        (".load_valid,.load_core", ".load_valid,.load_ready,.load_core"),
        ("  assign request_grant=2'b11;", "  assign request_grant=load_ready;"),
        ("    assign load_ready[lane]=1'b1;\n", ""),
        ("rsp_valid[lane]=active[lane] && cycle%4!=lane;",
         "rsp_valid[lane]=active[lane] && (held_response[lane] || cycle%4!=lane);"),
        ("      if (load_valid[lane] && load_ready[lane]) decoded_words[lane]++;",
         """      if (load_valid[lane] && !load_ready[lane]) $fatal(1,"WEIGHT_STAGE_OVERFLOW");
      if (load_valid[lane]) decoded_words[lane]++;
      if (staged_valid[lane] && stage_pending[1-lane] && !write_ready[1-lane])
        written_while_other_blocked[lane]++;"""),
        ("    if (stage_done && |staged_valid)", "    if (stage_done && (|stage_pending || |load_valid))"),
        ("    $finish;", """    if (!ideal_writes && (written_while_other_blocked[0]==0 || written_while_other_blocked[1]==0 ||
        denied_by_memory[0]==0 || denied_by_memory[1]==0)) $fatal(1,"INDEXED_STALL_COVERAGE");
    $display("INDEXED_STALL_PASS ideal=%0d independent0=%0d independent1=%0d blocked0=%0d blocked1=%0d",
             ideal_writes,written_while_other_blocked[0],written_while_other_blocked[1],
             denied_by_memory[0],denied_by_memory[1]);
    $finish;"""),
        ("    #4ms;", "    #8ms;"),
    ])


def raw(source):
    dut = re.search(r"(?ms)^`ifdef EXISTING_RAW\n.*?^`endif", source)[0]
    stage = f"""  logic loader_done_valid, loader_done_ready, loader_done_error;
  logic [1:0] load_ready, stage_pending, write_ready, write_valid;
  logic [1:0][4:0] write_core;
  logic [1:0][9:0] write_addr;
  logic [1:0][31:0] write_row_enable;
  logic [1:0][1023:0] write_payload;
  localparam int ENTRY_BITS = 1071;
  logic [ENTRY_BITS-1:0] expected_write[2];
  int cycle, commits, stalled[2], independent[2];
  assign write_ready = inject_fault ? 2'b11 : {{cycle%19>=5,cycle%31>=14}};
  always @(negedge clk) cycle<=cycle+1;
  {TRANSPORT} dut (
    .done_valid(loader_done_valid),.done_ready(loader_done_ready),.done_error(loader_done_error),.*
  );
  tri_oracle_weight_write_buffer stage (
    .clk,.rst_n,.load_valid,.load_ready,.pending(stage_pending),.load_core,.load_addr,
    .load_row_enable,.load_payload,.write_ready,.write_valid,.write_core,.write_addr,
    .write_row_enable,.write_payload,.loader_done_valid,.loader_done_ready,.loader_done_error,
    .done_valid,.done_ready,.done_error
  );
  always @(posedge clk) if (rst_n) begin
    if (done_valid && (|stage_pending || |load_valid)) $fatal(1,"RAW_STAGE_EARLY_DONE");
    if ((&write_valid) && write_core[0][4:2]==write_core[1][4:2]) $fatal(1,"RAW_STAGE_CLUSTER_COLLISION");
    for(int lane=0;lane<2;lane++) begin
      if (write_valid[lane]) begin
        if ({{write_core[lane],write_addr[lane],write_row_enable[lane],write_payload[lane]}} !==
            expected_write[lane]) $fatal(1,"RAW_STAGE_PAYLOAD lane=%0d",lane);
        commits++;
        if (stage_pending[1-lane] && !write_ready[1-lane]) independent[lane]++;
      end
      if (rsp_valid[lane] && !load_ready[lane] && !inject_fault) stalled[lane]++;
      if (load_valid[lane]) begin
        if (!load_ready[lane]) $fatal(1,"RAW_STAGE_OVERFLOW");
        expected_write[lane] = {{load_core[lane],load_addr[lane],load_row_enable[lane],load_payload[lane]}};
      end
    end
  end"""
    return edit(source, [
        (dut, stage),
        ('      if (!(^rsp_ready) || !(^load_valid)) $fatal(1, "PARALLEL_CLUSTER_ARBITRATION");',
         """      if (|load_ready) begin
        if (!(^rsp_ready) || !(^load_valid)) $fatal(1,"PARALLEL_CLUSTER_ARBITRATION");
      end else if (|rsp_ready || |load_valid) $fatal(1,"PARALLEL_CLUSTER_OVERFLOW");"""),
        ("    responses = 0;", "    responses = 0;\n    commits = 0;"),
        ("    if (!fault) begin", '    if (commits != responses) $fatal(1,"RAW_STAGE_COMMIT_COUNT");\n    if (!fault) begin'),
        ('    $display("RAW_WEIGHT_MODE_PASS',
         """    if (stalled[0]==0 || stalled[1]==0 || independent[0]==0 || independent[1]==0)
      $fatal(1,"RAW_STAGE_STALL_COVERAGE");
    $display("RAW_STAGE_STALL_PASS blocked0=%0d blocked1=%0d independent0=%0d independent1=%0d",
             stalled[0],stalled[1],independent[0],independent[1]);
    $display("RAW_WEIGHT_MODE_PASS"""),
    ])


def rolling_projection(source):
    """Use real projection handshakes to release the locations being written."""
    controller = """  logic projection_ready, projection_done, projection_error, projection_rst_n;
  logic cmd_valid, cmd_ready, read_accepted, computing;
  logic [4:0] cmd_word, projection_tokens;
  logic [3:0] cmd_token, retired_token;
  logic result_valid;
  logic [8:0] hold_age;
  logic [2:0] compute_phase;
  logic [1:0] reuse_allowed;
  bit [31:0] unread_words;
  logic serial, immediate, deferred_load;
  int projection_reads, completed_projections, read_write_cycles, blocked_writes;

  initial begin
    serial = $test$plusargs("SERIAL_PROJECTION");
    immediate = serial || $test$plusargs("IMMEDIATE_PROJECTION");
    projection_tokens = $test$plusargs("SINGLE_TOKEN") ? 5'd1 : 5'd16;
  end
  wire reserve_projection = cfg_valid && cfg_indexed;
  assign loader_cfg_indexed = cfg_indexed || deferred_load;
  assign loader_cfg_valid = serial ? ((cfg_valid && !cfg_indexed) || (deferred_load && !computing)) : cfg_valid;
  wire [5:0] projection_strips = tile_start == 160 ? 6'd16 : 6'd32;
  assign cmd_ready = computing && ((hold_age >= 9'd255) || (hold_age == 9'd0)) && compute_phase!=3;
  assign read_accepted = cmd_valid && cmd_ready;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      result_valid <= 0;
      retired_token <= 0;
      computing <= 0;
      hold_age <= 0;
      compute_phase <= 0;
      deferred_load <= 0;
    end else begin
      result_valid <= read_accepted;
      retired_token <= cmd_token;
      if (reserve_projection && projection_ready) begin
        computing <= 1;
        hold_age <= immediate ? 0 : 1;
        compute_phase <= 0;
      end else if (projection_done) begin
        computing <= 0;
        hold_age <= 0;
      end else if (|stage_pending && hold_age != 0) hold_age <= 0;
      else if (hold_age != 0 && hold_age < 9'd255) hold_age <= hold_age + 1'b1;
      if (computing) compute_phase <= compute_phase == 6 ? 0 : compute_phase + 1'b1;
      if (serial && reserve_projection) deferred_load <= 1;
      else if (loader_cfg_valid && transport_ready) deferred_load <= 0;
    end
  end
  tri_oracle_batched_projection356 projection (
    .clk,.rst_n,.in_valid(reserve_projection),.in_ready(projection_ready),
    .in_tag(32'd51),.in_tokens(projection_tokens),.in_weight_base(5'd0),.in_mask_base(5'd0),
    .in_strips(projection_strips),.in_activation_base(10'd0),.in_activation_stride(11'd32),
    .in_accumulate(1'b0),.in_publish(1'b0),.out_valid(),.out_ready(1'b1),
    .out_tag(),.out_token(),.out_last(),.out_data(),.done_valid(projection_done),
    .done_ready(1'b1),.done_error(projection_error),.done_tag(),.backend_rst_n(projection_rst_n),
    .backend_cmd_valid(cmd_valid),.backend_cmd_ready(cmd_ready),.backend_cmd_weight(cmd_word),
    .backend_cmd_mask(),.backend_cmd_activation(),.backend_cmd_output(cmd_token),
    .backend_cmd_accumulate(),.backend_out_valid({5{result_valid}}),.backend_out_ready(),
    .backend_out_output({5{retired_token}}),.backend_out_data('0)
  );
  for (genvar lane=0; lane<2; lane++) begin : guard_lane
    tri_oracle_projection_weight_reuse guard (
      .clk,.rst_n,.discard(!projection_rst_n),.reserve(reserve_projection && projection_ready),
      .reserve_base(5'd0),.reserve_strips(projection_strips),
      .last_read(read_accepted && 5'(cmd_token) + 5'd1 == projection_tokens),
      .read_word(cmd_word),.write_word(staged_addr[lane][4:0]),.write_allowed(reuse_allowed[lane])
    );
    assign write_ready[lane] = reuse_allowed[lane] && staged_addr[lane][9:5]==0;
  end
  always @(posedge clk) if (rst_n) begin
    if (reserve_projection && !projection_ready) $fatal(1,"ROLLING_PROJECTION_BUSY");
    if (projection_done && projection_error) $fatal(1,"ROLLING_PROJECTION_ERROR");
    if (projection_done) completed_projections++;
    if (read_accepted) projection_reads++;
    if (read_accepted && |staged_valid) read_write_cycles++;
    if (|(stage_pending & ~write_ready)) blocked_writes++;
    for (int lane=0;lane<2;lane++) begin
      if (staged_valid[lane] && unread_words[staged_addr[lane][4:0]])
        $fatal(1,"ROLLING_PROJECTION_OVERWRITE lane=%0d word=%0d",lane,staged_addr[lane]);
    end
  end"""
    controller += """
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) unread_words <= '0;
    else if (reserve_projection && projection_ready)
      unread_words <= projection_strips == 32 ? 32'hffff_ffff : 32'h0000_ffff;
    else if (read_accepted && 5'(cmd_token) + 5'd1 == projection_tokens)
      unread_words[cmd_word] <= 0;
  end"""
    return edit(source, [
        ("  assign write_ready = ideal_writes ? 2'b11 : {cycle%43>=13, cycle%131>=70};", controller),
        (f"  {TRANSPORT} dut (", f"  logic loader_cfg_valid, loader_cfg_indexed;\n  {TRANSPORT} dut ("),
        ("    .clk,.rst_n,.cfg_valid,.cfg_paired(1'b0),.cfg_indexed,.cfg_ready(transport_ready),",
         "    .clk,.rst_n,.cfg_valid(loader_cfg_valid),.cfg_paired(1'b0),\n"
         "    .cfg_indexed(loader_cfg_indexed),.cfg_ready(transport_ready),"),
        ("    wait(stage_done===1'b1);", "    wait(stage_done===1'b1 && !computing);"),
        ("    if (!ideal_writes && (written_while_other_blocked[0]==0 || written_while_other_blocked[1]==0 ||\n"
         "        denied_by_memory[0]==0 || denied_by_memory[1]==0)) $fatal(1,\"INDEXED_STALL_COVERAGE\");",
         """    if (!$test$plusargs("FULL_MATRIX") || completed_projections!=80 ||
        projection_reads!=2352*int'(projection_tokens))
      $fatal(1,"ROLLING_PROJECTION_COVERAGE");
    if ((serial && (read_write_cycles!=0 || blocked_writes!=0)) ||
        (!serial && projection_tokens==16 && (read_write_cycles==0 || blocked_writes==0)))
      $fatal(1,"ROLLING_PROJECTION_OVERLAP_COVERAGE");
    $display("ROLLING_PROJECTION_PASS serial=%0d immediate=%0d tokens=%0d projections=%0d reads=%0d read_write_cycles=%0d blocked_cycles=%0d",
             serial,immediate,projection_tokens,completed_projections,projection_reads,read_write_cycles,blocked_writes);"""),
    ])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference_folder", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    index_bench = indexed((args.reference_folder / "indexed_tb.sv").read_text())
    (args.output / "indexed_tb.sv").write_text(index_bench)
    (args.output / "rolling_tb.sv").write_text(rolling_projection(index_bench))
    (args.output / "raw_tb.sv").write_text(raw((args.reference_folder / "raw_tb.sv").read_text()))


if __name__ == "__main__":
    main()
