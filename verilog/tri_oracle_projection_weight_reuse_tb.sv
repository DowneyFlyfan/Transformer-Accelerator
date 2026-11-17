`timescale 1ns/1ps
module tri_oracle_projection_weight_reuse_tb;
  logic clk = 0;
  always #862ps clk = ~clk;

  logic rst_n = 0, in_valid = 0, done_ready = 0;
  logic [4:0] in_tokens = 0, in_weight_base = 0;
  logic [5:0] in_strips = 0;
  logic in_ready, done_valid, done_error, backend_rst_n;
  logic backend_cmd_valid, backend_cmd_ready = 0;
  logic [4:0] backend_cmd_weight;
  logic [3:0] backend_cmd_output;
  logic [4:0] backend_out_valid, backend_out_ready;
  logic [19:0] backend_out_output;

  logic write_valid = 0, write_allowed;
  logic [4:0] write_word = 0;
  logic [127:0] write_data = 0, read_data;
  logic [4:0] last_token;
  logic read_accepted, memory_web, memory_reb;
  logic [4:0] memory_read_word;
  int reads = 0, concurrent = 0, writes = 0, blocked = 0;

  assign read_accepted = backend_cmd_valid && backend_cmd_ready;
  // The sequencer and guard are zero-delay RTL. Give their synchronous outputs
  // propagation time so they meet the timed macro model's input hold windows.
  assign #250ps memory_web = !(write_valid && write_allowed);
  assign #250ps memory_reb = !read_accepted;
  assign #250ps memory_read_word = backend_cmd_weight;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      last_token <= '0;
      backend_out_valid <= '0;
      backend_out_output <= '0;
    end else begin
      if (in_valid && in_ready) last_token <= in_tokens - 1'b1;
      backend_out_valid <= {5{read_accepted}};
      backend_out_output <= {5{backend_cmd_output}};
    end
  end

  tri_oracle_batched_projection356 projection (
    .clk, .rst_n, .in_valid, .in_ready, .in_tag(32'd18), .in_tokens,
    .in_weight_base, .in_mask_base(5'd0), .in_strips, .in_activation_base(10'd0),
    .in_activation_stride(11'd32), .in_accumulate(1'b0), .in_publish(1'b0),
    .out_valid(), .out_ready(1'b1), .out_tag(), .out_token(), .out_last(), .out_data(),
    .done_valid, .done_ready, .done_error, .done_tag(), .backend_rst_n,
    .backend_cmd_valid, .backend_cmd_ready, .backend_cmd_weight, .backend_cmd_mask(),
    .backend_cmd_activation(), .backend_cmd_output, .backend_cmd_accumulate(),
    .backend_out_valid, .backend_out_ready, .backend_out_output, .backend_out_data('0)
  );

  tri_oracle_projection_weight_reuse guard (
    .clk, .rst_n, .discard(!backend_rst_n), .reserve(in_valid && in_ready),
    .reserve_base(in_weight_base), .reserve_strips(in_strips),
    .last_read(read_accepted && 5'(backend_cmd_output) == last_token),
    .read_word(backend_cmd_weight), .write_word, .write_allowed
  );

  TS6N28HPCPSVTA32X128M2FW memory (
    .CLKW(clk), .CLKR(clk), .WEB(memory_web), .REB(memory_reb),
    .AA(write_word), .AB(memory_read_word), .D(write_data), .BWEB(128'b0), .Q(read_data)
  );

  function automatic logic [127:0] weights(input int epoch, input int word);
    return {32'(epoch+1), 32'(word), 32'(~word), 32'(epoch*33 + word)};
  endfunction

  task automatic step(input bit allow_write, input bit expect_read,
                      input int word, input int token, input int epoch);
    #20ps;
    if (write_valid && write_allowed !== allow_write)
      $fatal(1, "PROJECTION_WEIGHT_GUARD word=%0d token=%0d write_word=%0d got=%0b expected=%0b",
             word, token, write_word, write_allowed, allow_write);
    if (read_accepted !== expect_read)
      $fatal(1, "PROJECTION_WEIGHT_COMMAND word=%0d token=%0d", word, token);
    if (expect_read && (backend_cmd_weight !== 5'(word) || backend_cmd_output !== 4'(token)))
      $fatal(1, "PROJECTION_WEIGHT_ORDER word=%0d token=%0d", word, token);
    if (expect_read && write_valid && allow_write && write_word == 5'(word))
      $fatal(1, "PROJECTION_WEIGHT_COLLISION word=%0d", word);
    @(posedge clk);
    #800ps;
    if (expect_read) begin
      if (read_data !== weights(epoch, word))
        $fatal(1, "PROJECTION_WEIGHT_DATA word=%0d token=%0d epoch=%0d got=%h",
               word, token, epoch, read_data);
      reads++;
    end
    if (write_valid && allow_write) begin
      writes++;
      concurrent += int'(expect_read);
    end
    if (write_valid && !allow_write) blocked++;
  endtask

  task automatic offer(input int base, input int strips, input int tokens,
                       input int write_address, input bit allowed);
    @(negedge clk);
    if (!in_ready) $fatal(1, "PROJECTION_WEIGHT_DESCRIPTOR_BUSY");
    in_weight_base = 5'(base);
    in_strips = 6'(strips);
    in_tokens = 5'(tokens);
    in_valid = 1;
    write_valid = 1;
    write_word = 5'(write_address);
    write_data = weights(1, write_address);
    step(allowed, 0, base, -1, 0);
    @(negedge clk);
    in_valid = 0;
    write_valid = 0;
  endtask

  task automatic complete(input bit error_expected);
    wait (done_valid);
    @(negedge clk);
    if (done_error !== error_expected) $fatal(1, "PROJECTION_WEIGHT_COMPLETION");
    done_ready = 1;
    @(negedge clk);
    done_ready = 0;
  endtask

  initial begin
    repeat (3) @(negedge clk);
    rst_n = 1;
    for (int word = 0; word < 32; word++) begin
      @(negedge clk);
      write_valid = 1;
      write_word = 5'(word);
      write_data = weights(0, word);
      step(1, 0, word, -1, 0);
    end

    offer(0, 32, 16, 0, 0);
    for (int word = 0; word < 32; word++) begin
      for (int token = 0; token < 16; token++) begin
        @(negedge clk);
        write_valid = 1;
        write_word = word != 0 && token == 0 ? 5'(word - 1) : 5'(word);
        write_data = weights(1, int'(write_word));
        if (word == 7 && token == 15) begin
          backend_cmd_ready = 0;
          repeat (5) begin
            step(0, 0, word, token, 0);
            @(negedge clk);
          end
        end
        backend_cmd_ready = 1;
        step(word != 0 && token == 0, 1, word, token, 0);
      end
    end
    // The final address is writable before the final projection result retires.
    @(negedge clk);
    backend_cmd_ready = 0;
    if (done_valid || backend_out_valid !== 5'b11111)
      $fatal(1, "PROJECTION_WEIGHT_FINAL_RESULT_NOT_PENDING");
    step(1, 0, 31, 15, 0);
    @(negedge clk);
    write_valid = 0;
    complete(0);

    // The new descriptor reads the newly written generation at the upper bound.
    offer(29, 3, 1, 0, 1);
    for (int word = 29; word < 32; word++) begin
      @(negedge clk);
      backend_cmd_ready = 1;
      step(0, 1, word, 0, 1);
    end
    @(negedge clk);
    backend_cmd_ready = 0;
    complete(0);

    // A wrapping descriptor is rejected and cannot grant a write on acceptance.
    offer(31, 2, 1, 0, 0);
    complete(1);
    offer(0, 1, 1, 1, 1);
    @(negedge clk);
    backend_cmd_ready = 1;
    step(0, 1, 0, 0, 1);
    @(negedge clk);
    backend_cmd_ready = 0;
    complete(0);

    if (reads != 516 || concurrent != 31 || writes != 66 || blocked != 488)
      $fatal(1, "PROJECTION_WEIGHT_COUNTS reads=%0d concurrent=%0d writes=%0d blocked=%0d",
             reads, concurrent, writes, blocked);
    $display("PROJECTION_WEIGHT_REUSE_PASS reads=%0d concurrent=%0d writes=%0d blocked=%0d",
             reads, concurrent, writes, blocked);
    $finish;
  end

  initial begin
    #5us;
    $fatal(1, "PROJECTION_WEIGHT_TIMEOUT");
  end
endmodule
