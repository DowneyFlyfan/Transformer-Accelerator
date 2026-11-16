`timescale 1ns/1ps

module tri_oracle_memory_tx_credit_trial #(
  parameter int Return_Cycles = 4,
  parameter bit Full_Rate = 1
) (output bit done);
  localparam int Credits = 16;
  localparam int Words = 96;
  bit clk = 0, rst_n = 0;
  // Round each half-period to the nearest picosecond.
  always #0.862 clk = !clk;

  logic valid = 0, ready, pad_valid, pad_clock, pad_credit, sender_error;
  logic [21:0] tx_word;
  logic [7:0] pad_data;
  tri_oracle_memory_tx_credit #(.CREDITS(Credits)) sender (
    .clk, .rst_n, .in_valid(valid), .in_ready(ready), .in_word(tx_word),
    .pad_valid, .pad_data, .pad_clock, .pad_credit, .protocol_error(sender_error)
  );

  // The board uses the clock forwarded by the chip. Neither direction
  // returns a ready value combinationally.
  logic peer_clk, peer_valid;
  logic [7:0] peer_data;
  // Transport delays preserve transitions even when propagation takes
  // more than a clock period.
  always @(pad_clock) peer_clk <= #2.12 pad_clock;
  always @(pad_valid) peer_valid <= #1.97 pad_valid;
  always @(pad_data) peer_data <= #2.02 pad_data;

  logic full, empty, head_valid, head_ready;
  logic [7:0] head;
  wire reload = !head_valid || head_ready;
  wire issue_head = reload && (!empty || peer_valid);
  logic [Return_Cycles-1:0] credits_in_flight;
  tri_oracle_credit_bypass_fifo #(.WIDTH(8), .DEPTH(Credits)) queue (
    .clk(peer_clk), .rst_n, .read_enable(reload), .write_enable(peer_valid),
    .write_data(peer_data), .read_data(head), .full, .empty
  );
  always_ff @(posedge peer_clk or negedge rst_n) begin
    if (!rst_n) begin
      head_valid <= 0;
      credits_in_flight <= '0;
    end else begin
      if (reload) head_valid <= issue_head;
      credits_in_flight <= {credits_in_flight[Return_Cycles-2:0], issue_head};
    end
  end
  always @(credits_in_flight) pad_credit <= #0.79 credits_in_flight[Return_Cycles-1];

  logic recovered_valid, recovered_ready;
  logic [21:0] recovered_word;
  tri_oracle_flit_from_pads peer_decoder (
    .clk(peer_clk), .rst_n, .pad_valid(head_valid), .pad_ready(head_ready), .pad_data(head),
    .out_valid(recovered_valid), .out_ready(recovered_ready), .out_word(recovered_word)
  );

  int received, input_words, printed_bytes, frame_bubbles, source_stalls;
  int peer_ticks;
  bit warmup, stress, sending, started;

  function automatic logic [21:0] fixture(input int index, input bit second);
    return 22'(32'h93c1bfa4 * 32'(index + 1) ^ (second ? 32'hc752b : 32'h10a3c));
  endfunction

  assign recovered_ready = !warmup && (!stress || (peer_ticks > 100 && peer_ticks % 13 >= 4));

  always @(posedge peer_clk or negedge rst_n) begin
    if (!rst_n) begin
      received = 0;
      peer_ticks <= 0;
    end else begin
      peer_ticks <= peer_ticks + 1;
      if (full && peer_valid) $fatal(1, "PEER_FIFO_OVERFLOW");
      if (recovered_valid && recovered_ready) begin
        if (received >= input_words || recovered_word !== fixture(received, stress))
          $fatal(1, "RECOVERED_WORD_MISMATCH ordinal=%0d", received);
        received++;
      end
    end
  end

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      input_words = 0;
      printed_bytes = 0;
      frame_bubbles = 0;
      source_stalls = 0;
      started = 0;
    end else begin
      if (sender_error) $fatal(1, "UNEXPECTED_CREDIT_OVERFLOW");
      if (valid && ready) input_words++;
      if (pad_valid) begin
        started = 1;
        printed_bytes++;
      end else if (started && printed_bytes < 3 * Words && sending)
        frame_bubbles++;
      if (valid && !ready) source_stalls++;
    end
  end

  task automatic reset_link();
    rst_n = 0;
    valid = 0;
    sending = 0;
    repeat (16) @(negedge clk);
    rst_n = 1;
  endtask

  task automatic deliver();
    sending = 1;
    valid = 1;
    while (input_words < Words) begin
      tx_word = fixture(input_words, stress);
      @(negedge clk);
    end
    valid = 0;
    wait(received == Words);
    @(negedge clk);
    sending = 0;
    if (printed_bytes != 3 * Words) $fatal(1, "TRANSMITTED_BYTE_COUNT");
  endtask

  initial begin
    stress = 0;
    warmup = 1;
    reset_link();
    valid = 1;
    tx_word = fixture(0, 0);
    repeat (2) @(negedge clk);
    if (printed_bytes == 0 || received != 0) $fatal(1, "RESET_DID_NOT_INTERRUPT_ACTIVE_LINK");
    reset_link();
    warmup = 0;
    deliver();
    if ((frame_bubbles == 0) != Full_Rate) $fatal(1, "NO_STALL_RATE_MISMATCH");
    $display("MEMORY_TX_CREDIT_RATE_PASS delay=%0d words=%0d bytes=%0d bubbles=%0d",
             Return_Cycles, received, printed_bytes, frame_bubbles);
    repeat (30) @(negedge clk);
    reset_link();
    stress = 1;
    deliver();
    if (frame_bubbles < 25 || source_stalls < 100) $fatal(1, "INSUFFICIENT_BACKPRESSURE");
    $display("MEMORY_TX_CREDIT_STALL_PASS delay=%0d words=%0d bytes=%0d bubbles=%0d",
             Return_Cycles, received, printed_bytes, frame_bubbles);
    done = 1;
  end
endmodule

module tri_oracle_memory_tx_credit_tb;
  wire [2:0] done;
  bit fault_done = 0;
  bit fault_clk = 0, fault_reset_n = 0, extra_credit = 0;
  wire fault;
  always #0.862 fault_clk = !fault_clk;
  tri_oracle_memory_tx_credit unsolicited_credit (
    .clk(fault_clk), .rst_n(fault_reset_n), .in_valid(1'b0), .in_ready(), .in_word(22'd0),
    .pad_valid(), .pad_data(), .pad_clock(), .pad_credit(extra_credit), .protocol_error(fault)
  );
  tri_oracle_memory_tx_credit_trial #(.Return_Cycles(4)) a (done[0]);
  tri_oracle_memory_tx_credit_trial #(.Return_Cycles(8)) b (done[1]);
  tri_oracle_memory_tx_credit_trial #(.Return_Cycles(18), .Full_Rate(0)) c (done[2]);
  initial begin
    repeat (3) @(negedge fault_clk);
    fault_reset_n = 1;
    extra_credit = 1;
    @(negedge fault_clk);
    extra_credit = 0;
    repeat (3) @(negedge fault_clk);
    if (fault !== 1'b1) $fatal(1, "UNSOLICITED_CREDIT_WAS_ACCEPTED");
    fault_reset_n = 0;
    @(negedge fault_clk);
    if (fault !== 1'b0) $fatal(1, "CREDIT_PROTOCOL_ERROR_NOT_RESET");
    $display("MEMORY_TX_UNSOLICITED_CREDIT_PASS");
    fault_done = 1;
  end
  initial begin
    wait ((&done) && fault_done);
    $finish;
  end
  initial begin
    #4000;
    $fatal(1, "MEMORY_TX_CREDIT_TIMEOUT");
  end
endmodule
