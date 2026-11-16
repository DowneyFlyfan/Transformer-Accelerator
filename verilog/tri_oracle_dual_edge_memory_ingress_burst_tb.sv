`timescale 1ns/1ps

module tri_oracle_dual_edge_memory_ingress_burst_tb;
  bit clk=0,rst_n=0;
  always #5 clk=~clk;
  logic [447:0] pad_data;
  logic [1:0] pad_valid,pad_last,pad_ready;
  wire [1:0] pad_error=0,pad_compact=0,out_ready=2'b11;
  wire [5:0] pad_words={3'd7,3'd7};
  logic [1:0] out_valid,out_last,out_error;
  logic [1023:0] out_data;
  int rising_sent=0,falling_sent=0,received[2]='{default:0},cycle=0;
  int first_cycle=-1,last_cycle=-1,simultaneous=0;
  wire [447:0] rising_chunk=packet(0,rising_sent),falling_chunk=packet(1,falling_sent);

  tri_oracle_dual_edge_memory_ingress dut (.*);

  function automatic logic [63:0] reference_word(input int lane,ordinal);
    return 64'h925751c929019791 ^ (64'(lane)<<44) ^ (64'(ordinal)<<17);
  endfunction

  function automatic logic [447:0] packet(input int lane,number);
    for (int word=0;word<7;word++) packet[64*word+:64]=reference_word(lane,7*number+word);
  endfunction

  assign #2 pad_data=clk?falling_chunk:rising_chunk;
  assign pad_valid={falling_sent<64,rising_sent<64};
  assign pad_last={falling_sent==63,rising_sent==63};

  always @(negedge clk) if (rst_n && pad_valid[1]) begin
    if (!pad_ready[1]) $fatal(1,"DDR_BURST_FALLING_INPUT_BUBBLE");
    falling_sent<=falling_sent+1;
  end

  always @(posedge clk) if (rst_n) begin
    if (pad_valid[0]) begin
      if (!pad_ready[0]) $fatal(1,"DDR_BURST_RISING_INPUT_BUBBLE");
      rising_sent<=rising_sent+1;
    end
    if (|out_valid) begin
      if (first_cycle<0) first_cycle=cycle;
      last_cycle=cycle;
    end
    if (out_valid==2'b11) simultaneous++;
    for (int lane=0;lane<2;lane++) if (out_valid[lane]) begin
      if (received[lane]>=56 || out_last[lane]!==(received[lane]==55) || out_error[lane])
        $fatal(1,"DDR_BURST_RESPONSE_METADATA lane=%0d beat=%0d",lane,received[lane]);
      for (int word=0;word<8;word++)
        if (out_data[512*lane+64*word+:64]!==reference_word(lane,8*received[lane]+word))
          $fatal(1,"DDR_BURST_DATA lane=%0d beat=%0d word=%0d",lane,received[lane],word);
      received[lane]++;
    end
    cycle<=cycle+1;
  end

  initial begin
    repeat (3) @(negedge clk);
    #1 rst_n=1;
    wait(received[0]==56 && received[1]==56);
    repeat (3) @(negedge clk);
    if (rising_sent!=64 || falling_sent!=64 || simultaneous<48 ||
        last_cycle-first_cycle+1>65 || out_valid!==0)
      $fatal(1,"DDR_BURST_COUNTS rise=%0d fall=%0d overlap=%0d",rising_sent,falling_sent,simultaneous);
    $display("DUAL_EDGE_INGRESS_BURST_PASS rising_chunks=64 falling_chunks=64 beats_per_lane=56 overlap=%0d delivery_cycles=%0d",
             simultaneous,last_cycle-first_cycle+1);
    $finish;
  end

  initial begin
    repeat (120) @(negedge clk);
    $fatal(1,"DDR_BURST_TIMEOUT rise=%0d fall=%0d",received[0],received[1]);
  end
endmodule
