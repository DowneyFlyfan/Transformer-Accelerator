`timescale 1ps/1ps
module tri_oracle_weight_phase_port_tb;
  localparam int Banks = 16, WeightBits = 128*Banks;
  logic memory_clk = 0, rst_n = 1, core_clk;
  always #431ps memory_clk = !memory_clk;

  logic read_valid = 0, reserve = 0, last_read = 0, block_writes = 0;
  logic [4:0] read_address = 0, memory_address;
  logic [Banks-1:0] memory_ce_n;
  logic memory_we_n;
  logic [WeightBits-1:0] memory_d, memory_bwe_n, memory_q;
  logic [1:0] raw_valid = 0, raw_ready, pending, permitted, granted;
  logic [1:0] selected, active_lane, retired, committed;
  logic [1:0][4:0] raw_core = {5'd1, 5'd0}, buffered_core;
  logic [1:0][9:0] raw_address = '0, buffered_address;
  logic [1:0][31:0] raw_rows = '0, buffered_rows;
  logic [1:0][1023:0] raw_data = '0, buffered_data;
  logic source_done = 0, source_done_ready, done;
  logic [WeightBits-1:0] expected [32], next_data;
  logic [31:0] initialized = 0, unread = 0;
  logic next_read = 0;
  logic [4:0] next_address;
  logic [1:0] observed_commit = 0;
  logic selected_lane;
  int read_checks = 0, write_checks = 0, simultaneous = 0, protected_cycles = 0;
  int sustained = 0, longest_sustained = 0, replacements = 0, same_address = 0;
  int enabled_bank_writes = 0, disabled_bank_writes = 0;
  bit stress = 0;

  tri_oracle_weight_phase_clock clock_divider (.memory_clk, .rst_n, .core_clk);

  tri_oracle_weight_write_buffer buffer (
    .clk(core_clk), .rst_n, .load_valid(raw_valid), .load_ready(raw_ready), .pending,
    .load_core(raw_core), .load_addr(raw_address), .load_row_enable(raw_rows),
    .load_payload(raw_data), .write_ready(retired), .write_valid(committed),
    .write_core(buffered_core), .write_addr(buffered_address), .write_row_enable(buffered_rows),
    .write_payload(buffered_data), .loader_done_valid(source_done), .loader_done_error(1'b0),
    .loader_done_ready(source_done_ready), .done_ready(1'b1), .done_valid(done), .done_error()
  );

  for (genvar lane = 0; lane < 2; lane++) begin : gen_lane
    tri_oracle_projection_weight_reuse guard (
      .clk(core_clk), .rst_n, .discard(1'b0), .reserve,
      .reserve_base(5'd0), .reserve_strips(6'd32),
      .last_read(read_valid && last_read), .read_word(read_address),
      .write_word(buffered_address[lane][4:0]), .write_allowed(permitted[lane])
    );
  end
  weight_stream_write_arbiter select_write (
    .clk(core_clk), .rst_n, .offered(pending), .core(buffered_core),
    .memory_ready(permitted & pending & {2{!block_writes}}), .granted
  );
  assign selected = pending & granted;
  assign selected_lane = selected[1];

  logic [Banks-1:0] bank_enables;
  for (genvar bank = 0; bank < Banks; bank++) begin : gen_bank
    assign bank_enables[bank] = |buffered_rows[selected_lane][2*bank+:2];
    assign memory_bwe_n[128*bank+:128] = {{64{!buffered_rows[active_lane[1]][2*bank+1]}},
                                        {64{!buffered_rows[active_lane[1]][2*bank]}}};
  end

  tri_oracle_weight_phase_port port_control (
    .memory_clk, .core_clk, .rst_n, .read_valid, .read_address,
    .write_select(selected), .write_address(buffered_address[selected_lane][4:0]),
    .write_banks(bank_enables),
    .active_write_lane(active_lane), .write_retired(retired),
    .memory_address, .memory_ce_n, .memory_we_n
  );

  assign memory_d = {2{buffered_data[active_lane[1]]}};
  TS5N28HPCPSVTA32X128M2FW memory[Banks-1:0] (
    .CLK(memory_clk), .CEB(memory_ce_n), .WEB(memory_we_n), .A(memory_address),
    .D(memory_d), .BWEB(memory_bwe_n), .Q(memory_q)
  );

  always @(posedge memory_clk) if (rst_n) begin
    if (core_clk) begin
      if (memory_ce_n !== {Banks{!next_read}} || !memory_we_n ||
          (next_read && memory_address !== next_address)) $fatal(1, "WEIGHT_PHASE_READ_SLOT");
    end else if (!(&memory_ce_n)) begin
      if (memory_we_n || !(^active_lane) || observed_commit != 0 ||
          memory_address !== buffered_address[active_lane[1]][4:0] ||
          unread[memory_address]) $fatal(1, "WEIGHT_PHASE_WRITE_SLOT");
      if (!initialized[memory_address] && memory_bwe_n != 0)
        $fatal(1, "WEIGHT_PHASE_MASKED_INITIALIZATION");
      for (int bank = 0; bank < Banks; bank++) begin
        if (memory_ce_n[bank] !== (&memory_bwe_n[128*bank+:128]))
          $fatal(1, "WEIGHT_PHASE_BANK_ENABLE bank=%0d", bank);
        if (memory_ce_n[bank]) disabled_bank_writes++;
        else enabled_bank_writes++;
      end
      if (next_read && next_address == memory_address) same_address++;
      expected[memory_address] = (expected[memory_address] & memory_bwe_n) |
          (memory_d & ~memory_bwe_n);
      initialized[memory_address] = 1;
      observed_commit = active_lane;
      write_checks++;
    end
  end

  always @(posedge core_clk or negedge rst_n) begin
    if (!rst_n) begin
      next_read = 0;
      unread = 0;
      observed_commit = 0;
    end else begin
      if (committed !== observed_commit) $fatal(1, "WEIGHT_PHASE_ACK_BEFORE_WRITE");
      if (next_read) begin
        if (memory_q !== next_data) $fatal(1, "WEIGHT_PHASE_DATA address=%0d", next_address);
        read_checks++;
        if (|observed_commit) simultaneous++;
      end
      sustained = stress && next_read && (|observed_commit) ? sustained + 1 : 0;
      if (sustained > longest_sustained) longest_sustained = sustained;
      if (|(committed & raw_valid & raw_ready)) replacements++;
      if (|(pending & ~permitted)) protected_cycles++;
      observed_commit = 0;
      next_read = read_valid;
      next_address = read_address;
      if (read_valid) next_data = expected[read_address];
      if (reserve) unread = '1;
      else if (read_valid && last_read) unread[read_address] = 0;
    end
  end

  function automatic logic [127:0] value(input int tag, input int index);
    return {32'(tag), 32'(index), 32'(~(tag+index)), 32'(tag*311 + index)};
  endfunction

  task automatic load_range(input int lane, input int count, input int first,
                            input int step, input bit full_word, input int tag);
    @(negedge core_clk);
    for (int index = 0; index < count; index++) begin
      raw_valid[lane] = 1;
      raw_address[lane] = 10'((first + index * step) % 32);
      raw_rows[lane] = full_word ? '1 : (index%2 == 0 ? 32'h0000_4949 : 32'h0000_9696)
          << (index%4 < 2 ? 0 : 16);
      for (int bank = 0; bank < 8; bank++)
        raw_data[lane][bank*128+:128] = value(tag+bank*17, index);
      do @(posedge core_clk); while (!raw_ready[lane]);
      @(negedge core_clk);
    end
    raw_valid[lane] = 0;
  endtask

  task automatic read_range(input int count, input bit protect);
    @(negedge core_clk);
    reserve = protect;
    @(negedge core_clk);
    reserve = 0;
    for (int index = 0; index < count; index++) begin
      read_address = protect ? 5'(index/4) : 5'(index+7);
      read_valid = 1;
      last_read = protect && index%4 == 3;
      @(negedge core_clk);
    end
    read_valid = 0;
    last_read = 0;
  endtask

  initial begin
    #40ps rst_n = 0;
    repeat (4) @(negedge memory_clk);
    #120ps rst_n = 1;
    fork
      load_range(0, 32, 0, 1, 1, 1);
      begin
        do @(posedge memory_clk);
        while (core_clk || (&memory_ce_n) || memory_address != 31);
        // Changing the next write's permission cannot cancel an actual write.
        #150ps block_writes = 1;
        @(negedge core_clk);
        block_writes = 0;
      end
    join
    wait (pending == 0);
    @(negedge core_clk);
    fork
      read_range(128, 1);
      load_range(0, 16, 0, 2, 0, 2);
      load_range(1, 16, 1, 2, 0, 3);
    join
    wait (pending == 0);
    @(negedge core_clk);
    stress = 1;
    fork
      read_range(256, 0);
      load_range(0, 128, 0, 1, 0, 4);
      load_range(1, 128, 13, 1, 0, 5);
    join
    wait (pending == 0);
    @(negedge core_clk);
    stress = 0;
    read_range(32, 0);

    block_writes = 1;
    load_range(0, 1, 0, 1, 0, 6);
    source_done = 1;
    repeat (3) begin
      @(negedge core_clk);
      if (pending !== 1 || done || source_done_ready) $fatal(1, "WEIGHT_PHASE_EARLY_DONE");
    end
    #85ps rst_n = 0;
    source_done = 0;
    block_writes = 0;
    repeat (4) @(negedge memory_clk);
    #120ps rst_n = 1;
    repeat (4) @(negedge core_clk);
    if (pending !== 0 || retired !== 0 || write_checks != 320 || read_checks != 416 ||
        protected_cycles < 100 || replacements < 200 || longest_sustained < 240 ||
        simultaneous < 270 || same_address == 0 || disabled_bank_writes == 0 ||
        enabled_bank_writes+disabled_bank_writes != 5120) $fatal(1, "WEIGHT_PHASE_COVERAGE");
    $display("WEIGHT_PHASE_PASS reads=%0d writes=%0d simultaneous=%0d sustained=%0d",
             read_checks, write_checks, simultaneous, longest_sustained);
    $display("WEIGHT_PHASE_STALLS protected=%0d replacements=%0d same_address=%0d",
             protected_cycles, replacements, same_address);
    $display("WEIGHT_PHASE_BANKS reads=%0d writes=%0d disabled=%0d",
             Banks*read_checks, enabled_bank_writes, disabled_bank_writes);
    $finish;
  end

  initial begin
    #5us;
    $fatal(1, "WEIGHT_PHASE_TIMEOUT");
  end
endmodule
