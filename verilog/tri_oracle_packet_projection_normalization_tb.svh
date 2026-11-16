`timescale 1ns/1ps

module tri_oracle_packet_projection_normalization_tb;
  bit clk = 0, rst_n = 0;
  always #5 clk = !clk;
  logic cfg_valid = 0, cfg_ready, cfg_token = 0;
  logic [31:0] cfg_tag = '0;
  logic [31:0] cfg_epsilon_q16 = 32'd43980465;
  logic [5:0] cfg_shift = 6'd17;
  logic req_valid, req_ready, rsp_ready, rsp_valid, rsp_last, rsp_error;
  logic [63:0] req_address, rsp_data;
  logic [4:0] req_length;
  logic operand_ready, operand_token, operand_valid;
  logic [7:0] operand_strip;
  logic [279:0] residual_q32;
  logic [4:0] projection_shift;
  logic gamma_valid, gamma_ready;
  logic [7:0] gamma_strip;
  logic [127:0] gamma_data;
  logic out_valid, out_ready, out_last, out_error;
  logic [31:0] out_tag;
  logic [9:0] out_index;
  logic [3:0] out_count;
  logic [127:0] out_norm_q8;
  logic [7:0] out_outlier_mask;
  logic [63:0] out_activation;
  logic bank_ce_n, bank_we_n;
  logic [8:0] bank_addr;
  logic [255:0] bank_d, bank_q;
  logic read_valid = 0, read_ready, response_valid, response_ready = 0;
  logic [8:0] read_row;
  logic [231:0] response_data;
  logic rx_valid = 0, rx_ready, rx_is_payload = 0, rx_payload_last = 0;
  logic [15:0] rx_data = '0;
  logic forward_valid;
  logic [708:0] vectors[576];
  logic [255:0] normalization_inputs[512];
  string vectors_path, norm_path, dump;
  int file, cycles, rows, host_words, bank_readbacks;

  tri_oracle_native_reset_copy_0 dut (.*, .lease_granted(1'b1));
  tri_oracle_host_projection_rx port_rx (.*, .forward_ready(1'b1));
  projection_fixture_peer scoreboard (.*);
  for (genvar bank=0; bank<4; bank++) begin : banks
    TS5N28HPCPSVTA512X64M4F memory (
      .CLK(clk),.CEB(bank_ce_n),.WEB(bank_we_n),.A(bank_addr),.D(bank_d[64*bank+:64]),.Q(bank_q[64*bank+:64])
    );
  end
  assign out_ready = cycles % 17 < 5;
  always @(posedge clk) if (rst_n) begin
    cycles <= cycles + 1;
    if (forward_valid) $fatal(1, "NORMALIZATION_FORWARD_LEAK");
    if (rx_valid && rx_ready) host_words++;
    if (out_valid && out_ready) begin
      $fdisplay(file, "%054h", {out_index, out_count, out_last, out_error, out_norm_q8, out_outlier_mask, out_activation});
      rows++;
    end
  end

  task automatic flit(input logic [15:0] value, input bit header);
    rx_valid = 1;
    rx_payload_last = header;
    rx_data = value;
    do @(posedge clk); while (!rx_ready);
    @(negedge clk);
    rx_valid = 0;
  endtask

  initial begin
    if (!$value$plusargs("VECTORS=%s", vectors_path) || !$value$plusargs("NORM_INPUTS=%s", norm_path) ||
        !$value$plusargs("DUMP=%s", dump)) $fatal(1, "NORMALIZATION_PACKET_FIXTURE");
    $readmemh(vectors_path, vectors);
    $readmemh(norm_path, normalization_inputs);
    file = $fopen(dump, "w");
    if (!file) $fatal(1, "NORMALIZATION_PACKET_DUMP");
    repeat (8) @(negedge clk);
    rst_n = 1;
    repeat (4) @(negedge clk);
    for (int token=0; token<2; token++) begin
      cfg_valid = 1;
      cfg_token = 1'(token);
      cfg_tag = 32'hac001000 + 32'(token);
      do @(posedge clk); while (!cfg_ready);
      @(negedge clk);
      cfg_valid = 0;
      for (int strip=0; strip<256; strip++) begin
        logic [287:0] record_data;
        record_data = {3'd0, vectors[token*256+strip][348:344], vectors[token*256+strip][279:0]};
        flit(16'hA678, 1);
        for (int word=0; word<18; word++) flit(record_data[word*16+:16], 0);
      end
      for (int strip=0; strip<256; strip++) begin
        logic [127:0] record_data;
        record_data = normalization_inputs[token*256+strip][255:128];
        flit(16'hA679, 1);
        for (int word=0; word<8; word++) flit(record_data[word*16+:16], 0);
      end
      while (rows != (token+1)*256) @(negedge clk);
    end
    for (int row=0; row<512; row++) begin
      read_row = 9'(row);
      read_valid = 1;
      do @(posedge clk); while (!read_ready);
      @(negedge clk);
      read_valid = 0;
      while (!response_valid) @(negedge clk);
      if (response_data !== vectors[row][580:349]) $fatal(1,"NORMALIZATION_SAVED_BANK row=%0d",row);
      response_ready = 1;
      @(negedge clk);
      response_ready = 0;
      bank_readbacks++;
    end
    $fclose(file);
    if (scoreboard.inputs != 512 || scoreboard.outputs != 512 || scoreboard.gamma_count != 512 ||
        scoreboard.writes != 512 || scoreboard.packet_reads != 64 || scoreboard.bus_beats != 512 ||
        host_words != 14336 || bank_readbacks != 512)
      $fatal(1,"NORMALIZATION_PACKET_INVENTORY inputs=%0d gamma=%0d outputs=%0d",
             scoreboard.inputs, scoreboard.gamma_count, scoreboard.outputs);
    $display("PACKET_PROJECTION_NORMALIZATION_PASS operands=512 gamma=512 rows=512 bank_rows=512 host_words=14336 packets=64");
    $finish;
  end

  initial begin
    #800000;
    $fatal(1, "PACKET_PROJECTION_NORMALIZATION_TIMEOUT words=%0d operands=%0d gamma=%0d rows=%0d banks=%0d",
           host_words, scoreboard.inputs, scoreboard.gamma_count, rows, bank_readbacks);
  end
endmodule
