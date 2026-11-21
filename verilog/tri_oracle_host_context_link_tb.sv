`timescale 1ns/1ps
module tri_oracle_host_context_link_tb;
  logic clk=0,rst_n=0;
  always #5 clk=~clk;
  logic control_valid=0,control_finish=0;
  wire control_ready;
  logic context_valid=1,lease_active=1,metadata_needs_rebuild=1;
  logic [31:0] context_tag=32'h11223344;
  logic [10:0] context_query=37;
  logic signed [8:0] context_exponent=-9'sd8;
  wire finish_valid,done_ready;
  logic finish_ready=0,done_valid=0,done_error=0;
  logic source_valid=0,source_last=0,tx_ready=0;
  logic [15:0] source_data=0;
  wire source_ready,tx_valid,tx_last;
  wire [15:0] tx_data;
  bit expect_finish=0,block_source=0;
  int words=0,finish_handshakes=0,done_handshakes=0,accepted_controls=0;
  tri_oracle_host_context_link dut(.*);
  always @(posedge clk)if(rst_n)begin
    if(block_source && source_valid && source_ready)$fatal(1,"CONTEXT_HOST_SOURCE_SPLIT_BY_REPLY");
    if(finish_valid && !expect_finish)$fatal(1,"CONTEXT_HOST_UNEXPECTED_RELEASE");
    if(control_valid && control_ready)accepted_controls++;
    if(finish_valid && finish_ready)finish_handshakes++;
    if(done_ready && done_valid)done_handshakes++;
  end
  task automatic control(input bit close_frame);
    @(negedge clk);control_finish=close_frame;control_valid=1;
    @(posedge clk);if(!control_ready)$fatal(1,"CONTEXT_HOST_CONTROL_NOT_READY");
    @(negedge clk);control_valid=0;
  endtask
  task automatic word(input logic [15:0] want,input bit last);
    for(int n=0;n<20;n++)begin @(negedge clk);if(tx_valid)break;end
    repeat(3)begin
      @(posedge clk);
      if(!tx_valid || tx_data!==want || tx_last!==last)
        $fatal(1,"CONTEXT_HOST_WORD expected=%h actual=%h last=%b",want,tx_data,tx_last);
      @(negedge clk);
    end
    tx_ready=1;@(posedge clk);
    if(!tx_valid || tx_data!==want || tx_last!==last)$fatal(1,"CONTEXT_HOST_WORD_ACCEPT");
    @(negedge clk);tx_ready=0;words++;
  endtask
  task automatic packet(input logic [15:0] low_status,high_status,low_tag,high_tag,action);
    word(16'ha687,0);word(low_status,0);word(high_status,0);
    word(low_tag,0);word(high_tag,0);word(action,1);
  endtask
  task automatic reset_link;
    @(negedge clk);rst_n=0;control_valid=0;source_valid=0;
    finish_ready=0;done_valid=0;done_error=0;expect_finish=0;
    context_valid=0;lease_active=0;context_tag=0;context_query=0;context_exponent=0;
    repeat(2)begin
      @(posedge clk);
      if(tx_valid || finish_valid || done_ready || control_ready)$fatal(1,"CONTEXT_HOST_RESET_OUTPUTS");
      @(negedge clk);
    end
    rst_n=1;@(negedge clk);
    if(!control_ready || tx_valid || finish_valid || done_ready)$fatal(1,"CONTEXT_HOST_RESET_STALE_WORK");
  endtask
  initial begin
    repeat(3)@(negedge clk);rst_n=1;
    // A source packet stalled at its first word owns the output packet boundary.
    source_valid=1;source_data=16'ha111;
    @(posedge clk);@(negedge clk);
    control(0);
    context_tag=32'h55667788;context_query=280;context_exponent=-9'sd7;
    word(16'ha111,0);source_data=16'ha222;source_last=1;
    word(16'ha222,1);source_valid=0;source_last=0;
    source_valid=1;source_last=1;source_data=16'hc111;block_source=1;
    control_valid=1;control_finish=0; // Hold the next poll through the previous reply.
    packet(16'h4bf8,16'h0070,16'h3344,16'h1122,0);
    block_source=0;tx_ready=1;
    @(posedge clk);
    if(!control_ready || !source_ready || !tx_valid || !tx_last || tx_data!==16'hc111)
      $fatal(1,"CONTEXT_HOST_SIMULTANEOUS_LAST_CONTROL");
    words++;
    @(negedge clk);tx_ready=0;source_valid=0;source_last=0;
    if(control_ready || !tx_valid || tx_data!==16'ha687)
      $fatal(1,"CONTEXT_HOST_SIMULTANEOUS_CONTROL_NOT_QUEUED");
    repeat(2)@(negedge clk);control_valid=0;
    packet(16'h31f9,16'h0072,16'h7788,16'h5566,0);
    // Waiting for real memory release cannot block the final projection reply.
    expect_finish=1;control(1);
    source_valid=1;source_last=1;source_data=16'hb111;
    word(16'hb111,1);source_valid=0;source_last=0;
    repeat(3)begin
      @(posedge clk);
      if(!finish_valid || done_ready || tx_valid || control_ready)$fatal(1,"CONTEXT_HOST_FINISH_NOT_HELD");
      @(negedge clk);
    end
    finish_ready=1;@(posedge clk);if(!finish_valid)$fatal(1,"CONTEXT_HOST_FINISH_HANDSHAKE");
    @(negedge clk);finish_ready=0;expect_finish=0;context_valid=0;lease_active=0;
    repeat(3)begin
      @(posedge clk);if(finish_valid || tx_valid || !done_ready)$fatal(1,"CONTEXT_HOST_DONE_NOT_WAITED");
      @(negedge clk);
    end
    done_valid=1;@(posedge clk);if(!done_ready)$fatal(1,"CONTEXT_HOST_DONE_NOT_ACCEPTED");
    @(negedge clk);done_valid=0;
    packet(16'h31f9,16'h04c2,16'h7788,16'h5566,1);
    // An already-pending failed context completion must be reported and consumed.
    done_valid=1;done_error=1;control(1);
    @(posedge clk);if(!done_ready || finish_valid)$fatal(1,"CONTEXT_HOST_PENDING_ERROR");
    @(negedge clk);done_valid=0;done_error=0;
    packet(16'h31f9,16'h05c2,16'h7788,16'h5566,1);
    // A context failure racing a stalled finish must not issue a release afterward.
    context_valid=1;lease_active=1;expect_finish=1;control(1);
    @(negedge clk);context_valid=0;lease_active=0;done_valid=1;done_error=1;
    @(posedge clk);@(negedge clk);
    if(finish_valid || !done_ready)$fatal(1,"CONTEXT_HOST_RACING_ERROR");
    @(posedge clk);@(negedge clk);done_valid=0;done_error=0;expect_finish=0;
    packet(16'h31f9,16'h05c2,16'h7788,16'h5566,1);
    control(1);packet(16'h31f9,16'h0642,16'h7788,16'h5566,1);
    context_tag=0;context_query=0;context_exponent=0;
    control(0);packet(0,16'h0040,0,0,0);
    // Reset cancels requests before release, while awaiting completion and in reply.
    context_valid=1;lease_active=1;expect_finish=1;control(1);reset_link();
    context_valid=1;lease_active=1;expect_finish=1;control(1);
    finish_ready=1;@(posedge clk);@(negedge clk);finish_ready=0;expect_finish=0;reset_link();
    control(0);reset_link();
    if(words!=46 || finish_handshakes!=2 || done_handshakes!=3 || accepted_controls!=10)
      $fatal(1,"CONTEXT_HOST_INVENTORY words=%0d finish=%0d done=%0d",words,finish_handshakes,done_handshakes);
    $display("CONTEXT_HOST_LINK_PASS reply_packets=7 forwarded_words=4 checked_words=46 reset_phases=3 finish_handshakes=2 done_handshakes=3 accepted_controls=10");
    $finish;
  end
  initial begin #100000;$fatal(1,"CONTEXT_HOST_TIMEOUT");end
endmodule
