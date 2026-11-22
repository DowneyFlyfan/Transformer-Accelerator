`timescale 1ns/1ps
// Actual compiler-backed 8KB weight, 8KB input, 1KB mask and 2KB output stores.
// A prefetched accumulator adds one completion stage. A recent-write register
// serves cluster completion reads; arbitrary read misses backpressure the array.
// Native same-address read/write operations are suppressed and forwarded.
module tri_oracle_sram_memory_compute (
  input logic clk,
  input logic rst_n,
  input logic load_valid,
  output logic load_ready,
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
  output logic [1023:0] result_data
);
  logic [2047:0] weight_q, weight_bweb;
  logic [15:0] weight_ceb, weight_web;
  logic [4:0] weight_address, mask_address;
  logic [127:0] input_q;
  logic [1:0] input_ceb, input_web;
  logic [8:0] input_address;
  logic [255:0] mask_q;
  logic mask_ceb, mask_web;
  logic command_pending, input_bank;
  logic [3:0] read_slot, slot_pipe[4];
  logic read_accumulate;
  logic [3:0] accumulate_pipe;
  logic array_ready, array_valid, array_out_ready, accept_command, accept_array;
  logic [2047:0] repeated_activation;
  logic [607:0] array_sums, writeback_sums;
  logic writeback_valid, writeback_accumulate, accumulator_forward;
  logic [3:0] writeback_slot, memory_read_address, recent_slot;
  logic [1023:0] output_q, accumulator_forward_data, accumulator_word, writeback_data;
  logic [1023:0] recent_data, response_bypass_data, held_result;
  logic recent_valid, current_write_hit, recent_hit, external_miss;
  logic memory_read_collision, memory_read_enable, output_web, output_reb;
  logic response_bypass;

  // Output slots share the existing macro ports; no context data flops.
  logic [2:0] context_outstanding;
  logic [15:0] context_owned;
  logic [3:0] context_release_slot;
  logic matrix_load_ready, context_load_ready, context_write, context_release;
  logic [3:0] output_write_address;
  logic [1023:0] output_write_data;
  logic accepted_load, compute_enabled, softmax_configure, softmax_owns_input;
  logic simd_cfg_ready;
  logic [1:0] simd_mem_ce_n, simd_mem_we_n;
  logic [8:0] simd_mem_address;
  logic [1:0][63:0] simd_mem_d, imem_d;
  logic [1:0] imem_ce_n, imem_we_n;
  logic [8:0] imem_address;

  assign context_load_ready = rst_n && context_outstanding==0 && !read_valid
                              && !result_valid && !writeback_valid;
  assign load_ready = load_kind==3 ? context_load_ready : matrix_load_ready;
  assign accepted_load = load_valid && load_ready;
  assign context_write = accepted_load && load_kind==3 && load_addr<16;
  assign context_release = accepted_load && load_kind==3 && ((load_addr>=16 && load_addr<=17) || (load_addr>=32 && load_addr<=47));
  assign context_release_slot = load_addr>=32 ? load_addr[3:0] : 4'd14+4'(load_addr[0]);
  assign output_write_address = context_write ? load_addr[3:0] : writeback_slot;
  assign output_write_data = context_write ? load_data[1023:0] : writeback_data;
  assign softmax_cfg_ready = softmax_configure && simd_cfg_ready;
  assign imem_ce_n = softmax_owns_input ? simd_mem_ce_n : input_ceb;
  assign imem_we_n = softmax_owns_input ? simd_mem_we_n : input_web;
  assign imem_address = softmax_owns_input ? simd_mem_address : input_address;
  assign imem_d = softmax_owns_input ? simd_mem_d : {2{load_data[63:0]}};

  tri_oracle_wac_imem_owner input_owner (
    .clk, .rst_n, .load_ready(matrix_load_ready), .activation_reloaded, .activation_reload_required,
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

  always_comb begin
    cmd_ready = compute_enabled && array_ready && !accepted_load
                && !context_owned[cmd_output];
    accept_command = rst_n && cmd_valid && cmd_ready;
    current_write_hit = writeback_valid && read_output == writeback_slot;
    recent_hit = recent_valid && read_output == recent_slot;
    external_miss = read_valid && !current_write_hit && !recent_hit;
    array_out_ready = !external_miss;
    accept_array = rst_n && array_valid && array_out_ready;
    memory_read_address = external_miss ? read_output : slot_pipe[3];
    memory_read_collision = writeback_valid && memory_read_address == writeback_slot;
    memory_read_enable = rst_n && (external_miss || accept_array) && !memory_read_collision;
    output_reb = !memory_read_enable;
    output_web = !(rst_n && (writeback_valid || context_write));
    accumulator_word = accumulator_forward ? accumulator_forward_data : output_q;
    for (integer row = 0; row < 32; row++) begin
      if (writeback_accumulate)
        writeback_data[row*32+:32] = accumulator_word[row*32+:32]
            + {{13{writeback_sums[row*19+18]}}, writeback_sums[row*19+:19]};
      else
        writeback_data[row*32+:32] = {{13{writeback_sums[row*19+18]}},
                                     writeback_sums[row*19+:19]};
    end
    repeated_activation = {32{input_q[input_bank*64+:64]}};
    result_data = result_valid ? (response_bypass ? response_bypass_data : output_q)
                               : held_result;
    weight_address = accepted_load ? load_addr[4:0] : cmd_weight;
    mask_address = accepted_load ? load_addr[4:0] : cmd_mask;
    input_address = accepted_load ? load_addr[8:0] : cmd_activation[8:0];
    for (integer row = 0; row < 32; row++)
      weight_bweb[row*64+:64] = {64{!load_row_enable[row]}};
    for (integer bank = 0; bank < 16; bank++) begin
      weight_web[bank] = !(rst_n && accepted_load && load_kind == 0 && load_addr < 32
                          && (|load_row_enable[bank*2+:2]));
      weight_ceb[bank] = weight_web[bank] && !accept_command;
    end
    for (integer bank = 0; bank < 2; bank++) begin
      input_web[bank] = !(rst_n && accepted_load && load_kind == 1
                         && load_addr[9] == 1'(bank));
      input_ceb[bank] = input_web[bank] && !(accept_command
                                          && cmd_activation[9] == 1'(bank));
    end
    mask_web = !(rst_n && accepted_load && load_kind == 2 && load_addr < 32);
    mask_ceb = mask_web && !accept_command;
  end

  // Instance arrays partition wide data/masks and broadcast their common address.
  TS5N28HPCPSVTA32X128M2FW weights[15:0] (
    .CLK(clk), .CEB(weight_ceb), .WEB(weight_web), .A(weight_address),
    .D(load_data), .BWEB(weight_bweb), .Q(weight_q)
  );
  TS5N28HPCPSVTA512X64M4F inputs[1:0] (
    .CLK(clk), .CEB(imem_ce_n), .WEB(imem_we_n), .A(imem_address),
    .D(imem_d), .Q(input_q)
  );
  TS5N28HPCPSVTA32X128M2FW masks[1:0] (
    .CLK(clk), .CEB(mask_ceb), .WEB(mask_web), .A(mask_address),
    .D(load_data[255:0]), .BWEB(128'b0), .Q(mask_q)
  );
  TS6N28HPCPSVTA16X128M2F outputs[7:0] (
    .CLKW(clk), .CLKR(clk), .WEB(output_web), .REB(output_reb),
    .AA(output_write_address), .AB(memory_read_address), .D(output_write_data), .Q(output_q)
  );
  tri_oracle_pe_array compute (
    .clk(clk), .rst_n(rst_n), .in_valid(command_pending), .in_ready(array_ready),
    .operand_a(repeated_activation), .operand_b(weight_q), .lane_enable(mask_q),
    .out_valid(array_valid), .out_ready(array_out_ready), .out_sums(array_sums)
  );

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      context_outstanding <= 0;
      context_owned <= 0;
      command_pending <= 0;
      input_bank <= 0;
      read_slot <= 0;
      read_accumulate <= 0;
      accumulate_pipe <= 0;
      for (integer stage = 0; stage < 4; stage++) slot_pipe[stage] <= 0;
      load_error <= 0;
      writeback_valid <= 0;
      writeback_accumulate <= 0;
      writeback_slot <= 0;
      writeback_sums <= 0;
      accumulator_forward <= 0;
      accumulator_forward_data <= 0;
      recent_valid <= 0;
      recent_slot <= 0;
      recent_data <= 0;
      done_valid <= 0;
      done_output <= 0;
      result_valid <= 0;
      response_bypass <= 0;
      response_bypass_data <= 0;
      held_result <= 0;
    end else begin
      case ({accept_command,done_valid})
        2'b10: context_outstanding <= context_outstanding+3'd1;
        2'b01: context_outstanding <= context_outstanding-3'd1;
        default: ;
      endcase
      if (context_write) context_owned[load_addr[3:0]] <= 1;
      if (context_release) context_owned[context_release_slot] <= 0;
      if (context_write && recent_valid && recent_slot==load_addr[3:0]) recent_valid <= 0;
      load_error <= accepted_load && (((load_kind == 0 || load_kind == 2) && load_addr >= 32)
                                  || (load_kind==3 && !((load_addr<=17) || (load_addr>=32 && load_addr<=47))));
      if (array_ready) begin
        command_pending <= accept_command;
        slot_pipe[0] <= read_slot;
        accumulate_pipe[0] <= read_accumulate;
        for (integer stage = 1; stage < 4; stage++) begin
          slot_pipe[stage] <= slot_pipe[stage-1];
          accumulate_pipe[stage] <= accumulate_pipe[stage-1];
        end
      end
      if (accept_command) begin
        input_bank <= cmd_activation[9];
        read_slot <= cmd_output;
        read_accumulate <= cmd_accumulate;
      end
      writeback_valid <= accept_array;
      if (accept_array) begin
        writeback_slot <= slot_pipe[3];
        writeback_accumulate <= accumulate_pipe[3];
        writeback_sums <= array_sums;
        accumulator_forward <= memory_read_collision;
        if (memory_read_collision) accumulator_forward_data <= writeback_data;
      end
      done_valid <= writeback_valid;
      if (writeback_valid) begin
        done_output <= writeback_slot;
        recent_valid <= 1;
        recent_slot <= writeback_slot;
        recent_data <= writeback_data;
      end
      result_valid <= read_valid;
      if (result_valid) held_result <= result_data;
      if (read_valid) begin
        response_bypass <= current_write_hit || recent_hit;
        if (current_write_hit) response_bypass_data <= accumulator_word;
        else if (recent_hit) response_bypass_data <= recent_data;
      end
    end
  end
endmodule
