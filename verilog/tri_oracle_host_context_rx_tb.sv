`timescale 1ns/1ps
module tri_oracle_host_context_rx_tb;
  logic clk=0,rst_n=0;
  always #5 clk=~clk;
  logic rx_valid=0,rx_is_payload=0,rx_payload_last=0;
  logic [15:0] rx_data=0;
  wire rx_ready,forward_valid;
  logic forward_ready=0;
  wire control_valid;
  logic control_ready=0;
  wire [1:0] control_action;
  wire context_control_valid,context_control_finish;
  logic context_control_ready=0;
  wire operand_valid,gamma_valid,stats_valid,stats_last,replay_valid,replay_last;
  logic operand_ready=0,gamma_ready=0,stats_ready=0,replay_ready=0;
  wire [279:0] residual_q32;
  wire [4:0] projection_shift;
  wire [127:0] gamma_data,stats_data,replay_data,replay_gamma;
  int context_requests=0,legacy_requests=0,forwarded=0,statistics=0;
  tri_oracle_host_context_rx dut(.*);
  always @(posedge clk)if(rst_n)begin
    if(context_control_valid && context_control_ready)context_requests++;
    if(control_valid && control_ready)legacy_requests++;
    if(forward_valid && forward_ready)forwarded++;
    if(stats_valid && stats_ready)statistics++;
  end
  task automatic header(input logic [15:0] value,input bit context_request,input logic [1:0] action);
    @(negedge clk);rx_valid=1;rx_data=value;rx_is_payload=0;rx_payload_last=1;
    repeat(3)begin
      @(posedge clk);
      if(rx_ready || forward_valid || operand_valid || stats_valid || replay_valid || gamma_valid ||
         context_control_valid!==context_request || control_valid===context_request ||
         (context_request ? context_control_finish!==action[0] : control_action!==action))
        $fatal(1,"CONTEXT_RX_HEADER_ROUTING word=%h",value);
      @(negedge clk);
    end
    if(context_request)context_control_ready=1;else control_ready=1;
    @(posedge clk);if(!rx_ready)$fatal(1,"CONTEXT_RX_HEADER_BACKPRESSURE");
    @(negedge clk);rx_valid=0;control_ready=0;context_control_ready=0;
  endtask
  task automatic forwarded_word(input logic [15:0] value,input bit payload,last);
    @(negedge clk);rx_valid=1;rx_data=value;rx_is_payload=payload;rx_payload_last=last;
    repeat(2)begin
      @(posedge clk);
      if(!forward_valid || rx_ready || control_valid || context_control_valid)
        $fatal(1,"CONTEXT_RX_RECORD_FORWARDING word=%h",value);
      @(negedge clk);
    end
    forward_ready=1;@(posedge clk);if(!rx_ready || !forward_valid)$fatal(1,"CONTEXT_RX_FORWARD_ACCEPT");
    @(negedge clk);forward_ready=0;rx_valid=0;
  endtask
  task automatic local_word(input logic [15:0] value,input bit auxiliary);
    @(negedge clk);rx_valid=1;rx_data=value;rx_is_payload=0;rx_payload_last=auxiliary;
    @(posedge clk);
    if(!rx_ready || forward_valid || context_control_valid || control_valid)$fatal(1,"CONTEXT_RX_LOCAL_BODY_INTERCEPTED");
    @(negedge clk);rx_valid=0;
  endtask
  initial begin
    repeat(3)@(negedge clk);rst_n=1;
    header(16'ha685,1,0);header(16'ha686,1,1);
    header(16'ha67e,0,0);header(16'ha682,0,1);header(16'ha683,0,2);
    // Header-like words with auxiliary flags are still body data inside a record.
    forwarded_word(16'h1234,0,0);forwarded_word(16'ha685,0,1);forwarded_word(16'ha686,0,1);
    forwarded_word(16'h1111,1,0);forwarded_word(16'ha685,0,1);
    forwarded_word(16'h2222,0,0);forwarded_word(16'ha686,0,1);
    header(16'ha685,1,0);
    // At RecordStart, both marker values with any non-auxiliary flags are data.
    for(int h=0;h<2;h++)begin
      for(int flags=0;flags<3;flags++)begin
        forwarded_word(h==0 ? 16'ha685 : 16'ha686,flags!=0,flags==2);
        for(int body=0;body<(flags==0 ? 2 : 3);body++)
          forwarded_word(16'h1200+16'(body),0,0);
      end
    end
    // Preserve the existing eight-word statistics format and held publish state.
    local_word(16'ha67b,1);
    local_word(1,0);local_word(2,0);local_word(3,0);local_word(4,0);
    local_word(16'ha685,1);local_word(6,0);local_word(16'ha686,1);local_word(8,0);
    repeat(3)begin
      @(posedge clk);
      if(!stats_valid || !stats_last || stats_data!==128'h0008a6860006a6850004000300020001 ||
         forward_valid || context_control_valid || control_valid || rx_ready)
        $fatal(1,"CONTEXT_RX_LEGACY_STATISTICS");
      @(negedge clk);
    end
    stats_ready=1;@(posedge clk);@(negedge clk);stats_ready=0;
    // Reset cancels a stalled context header and an incomplete forwarded record.
    rx_valid=1;rx_data=16'ha686;rx_is_payload=0;rx_payload_last=1;
    @(posedge clk);@(negedge clk);rst_n=0;
    @(posedge clk);if(rx_ready || context_control_valid || control_valid || forward_valid)$fatal(1,"CONTEXT_RX_RESET_HEADER");
    @(negedge clk);rx_valid=0;rst_n=1;
    forwarded_word(16'h9876,0,0);
    rst_n=0;@(posedge clk);@(negedge clk);rst_n=1;
    header(16'ha686,1,1);
    if(context_requests!=4 || legacy_requests!=3 || forwarded!=30 || statistics!=1)
      $fatal(1,"CONTEXT_RX_INVENTORY context=%0d legacy=%0d forward=%0d stats=%0d",context_requests,legacy_requests,forwarded,statistics);
    $display("CONTEXT_HOST_RECEIVER_PASS context_requests=4 legacy_requests=3 forwarded_words=30 statistics_frames=1 reset_phases=2");
    $finish;
  end
  initial begin #100000;$fatal(1,"CONTEXT_RX_TIMEOUT");end
endmodule
