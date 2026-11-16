`timescale 1ns/1ps

module tri_oracle_host_projection_rx_tb;
  bit clk = 0, rst_n = 0;
  always #5 clk = !clk;
  logic rx_valid = 0, rx_ready, rx_is_payload = 0, rx_payload_last = 0;
  logic [15:0] rx_data = '0;
  logic forward_valid, forward_ready = 1;
  logic operand_valid, operand_ready = 0, gamma_valid, gamma_ready = 0;
  logic [279:0] residual_q32;
  logic [4:0] projection_shift;
  logic [127:0] gamma_data;
  int forwarded, operands, gammas;
  localparam logic [287:0] Operand = {3'b000, 5'd21, 280'H71234EFAB1234DEADBA98776550FFDDAABBCCEEDD112233445566778899AABBCCDDEEFF};
  localparam logic [127:0] Gamma = 128'hABCDEF12345678909876543210FEDCBA;

  tri_oracle_host_projection_rx dut (.*);
  always @(posedge clk) if (rst_n) begin
    if (forward_valid && forward_ready) forwarded++;
    if (operand_valid && operand_ready) operands++;
    if (gamma_valid && gamma_ready) gammas++;
  end

  task automatic send(input logic [15:0] word, input bit payload, last, forward_word);
    rx_valid = 1;
    rx_data = word;
    rx_is_payload = payload;
    rx_payload_last = last;
    do @(posedge clk); while (!rx_ready);
    if (forward_valid !== forward_word) $fatal(1, "PROJECTION_RX_MISROUTED_WORD %h", word);
    @(negedge clk);
    rx_valid = 0;
  endtask

  initial begin
    repeat (3) @(negedge clk);
    rst_n = 1;
    send(16'h1234, 0, 0, 1);
    send(16'hA678, 0, 1, 1);
    send(16'h0000, 0, 0, 1);
    send(16'haaaa, 1, 1, 1);
    repeat (3) send(16'hA679, 0, 1, 1);
    send(16'hA674, 0, 1, 1);
    repeat (8) send(16'hA678, 0, 1, 1);
    send(16'hA670, 0, 1, 1);
    repeat (64) send(16'hA679, 0, 1, 1);

    send(16'hA678, 0, 1, 0);
    for (int word = 0; word < 18; word++) begin
      if (operand_valid || gamma_valid) $fatal(1, "PROJECTION_RX_EARLY_OPERAND");
      send(Operand[word*16+:16], 0, 0, 0);
    end
    repeat (4) begin
      if ({operand_valid,gamma_valid,projection_shift,residual_q32} !== {2'b10,Operand[284:0]} || rx_ready)
        $fatal(1,"PROJECTION_RX_STALLED_OPERAND");
      @(negedge clk);
    end
    operand_ready = 1;
    @(negedge clk);
    operand_ready = 0;
    send(16'hA679, 0, 1, 0);
    for (int word = 0; word < 8; word++) send(Gamma[word*16+:16], 0, 0, 0);
    repeat (4) begin
      if ({operand_valid,gamma_valid,gamma_data} !== {2'b01,Gamma} || rx_ready)
        $fatal(1,"PROJECTION_RX_STALLED_GAMMA");
      @(negedge clk);
    end
    gamma_ready = 1;
    @(negedge clk);
    gamma_ready = 0;
    send(16'hA678, 0, 1, 0);
    repeat (3) send(16'hffff, 0, 0, 0);
    rst_n = 0;
    @(negedge clk);
    if (operand_valid || gamma_valid || rx_ready || forward_valid) $fatal(1,"PROJECTION_RX_RESET");
    rst_n = 1;
    send(16'h5678, 0, 0, 1);
    send(16'h9012, 0, 0, 1);
    send(16'h0004, 0, 0, 1);
    if (forwarded != 84 || operands != 1 || gammas != 1)
      $fatal(1,"PROJECTION_RX_COUNTS forward=%0d operands=%0d gamma=%0d", forwarded, operands, gammas);
    $display("PROJECTION_RX_PASS forwarded=84 operands=1 gamma=1");
    $finish;
  end

  initial begin
    #10000;
    $fatal(1,"PROJECTION_RX_TIMEOUT");
  end
endmodule
