`timescale 1ns/1ps

module tri_oracle_host_control_tb;
  bit clk=0, rst_n=0;
  always #5 clk=!clk;
  logic rx_valid=0, rx_ready, rx_is_payload=0, rx_payload_last=0;
  logic [15:0] rx_data=0;
  logic link_valid, link_ready=1, config_enable=0;
  logic angle_valid, angle_ready=0, angle_last;
  logic [1023:0] angle_data;
  logic [63:0] context_base, value_read_base;
  logic source_valid=0, source_last=0, source_ready;
  logic [15:0] source_data=0;
  logic tx_valid, tx_last, tx_ready=0;
  logic [15:0] tx_data;
  logic [41:0] head_values=42'h2ABCDEF0123;
  logic [2047:0] result_values;
  localparam logic [127:0] Bases=128'hF234ABC002600000_8965123434000100;
  int receive_words, complete_responses;

  tri_oracle_host_control_rx rx (.*);
  tri_oracle_host_control_tx tx (.*);
  always @(posedge clk) if (rst_n) begin
    if (link_valid && link_ready) receive_words++;
    if (source_valid && source_last && source_ready) complete_responses++;
  end

  task automatic send(input logic [15:0] data, input bit payload, last);
    rx_valid=1; rx_data=data; rx_is_payload=payload; rx_payload_last=last;
    do @(posedge clk); while (!rx_ready);
    @(negedge clk);
    rx_valid=0;
  endtask

  task automatic receive(input logic [15:0] data, input bit last);
    repeat (3) begin
      @(posedge clk);
      if ({tx_valid,tx_last,tx_data,source_ready} !== {1'b1,last,data,1'b0})
        $fatal(1,"HOST_CONTROL_RESPONSE_STALL data=%h last=%b",data,last);
      @(negedge clk);
    end
    tx_ready=1;
    @(posedge clk);
    if ({tx_valid,tx_last,tx_data,source_ready} !== {1'b1,last,data,last})
      $fatal(1,"HOST_CONTROL_RESPONSE_WORD data=%h last=%b",data,last);
    @(negedge clk);
    tx_ready=0;
  endtask

  initial begin
    logic [47:0] head_words;
    repeat(3) @(negedge clk);
    rst_n=1;
    fork
      send(16'hA674,0,1);
      begin
        repeat (3) begin
          @(posedge clk);
          if ({rx_ready,link_valid} !== 2'b00) $fatal(1,"HOST_CONTROL_CONFIG_WHILE_BUSY");
        end
        @(negedge clk);
        config_enable=1;
      end
    join
    for(int word=0;word<8;word++) begin
      if ({value_read_base,context_base} !== 128'd0 || angle_valid)
        $fatal(1,"HOST_CONTROL_CONFIG_NOT_ATOMIC");
      send(Bases[word*16+:16],0,0);
    end
    if ({value_read_base,context_base} !== Bases || receive_words != 0)
      $fatal(1,"HOST_CONTROL_BASES");
    send(16'h0102,0,0);
    send(16'hA674,0,1);
    send(16'h0004,0,0);
    if (receive_words != 3) $fatal(1,"HOST_CONTROL_LEGACY_RX");

    send(16'hA671,0,1);
    for(int word=0;word<64;word++) send(16'(17+word*71),0,0);
    if (!angle_valid || !angle_last) $fatal(1,"HOST_CONTROL_ROTARY_FLAGS");
    for(int word=0;word<64;word++)
      if (angle_data[word*16+:16] !== 16'(17+word*71)) $fatal(1,"HOST_CONTROL_ROTARY_DATA");
    angle_ready=1;
    @(negedge clk);
    angle_ready=0;

    source_valid=1; source_last=1; source_data=16'h000c;
    receive(16'h000c,1);
    source_data=16'h0004;
    receive(16'h0004,0);
    head_words={6'd0,head_values};
    for(int word=0;word<3;word++) receive(head_words[word*16+:16],word==2);
    for(int word=0;word<128;word++) result_values[word*16+:16]=16'(101+word*337);
    source_data=16'h0005;
    receive(16'h0005,0);
    for(int word=0;word<128;word++) receive(result_values[word*16+:16],word==127);
    source_valid=0;
    if (complete_responses!=3) $fatal(1,"HOST_CONTROL_RESPONSE_COUNT");

    send(16'hA674,0,1);
    repeat(4) send(16'hffff,0,0);
    if ({value_read_base,context_base} !== Bases) $fatal(1,"HOST_CONTROL_PARTIAL_OVERWRITE");
    rst_n=0;
    @(negedge clk);
    if ({value_read_base,context_base} !== 128'd0) $fatal(1,"HOST_CONTROL_RESET");
    $display("HOST_CONTROL_PASS legacy_words=3 rotary_words=64 head_words=3 attention_words=128");
    $finish;
  end
  initial begin
    #15000;
    $fatal(1,"HOST_CONTROL_TIMEOUT");
  end
endmodule
