"""Start packed weight fetches after activation prefetch and protect live words."""

from prepare_tri_oracle_early_weight_pairs import edit


def schedule_weight_prefetch(source):
    return edit(source, [
        ("  logic activation_bank, prefetch_inflight, next_tile;",
         """  logic activation_bank, prefetch_inflight, next_tile, clear_after_prefetch;
  logic [1:0] wide_load_ready;
  logic weight_writes_empty;"""),
        ("tri_oracle_parallel_weight_loader packed_loader (", "tri_oracle_backpressured_raw_weight_loader packed_loader ("),
        ("    .load_valid(wide_load_valid),", "    .load_ready(wide_load_ready),.load_valid(wide_load_valid),"),
        (".done_valid(packed_done),.done_ready(state==PACK_WAIT),",
         ".done_valid(packed_done),.done_ready(state==PACK_WAIT && weight_writes_empty),"),
        ("    .wide_load_payload({aux_rsp_data,wide_rsp_data}),", """    .wide_load_payload({aux_rsp_data,wide_rsp_data}),
    .wide_load_ready,.weight_writes_empty,
    .weight_reserve(state==EXECUTE && sequence_ready), .weight_reserve_strips(tile_words),
    .weight_last_read(backend_cmd_valid && backend_cmd_ready && backend_cmd_mask==5'(tokens-1)),"""),
        ("activation_bank<=0;prefetch_inflight<=0;\n      weight_core",
         "activation_bank<=0;prefetch_inflight<=0;clear_after_prefetch<=0;\n      weight_core"),
        ("activation_bank<=0;prefetch_inflight<=0;\n          done_error",
         "activation_bank<=0;prefetch_inflight<=0;clear_after_prefetch<=0;\n          done_error"),
        ("                  state<=prefetch_inflight ? WAIT_PREFETCH : CLEAR_WEIGHTS;",
         "                  state<=prefetch_inflight ? PACK_START : CLEAR_WEIGHTS;"),
        ("            if(weight_core==last_core)begin weight_core<=first_core;weight_row<=0;chunk_word<=0;state<=packed_weights ? PACK_START : WEIGHT_SELECT;end",
         """            if(weight_core==last_core)begin
              weight_core<=first_core;weight_row<=0;chunk_word<=0;clear_after_prefetch<=0;
              state<=clear_after_prefetch ? EXECUTE : packed_weights ? PACK_START : WEIGHT_SELECT;
            end"""),
        ("          if(packed_done)begin", "          if(packed_done && weight_writes_empty)begin"),
        ("            end else state<=EXECUTE;\n          end\n        end\n        EXECUTE:",
         "            end else state<=prefetch_inflight ? WAIT_PREFETCH : EXECUTE;\n          end\n        end\n        EXECUTE:"),
        ("          end else state<=CLEAR_WEIGHTS;\n        end\n        WAIT_EXECUTE:",
         "          end else begin clear_after_prefetch<=1;state<=CLEAR_WEIGHTS;end\n        end\n        WAIT_EXECUTE:"),
        ("          prefetch_inflight<=0;\n          if(flush_second)", "          prefetch_inflight<=0;clear_after_prefetch<=0;\n          if(flush_second)"),
    ])


def register_scheduler_tile_length(source):
    extent = "9'(part_words)-9'(tile_start)>32 ? 6'd32 : 6'(part_words-tile_start)"
    return edit(source, [
        (f"    tile_words={extent};\n", ""),
        ("chunk_word<=0;selected_channel<=0;", "chunk_word<=0;selected_channel<=0;tile_words<=0;"),
        ("        ACT_PREPARE:begin activation_mode<=1;state<=ADDRESS_OFFSET;end",
         f"""        ACT_PREPARE:begin
          tile_words<={extent};
          activation_mode<=1;state<=ADDRESS_OFFSET;
        end"""),
    ])


def bind_weight_guards(source):
    return edit(source, [
        ("    input wire [1:0] wide_load_valid,", """    input wire [1:0] wide_load_valid,
    output logic [1:0] wide_load_ready,
    output logic weight_writes_empty,
    input logic weight_reserve, weight_last_read,
    input logic [5:0] weight_reserve_strips,"""),
        ("        .read_cores(phase_read_cores), .read_address(cmd_weight),", """        .read_cores(phase_read_cores), .read_address(cmd_weight),
        .wide_ready(wide_load_ready), .writes_empty(weight_writes_empty),
        .reserve(weight_reserve), .reserve_strips(weight_reserve_strips), .last_read(weight_last_read),"""),
    ])


def guard_weight_ingress(source):
    return edit(source, [
        ("  input logic [4:0] read_address,", """  input logic [4:0] read_address,
  input logic reserve, last_read,
  input logic [5:0] reserve_strips,
  output logic [1:0] wide_ready,
  output logic writes_empty,"""),
        ("  logic malformed;", "  logic malformed;\n  logic [1:0] allowed;"),
        ("  for (genvar lane = 0; lane < 2; lane++) begin : check_wide",
         """  assign wide_ready = scalar_valid ? 2'b00 : load_ready;
  assign writes_empty = !(|pending) && !(|load_valid);
  for (genvar lane = 0; lane < 2; lane++) begin : check_wide
    tri_oracle_projection_weight_reuse reservation (
      .clk, .rst_n, .discard(1'b0), .reserve, .reserve_base(5'd0), .reserve_strips,
      .last_read, .read_word(read_address), .write_word(staged_address[lane][4:0]),
      .write_allowed(allowed[lane])
    );"""),
        (".write_pending(pending), .write_allowed(2'b11)", ".write_pending(pending), .write_allowed(allowed)"),
    ])


def check_guarded_weight_writes(source):
    return edit(source, [
        ("  input logic [1:0] load_valid, load_ready, pending, retired,", """  input logic [1:0] load_valid, load_ready, pending, retired, allowed,
  input logic reserve, last_read,
  input logic [5:0] reserve_strips,
  input logic [4:0] read_address,
  input logic [4:0][4:0] phase_address,"""),
        ("  bit [4:0] read_clusters, write_clusters;", """  bit [4:0] read_clusters, write_clusters;
  bit [31:0] unread;
  int protected_cycles = 0;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) unread <= 0;
    else if (reserve) unread <= 32'((64'd1 << reserve_strips) - 1);
    else if (last_read) unread[read_address] <= 0;
  end"""),
        ("if (error || pending !== retired || (|(load_valid & ~load_ready)))",
         "if (error || (|(retired & ~pending)) || (|(load_valid & ~load_ready)))"),
        ("    if (scalar_valid)", "    if (|(pending & ~allowed)) protected_cycles++;\n    if (scalar_valid)"),
        ("          writes++;", """          if (unread[phase_address[cluster]])
            $fatal(1, "CHIP_WEIGHT_PREFETCH_OVERWRITE cluster=%0d word=%0d", cluster, phase_address[cluster]);
          writes++;"""),
        ("endmodule\n\nbind", """  final $display("CHIP_WEIGHT_GUARD blocked=%0d", protected_cycles);
endmodule

bind"""),
    ])


def prepare_guard_stress_bench(source):
    tensor = "dut.layer.layer.feedforward.compute.compute.tensor"
    return edit(source, [
        ("(FAULT==4 && packed_sign_address(wide_address[lane])) ||",
         f"""(FAULT==4 && packed_sign_address(wide_address[lane])) ||
       (FAULT==18 && lane==FAULT_LANE && {tensor}.prefetch_inflight &&
        !{tensor}.sequence_done_valid && weight_branch(wide_address[lane])>=0) ||"""),
        ("FAULT<=4 || FAULT==7 || FAULT==11", "FAULT<=4 || FAULT==7 || FAULT==11 || FAULT==18"),
        ("endmodule\n", f"""  initial if ($test$plusargs("STALL_FIRST_PROJECTION")) begin
    wait ({tensor}.prefetch_inflight);
    @(negedge clk);
    force {tensor}.fabric.cmd_ready = 1'b0;
    if ($test$plusargs("IGNORE_WEIGHT_REUSE"))
      force {tensor}.fabric.weight_ingress.allowed = 2'b11;
    repeat (160) @(negedge clk);
    release {tensor}.fabric.cmd_ready;
  end
endmodule
"""),
    ])
