`timescale 1ns/1ps
// Protocol peer deliberately corrupts one return slot. This checks ownership
// reset and recovery at the real sequencer boundary, not matrix arithmetic.
module tri_oracle_batched356_boundary_tb;
  logic clk=0;always #5 clk=~clk;
  logic rst_n=0,in_valid=0,in_accumulate=0,in_publish=0,out_ready=0,done_ready=0;
  logic [31:0] in_tag=0;
  logic [4:0] in_tokens=0,in_weight_base=0,in_mask_base=0;
  logic [5:0] in_strips=1;
  logic [9:0] in_activation_base=0;
  logic [10:0] in_activation_stride=1;
  wire in_ready,out_valid,out_last,done_valid,done_error,backend_rst_n;
  wire [31:0] out_tag,done_tag;
  wire [3:0] out_token;
  wire [5119:0] out_data;
  wire backend_cmd_valid,backend_cmd_accumulate;
  wire backend_cmd_ready=1;
  wire [4:0] backend_cmd_weight,backend_cmd_mask,backend_out_ready;
  wire [9:0] backend_cmd_activation;
  wire [3:0] backend_cmd_output;
  logic [4:0] backend_out_valid=0;
  logic [19:0] backend_out_output=0;
  logic [5119:0] backend_out_data={160{32'h11223344}};
  int resets=0;
  tri_oracle_batched_projection356 dut(.*);
  always @(negedge backend_rst_n)if(rst_n)resets++;
  task automatic configure(input int tokens,input bit publish,input int tag);
    @(negedge clk);while(!in_ready)@(negedge clk);
    in_valid=1;in_tokens=5'(tokens);in_publish=publish;in_tag=32'(tag);
    @(posedge clk);if(!in_ready)$fatal(1,"BATCH356_BOUNDARY_CONFIG");
    @(negedge clk);in_valid=0;in_tokens=0;in_tag='1;in_publish=0;
  endtask
  task automatic return_word(input int slot);
    do @(posedge clk);while(!backend_cmd_valid);
    @(negedge clk);backend_out_valid=31;backend_out_output={5{4'(slot)}};
  endtask
  task automatic acknowledge(input bit error,input int tag);
    wait(done_valid);@(negedge clk);
    if(done_error!==error || done_tag!==32'(tag))$fatal(1,"BATCH356_BOUNDARY_DONE");
    done_ready=1;@(posedge clk);@(negedge clk);done_ready=0;
  endtask
  initial begin
    repeat(3)@(negedge clk);rst_n=1;
    configure(1,0,1);return_word(0);
    do @(posedge clk);while(backend_out_ready!==31);
    @(negedge clk);backend_out_valid=0;acknowledge(0,1);
    if(resets!=0)$fatal(1,"BATCH356_SUCCESS_RESET_BACKEND");
    configure(17,0,2);acknowledge(1,2);
    if(resets!=1)$fatal(1,"BATCH356_INVALID_CONTINUATION_DID_NOT_FLUSH");
    in_accumulate=1;configure(1,0,1);in_accumulate=0;
    if(backend_cmd_valid)$fatal(1,"BATCH356_STALE_APPEND_ACCEPTED");
    acknowledge(1,1);
    if(resets!=2)$fatal(1,"BATCH356_STALE_APPEND_DID_NOT_FLUSH");
    configure(1,0,3);return_word(1);
    wait(!backend_rst_n);@(negedge clk);backend_out_valid=0;acknowledge(1,3);
    if(resets!=3)$fatal(1,"BATCH356_WRONG_SLOT_DID_NOT_FLUSH");
    configure(1,1,4);return_word(0);wait(out_valid);
    repeat(4)begin
      @(negedge clk);
      if(!out_valid || out_tag!==4 || out_token!==0 || out_last!==1 ||
         out_data!=={160{32'h11223344}} || backend_out_ready!==0)
        $fatal(1,"BATCH356_RECOVERED_OUTPUT_NOT_STABLE");
    end
    out_ready=1;@(posedge clk);@(negedge clk);out_ready=0;backend_out_valid=0;acknowledge(0,4);
    $display("BATCH356_BOUNDARY_PASS invalid_live_continuation=1 stale_append_rejected=1 wrong_result_slot=1 recovered_stalled_result=1 backend_flushes=3");$finish;
  end
  initial begin #20000;$fatal(1,"BATCH356_BOUNDARY_WATCHDOG");end
endmodule
