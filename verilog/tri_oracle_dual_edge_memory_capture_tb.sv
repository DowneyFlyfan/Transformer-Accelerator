`timescale 1ns/1ps

module tri_oracle_dual_edge_memory_capture_tb;
  logic clk=0,rst_n=0;
  always #5 clk=~clk;
  logic [447:0] pad_data;
  logic [1:0] pad_valid,pad_ready,pad_last,pad_error,pad_compact;
  logic [5:0] pad_words;
  logic [1:0] out_valid,out_ready,out_last,out_error,out_compact;
  logic [5:0] out_words;
  logic [895:0] out_data;
  int sent0=0,sent1=0,received[2]='{default:0};
  int cycle=0, overlap=0, stalled_edges[2]='{default:0};
  bit run_full=0, force_stall=0;
  wire [447:0] offered0=payload(0,sent0,run_full),offered1=payload(1,sent1,run_full);

  tri_oracle_dual_edge_memory_capture dut (.*);

  function automatic logic [447:0] payload(input int lane, ordinal,input bit phase);
    for (int word=0;word<7;word++)
      payload[64*word+:64]=64'hfe2038311ad03498 ^
        (64'(ordinal)<<(2*word)) ^ (64'(lane)<<21) ^
        (64'(phase)<<39) ^ (64'(word)<<54);
  endfunction

  function automatic logic [5:0] metadata(input int lane,ordinal);
    return {3'((ordinal+lane)%8),(ordinal%3==0),(ordinal%5==1),(ordinal%7==2)};
  endfunction

  // The peer changes the shared pins after each sampling edge. Falling
  // edges see lane 1; rising edges see lane 0.
  assign #2 pad_data=clk ? offered1 : offered0;
  assign pad_valid={sent1<(run_full?101:25),sent0<(run_full?128:25)};
  assign {pad_words[2:0],pad_compact[0],pad_last[0],pad_error[0]}=metadata(0,sent0);
  assign {pad_words[5:3],pad_compact[1],pad_last[1],pad_error[1]}=metadata(1,sent1);
  assign out_ready=force_stall?2'b0:
     ((cycle<16)?2'b11:{cycle%11>=6,cycle%7>=3});

  always @(posedge clk or negedge rst_n)
    if (!rst_n) sent0<=0;
    else if (pad_valid[0] && pad_ready[0]) sent0<=sent0+1;
  always @(negedge clk or negedge rst_n)
    if (!rst_n) sent1<=0;
    else if (pad_valid[1] && pad_ready[1]) sent1<=sent1+1;

  always @(posedge clk) begin
    if (!rst_n) begin
      received='{default:0};
      stalled_edges='{default:0};
      cycle<=0;
      overlap=0;
    end else begin
      logic [1:0] taken;
      taken=out_valid & out_ready;
      for (int lane=0;lane<2;lane++) begin
        if (out_valid[lane]) begin
          if ({out_words[3*lane+:3],out_compact[lane],out_last[lane],out_error[lane]}!==
              metadata(lane,received[lane]) || out_data[448*lane+:448]!==payload(lane,received[lane],run_full))
            $fatal(1,"DDR_CAPTURE_DATA lane=%0d beat=%0d",lane,received[lane]);
          if (taken[lane]) received[lane]++;
          else stalled_edges[lane]++;
        end
      end
      if (taken==2'b11) overlap++;
      cycle<=cycle+1;
    end
  end

  initial begin
    repeat (3) @(negedge clk);
    #1 rst_n=1;
    repeat (8) @(negedge clk);
    #1 force_stall=1;
    repeat (5) @(negedge clk);
    #1;
    if (out_valid!==2'b11) $fatal(1,"DDR_CAPTURE_RESET_COVERAGE");
    rst_n=0;
    repeat (3) @(negedge clk);
    #1;
    if (out_valid!==2'b00 || pad_ready!==2'b00) $fatal(1,"DDR_CAPTURE_RESET_LEAK");
    run_full=1;
    force_stall=0;
    rst_n=1;
    wait(received[0]==128 && received[1]==101);
    repeat (5) @(negedge clk);
    if (sent0!=128 || sent1!=101 || out_valid!==0 ||
        overlap<16 || stalled_edges[0]==0 || stalled_edges[1]==0)
      $fatal(1,"DDR_CAPTURE_COUNTS rise=%0d fall=%0d overlap=%0d",received[0],received[1],overlap);
    $display("DUAL_EDGE_CAPTURE_PASS rise=128 fall=101 overlap=%0d stalls=%0d,%0d",overlap,stalled_edges[0],stalled_edges[1]);
    $finish;
  end
  initial begin
    repeat (600) @(negedge clk);
    $fatal(1,"DDR_CAPTURE_TIMEOUT rise=%0d fall=%0d",received[0],received[1]);
  end
endmodule
