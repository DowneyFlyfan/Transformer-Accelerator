`timescale 1ns/1ps

module tri_oracle_host_status_link_tb;
  logic clk=0, rst_n=0;
  always #5 clk=!clk;

  logic rx_valid=0, rx_ready, rx_is_payload, rx_payload_last;
  logic [15:0] rx_data;
  logic forward_valid;
  logic control_valid, control_ready;
  logic [1:0] control_action;
  logic gamma_valid, gamma_ready=0;
  logic [127:0] gamma_data;
  logic [26:0] chip_status=0;
  logic residual_lease;
  logic source_valid=0, source_ready, source_last;
  logic [15:0] source_data;
  logic tx_valid, tx_ready, tx_last;
  logic [15:0] tx_data;
  int cycles=0, forwarded=0, gamma_transfers=0, controls=0, old_words=0, replies=0, held_count=0;
  int word_index=0;
  logic held=0, held_last;
  logic [15:0] held_data;
  localparam logic [127:0] GAMMA = 128'h0007a6820005a67e0003000200010000;
  localparam logic [27:0] EXPECTED [4] = '{28'h4012345,28'h8012345,28'hc076543,28'h0076543};
  localparam logic [1:0] ACTIONS [4] = '{2'd0,2'd2,2'd0,2'd1};
  localparam logic [15:0] FORWARDED [3] = '{16'hb012,16'ha67e,16'ha682};

  assign tx_ready = cycles%11 >= 5;
  always @(negedge clk) cycles <= cycles+1;

  tri_oracle_host_boundary_rx boundary_rx (
    .clk, .rst_n, .rx_valid, .rx_ready, .rx_is_payload, .rx_payload_last, .rx_data,
    .forward_valid, .forward_ready(1'b1), .control_valid, .control_ready, .control_action,
    .operand_valid(), .operand_ready(1'b0), .residual_q32(), .projection_shift(),
    .gamma_valid, .gamma_ready, .gamma_data,
    .stats_valid(), .stats_last(), .stats_ready(1'b0), .stats_data(),
    .replay_valid(), .replay_last(), .replay_ready(1'b0), .replay_data(), .replay_gamma()
  );
  tri_oracle_host_status_link status_link (.*);

  always @(posedge clk) if (rst_n) begin
    if (forward_valid) begin
      if (forwarded>=3 || rx_data!==FORWARDED[forwarded])
        $fatal(1,"STATUS_CONTROL_MISROUTED word=%h",rx_data);
      forwarded++;
    end
    if (control_valid && control_ready) begin
      if (controls>=4 || control_action!==ACTIONS[controls])
        $fatal(1,"STATUS_ACTION_MISDECODED");
      controls++;
    end
    if (gamma_valid) begin
      if (gamma_data!==GAMMA) $fatal(1,"STATUS_ALTERED_GAMMA_BODY");
      if (gamma_ready) gamma_transfers++;
    end
    if (held && (!tx_valid || tx_last!==held_last || tx_data!==held_data))
      $fatal(1,"STATUS_CHANGED_DURING_BACKPRESSURE");
    held = tx_valid && !tx_ready;
    if (held) begin
      held_count++;
      held_last = tx_last;
      held_data = tx_data;
    end
    if (tx_valid && tx_ready) begin
      logic [15:0] expected_word;
      if (old_words<3) begin
        if (tx_data!==16'(16'h9210+old_words) || tx_last!==(old_words==2))
          $fatal(1,"STATUS_INTERLEAVED_LEGACY_RESPONSE");
        old_words++;
      end else begin
        if (replies>=4) $fatal(1,"STATUS_EXTRA_REPLY");
        case (word_index)
          0: expected_word=16'ha684;
          1: expected_word=EXPECTED[replies][15:0];
          2: expected_word={4'b0,EXPECTED[replies][27:16]};
          3: expected_word={14'b0,ACTIONS[replies]};
          default: $fatal(1,"STATUS_REPLY_LENGTH");
        endcase
        if (tx_data!==expected_word || tx_last!==(word_index==3))
          $fatal(1,"STATUS_REPLY_DATA reply=%0d word=%0d expected=%h got=%h",
                 replies,word_index,expected_word,tx_data);
        if (tx_last) begin
          replies++;
          word_index=0;
        end else word_index++;
      end
    end
  end

  task automatic send(input logic [15:0] word, input bit aux_flags=1);
    rx_data=word;
    rx_is_payload=0;
    rx_payload_last=aux_flags;
    rx_valid=1;
    do @(posedge clk); while (!rx_ready);
    @(negedge clk);
    rx_valid=0;
  endtask

  initial begin
    repeat (3) @(negedge clk);
    rst_n=1;
    fork
      begin
        for (int word=0; word<3; word++) begin
          source_valid=1;
          source_last=word==2;
          source_data=16'(16'h9210+word);
          do @(posedge clk); while (!source_ready);
          @(negedge clk);
          source_valid=0;
          repeat (5) @(negedge clk);
        end
      end
      begin
        send(16'hb012,0);
        send(16'ha67e);
        send(16'ha682);
        chip_status=27'h4012345;
        @(negedge clk);
        chip_status[26]=0;
        send(16'ha67e);
        send(16'ha683);
        if (!residual_lease) $fatal(1,"STATUS_LEASE_SET_DROPPED");
        send(16'ha679);
        for (int word=0; word<8; word++) send(GAMMA[16*word+:16]);
        repeat (7) @(negedge clk);
        gamma_ready=1;
        @(negedge clk);
        gamma_ready=0;
        chip_status=27'h4076543;
        send(16'ha67e);
        chip_status[26]=0;
        send(16'ha682);
        if (residual_lease) $fatal(1,"STATUS_LEASE_CLEAR_DROPPED");
      end
    join
    wait (replies==4);
    repeat (6) @(negedge clk);
    if ({forwarded,gamma_transfers,controls,old_words} !== {32'd3,32'd1,32'd4,32'd3} ||
        held_count==0 || tx_valid)
      $fatal(1,"STATUS_TEST_COVERAGE");
    $display("HOST_STATUS_LINK_PASS replies=4 forward_words=3 gamma_records=1 held=%0d",held_count);
    $finish;
  end

  initial begin
    repeat (300) @(negedge clk);
    $fatal(1,"STATUS_LINK_TIMEOUT replies=%0d",replies);
  end
endmodule
