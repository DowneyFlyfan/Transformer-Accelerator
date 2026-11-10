`timescale 1ns/1ps
module tri_oracle_causal_token_size_boundary_tb;
  logic clk=0;
  always #5 clk=~clk;
  logic rst_n=0,frame_valid=0,map_valid=0,map_last=0;
  logic query_valid=0,out_ready=0;
  logic [1:0] map_origin=0,query_position=0;
  wire frame_ready,map_ready,query_ready,out_valid,out_last,error;
  wire [1:0] out_origin;
  wire [2:0] out_count;
  tri_oracle_causal_token_size #(.MAX_TOKENS(4)) dut(.*);
  task automatic begin_frame;
    @(negedge clk);frame_valid=1;
    do @(posedge clk);while(!frame_ready);
    @(negedge clk);frame_valid=0;
  endtask
  task automatic map_word(input int origin,input bit last_word);
    @(negedge clk);map_valid=1;map_origin=2'(origin);map_last=last_word;
    do @(posedge clk);while(!map_ready);
    @(negedge clk);map_valid=0;map_last=0;
  endtask
  task automatic check_singleton;
    @(negedge clk);query_valid=1;query_position=0;
    do @(posedge clk);while(!query_ready);
    @(negedge clk);query_valid=0;out_ready=1;
    do @(posedge clk);while(!out_valid);
    if(out_origin!==0 || out_count!==1 || out_last!==1 || error)
      $fatal(1,"CAUSAL_BOUNDARY_RECOVERY_WORD");
    @(negedge clk);out_ready=0;
  endtask
  initial begin
    repeat(2) @(negedge clk);rst_n=1;
    begin_frame();
    for(int i=0;i<4;i++) map_word(i,0);
    if(!error || map_ready || query_ready || out_valid || !frame_ready)
      $fatal(1,"CAUSAL_MISSING_LAST_NOT_REJECTED");
    begin_frame();map_word(0,1);check_singleton();
    begin_frame();map_word(0,0);map_word(0,0);
    @(negedge clk);rst_n=0;
    @(negedge clk);rst_n=1;
    if(!frame_ready || map_ready || query_ready || out_valid || error)
      $fatal(1,"CAUSAL_PARTIAL_LOAD_RESET_LEAK");
    begin_frame();map_word(0,1);check_singleton();
    // New-frame configuration and a query offered together have one winner.
    @(negedge clk);frame_valid=1;query_valid=1;
    #1;
    if(!frame_ready || query_ready) $fatal(1,"CAUSAL_FRAME_QUERY_DOUBLE_ACCEPT");
    @(posedge clk);
    @(negedge clk);frame_valid=0;query_valid=0;
    if(!map_ready || query_ready || out_valid) $fatal(1,"CAUSAL_NEW_FRAME_NOT_SELECTED");
    map_word(0,1);check_singleton();
    $display("CAUSAL_BOUNDARY_PASS missing_last=1 reset_partial_load=1 exclusive_frame_query=1 recovery_rows=3");
    $finish;
  end
  initial begin #20000;$fatal(1,"CAUSAL_BOUNDARY_WATCHDOG");end
endmodule
