`timescale 1ns/1ps
// Actual compiler-backed 8KB weight, 8KB input, 1KB mask and 2KB output stores.
// A prefetched accumulator adds one completion stage. A recent-write register
// serves cluster completion reads; arbitrary read misses backpressure the array.
// Native same-address read/write operations are suppressed and forwarded.
module tri_oracle_sram_memory_compute (
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

  always_comb begin
    cmd_ready = array_ready && !load_valid;
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
    output_web = !(rst_n && writeback_valid);
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
    weight_address = load_valid ? load_addr[4:0] : cmd_weight;
    mask_address = load_valid ? load_addr[4:0] : cmd_mask;
    input_address = load_valid ? load_addr[8:0] : cmd_activation[8:0];
    for (integer row = 0; row < 32; row++)
      weight_bweb[row*64+:64] = {64{!load_row_enable[row]}};
    for (integer bank = 0; bank < 16; bank++) begin
      weight_web[bank] = !(rst_n && load_valid && load_kind == 0 && load_addr < 32
                          && (|load_row_enable[bank*2+:2]));
      weight_ceb[bank] = weight_web[bank] && !accept_command;
    end
    for (integer bank = 0; bank < 2; bank++) begin
      input_web[bank] = !(rst_n && load_valid && load_kind == 1
                         && load_addr[9] == 1'(bank));
      input_ceb[bank] = input_web[bank] && !(accept_command
                                          && cmd_activation[9] == 1'(bank));
    end
    mask_web = !(rst_n && load_valid && load_kind == 2 && load_addr < 32);
    mask_ceb = mask_web && !accept_command;
  end

  // Instance arrays partition wide data/masks and broadcast their common address.
  TS5N28HPCPSVTA32X128M2FW weights[15:0] (
    .CLK(clk), .CEB(weight_ceb), .WEB(weight_web), .A(weight_address),
    .D(load_data), .BWEB(weight_bweb), .Q(weight_q)
  );
  TS5N28HPCPSVTA512X64M4F inputs[1:0] (
    .CLK(clk), .CEB(input_ceb), .WEB(input_web), .A(input_address),
    .D(load_data[63:0]), .Q(input_q)
  );
  TS5N28HPCPSVTA32X128M2FW masks[1:0] (
    .CLK(clk), .CEB(mask_ceb), .WEB(mask_web), .A(mask_address),
    .D(load_data[255:0]), .BWEB(128'b0), .Q(mask_q)
  );
  TS6N28HPCPSVTA16X128M2F outputs[7:0] (
    .CLKW(clk), .CLKR(clk), .WEB(output_web), .REB(output_reb),
    .AA(writeback_slot), .AB(memory_read_address), .D(writeback_data), .Q(output_q)
  );
  tri_oracle_pe_array compute (
    .clk(clk), .rst_n(rst_n), .in_valid(command_pending), .in_ready(array_ready),
    .operand_a(repeated_activation), .operand_b(weight_q), .lane_enable(mask_q),
    .out_valid(array_valid), .out_ready(array_out_ready), .out_sums(array_sums)
  );

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
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
      load_error <= load_valid && (load_kind == 3
                                  || ((load_kind == 0 || load_kind == 2) && load_addr >= 32));
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

`ifdef TRI_ORACLE_SRAM_CORE_BIND_PUBLIC
module tri_oracle_memory_compute (
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
  output logic [1023:0] result_data
);
  tri_oracle_sram_memory_compute implementation (.*);
endmodule
`endif
