`timescale 1ns/1ps
`ifndef TRI_ORACLE_CREDIT_TEST_DELAY
`define TRI_ORACLE_CREDIT_TEST_DELAY 4
`endif

module tri_oracle_credit_memory_ingress_tb;
  localparam int Credits = 8;
  localparam int ReturnCycles = `TRI_ORACLE_CREDIT_TEST_DELAY;
  bit clk=0,rst_n=0,stress=0,warmup=1;
  always #5 clk=~clk;

  logic [447:0] pad_data;
  logic [1:0] pad_valid,pad_last,pad_credit,protocol_error;
  wire [1:0] pad_error=0,pad_compact=0;
  wire [5:0] pad_words={3'd7,3'd7};
  logic [1:0] out_valid,out_last,out_error,out_ready;
  logic [1023:0] out_data;
  int sent[2]='{default:0},received[2]='{default:0},available[2]='{default:Credits};
  int cycle=0,credit_stalls[2]='{default:0};
  bit [ReturnCycles-1:0] returns[2]='{default:0};
  wire [447:0] rising_offer=chunk(0,sent[0],stress||warmup);
  wire [447:0] falling_offer=chunk(1,sent[1],stress||warmup);

  tri_oracle_credit_memory_ingress dut (.*);

  function automatic logic [63:0] expected_word(input int lane,offset,input bit phase);
    return 64'h643c192fd03578b1 ^ (64'(phase)<<54) ^ (64'(lane)<<50) ^ (64'(offset)<<20);
  endfunction

  function automatic logic [447:0] chunk(input int lane,ordinal,input bit phase);
    for (int word=0;word<7;word++) chunk[64*word+:64]=expected_word(lane,7*ordinal+word,phase);
  endfunction

  // Alternate host beats on the shared pins. Return credits reach the
  // peer after a separate delay on each lane's own sampling edge.
  assign #2 pad_data=clk?falling_offer:rising_offer;
  assign out_ready=warmup?2'b00:stress ?
    {cycle>=71 && cycle%13>=3,cycle>=44 && cycle%19>=5}:2'b11;

  for (genvar lane=0;lane<2;lane++) begin: peer
    wire peer_clock=lane==0?clk:!clk;
    assign pad_valid[lane]=rst_n && sent[lane]<64 && available[lane]!=0;
    assign pad_last[lane]=sent[lane]==63;
    always @(posedge peer_clock or negedge rst_n) begin
      if (!rst_n) begin
        sent[lane]<=0;
        available[lane]<=Credits;
        returns[lane]<='0;
        credit_stalls[lane]<=0;
      end else begin
        int updated;
        updated=available[lane]+int'(returns[lane][ReturnCycles-1])-int'(pad_valid[lane]);
        if (updated<0 || updated>Credits)
          $fatal(1,"CREDIT_CONSERVATION lane=%0d credits=%0d",lane,updated);
        available[lane]<=updated;
        returns[lane]<={returns[lane][ReturnCycles-2:0],pad_credit[lane]};
        if (pad_valid[lane]) sent[lane]<=sent[lane]+1;
        if (sent[lane]<64 && !pad_valid[lane]) begin
          credit_stalls[lane]<=credit_stalls[lane]+1;
          if (ReturnCycles==4 && !stress && !warmup)
            $fatal(1,"CREDIT_UNSTALLED_BURST_BUBBLE lane=%0d beat=%0d",lane,sent[lane]);
        end
      end
    end
  end

  always @(posedge clk) begin
    if (!rst_n) begin
      received='{default:0};
      cycle<=0;
    end else begin
      if (protocol_error!==0) $fatal(1,"CREDIT_RECEIVER_OVERFLOW");
      for (int lane=0;lane<2;lane++) if (out_valid[lane]) begin
        if (received[lane]>=56 || out_last[lane]!==(received[lane]==55) || out_error[lane])
          $fatal(1,"CREDIT_RESPONSE_METADATA lane=%0d beat=%0d",lane,received[lane]);
        for (int word=0;word<8;word++)
          if (out_data[512*lane+64*word+:64]!==expected_word(lane,8*received[lane]+word,stress||warmup))
            $fatal(1,"CREDIT_RESPONSE_DATA lane=%0d beat=%0d word=%0d",lane,received[lane],word);
        if (out_ready[lane]) received[lane]++;
      end
      cycle<=cycle+1;
    end
  end

  task automatic drained;
    wait(received[0]==56 && received[1]==56 && available[0]==Credits && available[1]==Credits);
    repeat (ReturnCycles+2) @(negedge clk);
    if (sent[0]!=64 || sent[1]!=64 || out_valid!==0 || pad_credit!==0)
      $fatal(1,"CREDIT_DRAIN_COUNTS");
  endtask

  initial begin
    repeat (3) @(negedge clk);
    #1 rst_n=1;
    repeat (10) @(negedge clk);
    #1;
    if (sent[0]==0 || sent[1]==0 || received[0]!=0 || received[1]!=0)
      $fatal(1,"CREDIT_RESET_IN_FLIGHT_COVERAGE");
    rst_n=0;
    repeat (4) @(negedge clk);
    #1;
    if (pad_credit!==0 || out_valid!==0 || available[0]!=Credits || available[1]!=Credits)
      $fatal(1,"CREDIT_RESET_IN_FLIGHT_LEAK");
    warmup=0;
    rst_n=1;
    drained();
    if (ReturnCycles==4)
      $display("CREDIT_FULL_RATE_PASS chunks=64,64 responses=56,56 delay=4");
    else begin
      if (credit_stalls[0]==0 || credit_stalls[1]==0)
        $fatal(1,"CREDIT_DELAY_WINDOW_COVERAGE");
      $display("CREDIT_DELAY_WINDOW_PASS chunks=64,64 responses=56,56 delay=%0d credit_stalls=%0d,%0d",
               ReturnCycles,credit_stalls[0],credit_stalls[1]);
    end
    #1 rst_n=0;
    repeat (4) @(negedge clk);
    #1 stress=1;
    rst_n=1;
    drained();
    if (credit_stalls[0]<36 || credit_stalls[1]<63)
      $fatal(1,"CREDIT_STALL_COVERAGE %0d,%0d",credit_stalls[0],credit_stalls[1]);
    $display("CREDIT_STALL_PASS chunks=64,64 responses=56,56 credit_stalls=%0d,%0d",
             credit_stalls[0],credit_stalls[1]);
    $finish;
  end
  initial begin
    repeat (500) @(negedge clk);
    $fatal(1,"CREDIT_MEMORY_TIMEOUT received=%0d,%0d available=%0d,%0d",
           received[0],received[1],available[0],available[1]);
  end
endmodule
