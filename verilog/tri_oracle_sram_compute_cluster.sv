`timescale 1ns/1ps
// Four actual compiled-memory cores and a 2KB compiled aggregate result store.
// Ordered queue ownership matches the inferred cluster. Prefetch the next
// completed output at retirement; forward a simultaneous same-address write.
module tri_oracle_sram_compute_cluster #(
  parameter int MERGE_FEATURES=0,
  parameter bit AGGREGATOR_MERGE_TABLE=0,
  parameter int MERGE_TABLE_ENTRIES=128,
  parameter bit CORE_STRIP_PREDICTOR=0,
  parameter bit CORE_HEAD_PREDICTOR=0,
  localparam int SIGN_WIDTH=MERGE_FEATURES==0 ? 1 : MERGE_FEATURES
) (
  input logic clk,
  input logic rst_n,
  input logic load_valid,
  input logic [1:0] load_core,
  input logic [1:0] load_kind,
  input logic [9:0] load_addr,
  input logic [2047:0] load_data,
  input logic [31:0] load_row_enable,
  output logic load_error,
  input logic cmd_valid,
  output logic cmd_ready,
  input logic [4:0] cmd_weight,
  input logic [4:0] cmd_mask,
  input logic [9:0] cmd_activation,
  input logic [3:0] cmd_output,
  input logic cmd_accumulate,
  input logic [1:0] cmd_reduce,
  output logic out_valid,
  input logic out_ready,
  output logic [3:0] out_output,
  output logic [1023:0] out_data,
  input logic [SIGN_WIDTH-1:0] merge_sign_data,
  input logic [12:0] merge_sign_control,
  output logic [23:0] merge_sign_counts,
  input logic [18:0] merge_table_request,
  output logic [79:0] merge_table_word,
  input logic strip_rst_n,
  input logic [530:0] strip_request,
  output logic [111:0] strip_response,
  input logic [396:0] head_request,
  output logic [72:0] head_response
);
  if (AGGREGATOR_MERGE_TABLE) begin : aggregator_merge_table
    tri_oracle_token_merge_table454 #(.ENTRIES(MERGE_TABLE_ENTRIES)) table_bank (
      .clk, .request(merge_table_request), .word(merge_table_word)
    );
  end else begin : no_merge_table
    assign merge_table_word='0;
  end

  wire [1579:0] core_head_requests;
  wire [291:0] core_head_responses;
  if (CORE_HEAD_PREDICTOR) begin : head_route
    tri_oracle_cluster_head450 route (
      .request(head_request), .response(head_response),
      .core_requests(core_head_requests), .core_responses(core_head_responses)
    );
  end else begin : no_head_route
    assign core_head_requests='0;
    assign head_response='0;
  end

  wire [587:0] core_strip_requests;
  wire [159:0] core_strip_responses;
  if (CORE_STRIP_PREDICTOR) begin : strip_group
    tri_oracle_cluster_strip448 route (
      .request(strip_request), .response(strip_response),
      .core_requests(core_strip_requests), .core_responses(core_strip_responses)
    );
  end else begin : no_strip_group
    assign core_strip_requests='0;
    assign strip_response='0;
  end

  if (MERGE_FEATURES!=0) begin : aggregator_sign
    tri_oracle_aggregator_sign447 #(
      .FEATURES(MERGE_FEATURES), .COMPILED_SIGN_BANK(1'b1),
      .COMPACT_SIGN_DEPTH(AGGREGATOR_MERGE_TABLE)
    ) similarity (
      .clk, .sign_data(merge_sign_data), .control(merge_sign_control), .counts(merge_sign_counts)
    );
  end else begin : no_sign_bank
    assign merge_sign_counts='0;
  end

  logic [3:0] ready, done, result_valid, load_errors, core_load;
  logic [15:0] done_slots;
  logic [4095:0] result_words;
  logic done_aligned, issue, retire, aggregate_write, output_refill, read_collision;
  logic [1023:0] reduced_words, aggregate_q, forwarded_words;
  logic [15:0] reserved, complete;
  logic [1:0] reduce_mode[16];
  logic [3:0] tag_queue[16];
  logic [3:0] head, tail, read_slot, next_head, next_output;
  logic [4:0] count, pending_count;
  logic output_forward, aggregate_web, aggregate_reb;

  function automatic logic [31:0] reduce_four(
      input logic signed [31:0] a, b, c, d, input logic [1:0] mode);
    logic signed [33:0] total;
    logic signed [31:0] ab, cd;
    total = $signed({{2{a[31]}}, a}) + $signed({{2{b[31]}}, b})
            + $signed({{2{c[31]}}, c}) + $signed({{2{d[31]}}, d});
    ab = a > b ? a : b;
    cd = c > d ? c : d;
    case (mode)
      1: return ab > cd ? ab : cd;
      2: return 32'(total >>> 2);
      default: return total[31:0];
    endcase
  endfunction

  always_comb begin
    load_error = |load_errors;
    cmd_ready = (&ready) && !load_valid && count < 16
                && !reserved[cmd_output] && cmd_reduce != 3;
    issue = cmd_valid && cmd_ready;
    retire = out_valid && out_ready;
    done_aligned = (&done) && done_slots[7:4] == done_slots[3:0]
                   && done_slots[11:8] == done_slots[3:0]
                   && done_slots[15:12] == done_slots[3:0];
    aggregate_write = rst_n && (&result_valid);
    for (integer row = 0; row < 32; row++)
      reduced_words[row*32+:32] = reduce_four(
          $signed(result_words[row*32+:32]), $signed(result_words[1024+row*32+:32]),
          $signed(result_words[2048+row*32+:32]), $signed(result_words[3072+row*32+:32]),
          reduce_mode[read_slot]);
    for (integer c = 0; c < 4; c++) core_load[c] = load_valid && load_core == 2'(c);
    next_head = retire ? head + 4'd1 : head;
    pending_count = count - (retire ? 5'd1 : 5'd0);
    next_output = tag_queue[next_head];
    read_collision = aggregate_write && read_slot == next_output;
    output_refill = rst_n && (!out_valid || out_ready) && pending_count != 0
                    && (complete[next_output] || read_collision);
    aggregate_web = !aggregate_write;
    aggregate_reb = !(output_refill && !read_collision);
    out_data = output_forward ? forwarded_words : aggregate_q;
  end

  tri_oracle_sram_strip_core448 #(.CORE_STRIP_PREDICTOR(CORE_STRIP_PREDICTOR), .CORE_HEAD_PREDICTOR(CORE_HEAD_PREDICTOR)) cores[3:0] (
    .head_request(core_head_requests), .head_response(core_head_responses),
    .strip_rst_n, .strip_request(core_strip_requests), .strip_response(core_strip_responses),
    .clk(clk), .rst_n(rst_n), .load_valid(core_load), .load_kind(load_kind),
    .load_addr(load_addr), .load_data(load_data), .load_row_enable(load_row_enable),
    .load_error(load_errors), .cmd_valid(issue), .cmd_ready(ready),
    .cmd_weight(cmd_weight), .cmd_activation(cmd_activation), .cmd_mask(cmd_mask),
    .cmd_output(cmd_output), .cmd_accumulate(cmd_accumulate),
    .done_valid(done), .done_output(done_slots),
    .read_valid(done_aligned), .read_output(done_slots[3:0]),
    .result_valid(result_valid), .result_data(result_words)
  );
  TS6N28HPCPSVTA16X128M2F aggregate_memory[7:0] (
    .CLKW(clk), .CLKR(clk), .WEB(aggregate_web), .REB(aggregate_reb),
    .AA(read_slot), .AB(next_output), .D(reduced_words), .Q(aggregate_q)
  );

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      reserved <= 0;
      complete <= 0;
      head <= 0;
      tail <= 0;
      count <= 0;
      read_slot <= 0;
      out_valid <= 0;
      out_output <= 0;
      output_forward <= 0;
      forwarded_words <= 0;
    end else begin
      case ({issue, retire})
        2'b10: count <= count + 1'b1;
        2'b01: count <= count - 1'b1;
        default: count <= count;
      endcase
      if (issue) begin
        reserved[cmd_output] <= 1;
        reduce_mode[cmd_output] <= cmd_reduce;
        tag_queue[tail] <= cmd_output;
        tail <= tail + 1'b1;
      end
      if (done_aligned) read_slot <= done_slots[3:0];
      if (aggregate_write) complete[read_slot] <= 1;
      if (retire) begin
        complete[out_output] <= 0;
        reserved[out_output] <= 0;
        head <= head + 1'b1;
      end
      if (!out_valid || out_ready) begin
        out_valid <= output_refill;
        if (output_refill) begin
          out_output <= next_output;
          output_forward <= read_collision;
          if (read_collision) forwarded_words <= reduced_words;
        end
      end
    end
  end
endmodule

`ifdef TRI_ORACLE_SRAM_CLUSTER_BIND_PUBLIC
module tri_oracle_compute_cluster #(
  parameter int MERGE_FEATURES=0,
  parameter bit AGGREGATOR_MERGE_TABLE=0,
  parameter int MERGE_TABLE_ENTRIES=128,
  parameter bit CORE_STRIP_PREDICTOR=0,
  parameter bit CORE_HEAD_PREDICTOR=0,
  localparam int SIGN_WIDTH=MERGE_FEATURES==0 ? 1 : MERGE_FEATURES
) (
  input logic clk,
  input logic rst_n,
  input logic load_valid,
  input logic [1:0] load_core,
  input logic [1:0] load_kind,
  input logic [9:0] load_addr,
  input logic [2047:0] load_data,
  input logic [31:0] load_row_enable,
  output logic load_error,
  input logic cmd_valid,
  output logic cmd_ready,
  input logic [4:0] cmd_weight,
  input logic [4:0] cmd_mask,
  input logic [9:0] cmd_activation,
  input logic [3:0] cmd_output,
  input logic cmd_accumulate,
  input logic [1:0] cmd_reduce,
  output logic out_valid,
  input logic out_ready,
  output logic [3:0] out_output,
  output logic [1023:0] out_data,
  input logic [SIGN_WIDTH-1:0] merge_sign_data,
  input logic [12:0] merge_sign_control,
  output logic [23:0] merge_sign_counts,
  input logic [18:0] merge_table_request,
  output logic [79:0] merge_table_word,
  input logic strip_rst_n,
  input logic [530:0] strip_request,
  output logic [111:0] strip_response,
  input logic [396:0] head_request,
  output logic [72:0] head_response
);
  tri_oracle_sram_compute_cluster #(.MERGE_FEATURES(MERGE_FEATURES), .AGGREGATOR_MERGE_TABLE(AGGREGATOR_MERGE_TABLE), .MERGE_TABLE_ENTRIES(MERGE_TABLE_ENTRIES), .CORE_STRIP_PREDICTOR(CORE_STRIP_PREDICTOR), .CORE_HEAD_PREDICTOR(CORE_HEAD_PREDICTOR)) implementation (.*);
endmodule
`endif

/* verilator lint_off DECLFILENAME */
module tri_oracle_sram_strip_core448 #(
    parameter bit CORE_STRIP_PREDICTOR=0,
    parameter bit CORE_HEAD_PREDICTOR=0
) (
  input logic clk,
  input logic rst_n,
  input logic load_valid,
  input logic [1:0] load_kind,
  input logic [9:0] load_addr,
  input logic [2047:0] load_data,
  input logic [31:0] load_row_enable,
  output logic load_error,
  input logic cmd_valid,
  output logic cmd_ready,
  input logic [4:0] cmd_weight,
  input logic [9:0] cmd_activation,
  input logic [4:0] cmd_mask,
  input logic [3:0] cmd_output,
  input logic cmd_accumulate,
  output logic done_valid,
  output logic [3:0] done_output,
  input logic read_valid,
  input logic [3:0] read_output,
  output logic result_valid,
  output logic [1023:0] result_data,
    input logic strip_rst_n,
    input logic [146:0] strip_request,
    output logic [39:0] strip_response,
    input logic [394:0] head_request,
    output logic [72:0] head_response
);
    tri_oracle_sram_memory_compute compute (.*);
    if (CORE_HEAD_PREDICTOR) begin : head
        tri_oracle_core_head450 predict (
            .clk, .rst_n(strip_rst_n), .request(head_request), .response(head_response)
        );
    end else begin : no_head
        assign head_response='0;
    end
    if (CORE_STRIP_PREDICTOR) begin : strip
        tri_oracle_core_strip448 predict (
            .clk, .rst_n(strip_rst_n), .request(strip_request), .response(strip_response)
        );
    end else begin : no_strip
        assign strip_response='0;
    end
endmodule
/* verilator lint_on DECLFILENAME */
