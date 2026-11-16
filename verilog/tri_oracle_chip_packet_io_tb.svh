`timescale 1ns/1ps

// The linker supplies the instance from the cold export's exact port list.
module tri_oracle_chip_packet_io_tb;
  bit clk = 0, rst_n = 0;
  always #5 clk = !clk;
  logic host_rx_valid = 0, host_rx_ready, host_rx_is_payload = 0, host_rx_payload_last = 0;
  logic [15:0] host_rx_data = '0;
  logic host_tx_valid, host_tx_ready = 0, host_tx_last, memory_tx_valid;
  logic [15:0] host_tx_data;
  int layer_issues, response_flits;

  // CHIP_INSTANCE

  always @(posedge clk) if (rst_n) begin
    if (memory_tx_valid) $fatal(1, "REJECTED_PACKET_ACCESSED_MEMORY");
    if (dut.accelerator.layer_command_valid[0] && dut.accelerator.layer_command_ready[0]) begin
      if (dut.accelerator.layer_command_tag !== 32'h43700001)
        $fatal(1, "MALFORMED_PACKET_REACHED_LAYER");
      layer_issues++;
    end
    if (host_tx_valid && host_tx_ready) response_flits++;
  end

  task automatic flit(input logic [15:0] value, input bit payload, final_payload);
    host_rx_valid = 1;
    host_rx_data = value;
    host_rx_is_payload = payload;
    host_rx_payload_last = final_payload;
    do @(posedge clk); while (!host_rx_ready);
    @(negedge clk);
    host_rx_valid = 0;
  endtask

  task automatic reject(input logic [31:0] tag, input int words);
    logic [47:0] expected;
    flit(tag[15:0], 0, 0);
    flit(tag[31:16], 0, 0);
    flit(16'd0, 0, 0);
    for (int word = 0; word < words; word++) begin
      flit(16'd0, 1, word == words - 1);
      for (int segment = 1; segment < 4; segment++) flit(16'd0, 0, 0);
    end

    expected = {12'd0, 1'b1, 3'd0, tag};
    while (!host_tx_valid) @(negedge clk);
    for (int index = 0; index < 3; index++) begin
      repeat (2) begin
        @(posedge clk);
        if ({host_tx_valid, host_tx_last, host_tx_data} !==
            {1'b1, index == 2, expected[index * 16 +: 16]})
          $fatal(1, "WRONG_COLD_HOST_RESPONSE tag=%h flit=%0d", tag, index);
        @(negedge clk);
      end
      host_tx_ready = 1;
      @(negedge clk);
      host_tx_ready = 0;
    end
  endtask

  initial begin
    repeat (8) @(negedge clk);
    rst_n = 1;
    repeat (8) @(negedge clk);
    reject(32'h43700000, 1);
    if (layer_issues != 0) $fatal(1, "DISPATCH_REJECTION_REACHED_FEEDFORWARD");
    reject(32'h43700001, 15);
    if (layer_issues != 1 || response_flits != 6 || host_tx_valid)
      $fatal(1, "COLD_PACKET_IO_INVENTORY");
    $display("COLD_PACKET_IO_PASS dispatcher_rejects=1 layer_rejects=1 response_flits=6");
    $finish;
  end

  initial begin
    #30000;
    $fatal(1, "COLD_PACKET_IO_TIMEOUT");
  end
endmodule
