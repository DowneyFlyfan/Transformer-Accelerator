`timescale 1ns/1ps
module tri_oracle_attention_context_commit_tb;
 logic clk=0,rst_n=0,cfg_valid=0,cfg_ready,cancel=0;
 logic [31:0] cfg_heads='1,cfg_tag=32'h125671ab;
 logic [15:0] cfg_query=280,cfg_epoch=16'ha791;
 logic broker_cfg_valid,broker_cfg_ready=1,collector_cfg_valid,collector_cfg_ready=1;
 logic broker_row_offer=0,broker_row_valid,broker_row_ready,broker_all_collected=1;
 logic [4:0] broker_row_head=0;
 logic [15:0] broker_row_query=280,broker_row_epoch=16'ha791;
 logic [31:0] broker_row_tag=32'h125671ab;
 logic collector_row_valid,collector_row_ready=0;
 logic broker_done_valid=0,broker_done_ready,broker_done_error=0,broker_reset_required=0,broker_cancel;
 logic collector_context_valid=0,collector_done_valid=0,collector_done_ready,collector_done_error=0,collector_rst_n;
 logic projection_idle=1,frame_valid,context_route_enable;
 logic finish_valid=0,finish_ready,collector_finish_valid,collector_finish_ready=1;
 logic done_valid,done_ready=0,done_error,reset_required,busy;
 logic [7:0] error_code;
 int configured=0,rows=0,collector_resets=0,positive_frames=0;
 always_comb broker_row_valid=broker_row_offer && !broker_cancel;
 always #5 clk=~clk;
 tri_oracle_attention_context_commit dut(.*);
 always @(posedge clk)if(rst_n)begin
  if(broker_cfg_valid!=collector_cfg_valid)$fatal(1,"COMMIT_PARTIAL_CONFIGURATION");
  if(broker_cfg_valid)configured++;
  if(collector_row_valid && collector_row_ready)rows++;
 end
 always @(negedge collector_rst_n)if(rst_n)collector_resets++;
 task automatic reset_all;
  @(negedge clk);rst_n=0;cfg_valid=0;cancel=0;broker_row_offer=0;collector_row_ready=0;
  broker_done_valid=0;broker_done_error=0;broker_reset_required=0;collector_context_valid=0;
  collector_done_valid=0;collector_done_error=0;projection_idle=1;finish_valid=0;done_ready=0;
  broker_cfg_ready=1;collector_cfg_ready=1;cfg_heads='1;cfg_query=280;cfg_epoch=16'ha791;cfg_tag=32'h125671ab;
  broker_row_query=280;broker_row_epoch=16'ha791;broker_row_tag=32'h125671ab;broker_all_collected=1;
  repeat(2)@(negedge clk);rst_n=1;#1;
  if(!cfg_ready || busy || done_valid || frame_valid)$fatal(1,"COMMIT_RESET_STATE");
 endtask
 task automatic configure;
  @(negedge clk);cfg_heads='1;cfg_query=280;cfg_epoch=16'ha791;cfg_tag=32'h125671ab;broker_all_collected=1;cfg_valid=1;
  @(posedge clk);if(!cfg_ready || !broker_cfg_valid || !collector_cfg_valid)$fatal(1,"COMMIT_ATOMIC_ACCEPT");
  @(negedge clk);cfg_valid=0;cfg_query='1;cfg_epoch=0;cfg_tag=0;cfg_heads=0;
  if(cfg_ready || !busy)$fatal(1,"COMMIT_ACCEPT_BUSY");
 endtask
 task automatic send_row(input int head);
  @(negedge clk);broker_row_head=5'(head);broker_row_offer=1;
  repeat(3)begin
   @(negedge clk);if(broker_row_ready || !collector_row_valid || frame_valid)$fatal(1,"COMMIT_ROW_BACKPRESSURE");
  end
  collector_row_ready=1;@(posedge clk);if(!broker_row_ready)$fatal(1,"COMMIT_ROW_NOT_FORWARDED");
  @(negedge clk);broker_row_offer=0;collector_row_ready=0;if(head==0)broker_all_collected=0;
 endtask
 task automatic broker_finish(input bit bad);
  @(negedge clk);broker_done_error=bad;broker_done_valid=1;
  do @(posedge clk);while(!broker_done_ready);
  @(negedge clk);broker_done_valid=0;broker_done_error=0;
 endtask
 task automatic expect_failed(input logic[7:0] code);
  for(int i=0;i<20;i++)begin @(negedge clk);if(done_valid)break;end
  if(!done_valid || !done_error || !reset_required || cfg_ready || frame_valid || collector_rst_n || error_code!=code)
   $fatal(1,"COMMIT_FAILURE_FENCE code=%02h expected=%02h",error_code,code);
  done_ready=1;repeat(4)@(negedge clk);done_ready=0;
  if(!done_valid || cfg_ready || !busy)$fatal(1,"COMMIT_FAILED_REUSE");
 endtask
 task automatic positive_frame(input bit collector_first);
  configure();
  for(int head=0;head<32;head++)send_row(head);
  if(collector_first)begin
   collector_context_valid=1;repeat(3)begin @(negedge clk);if(frame_valid || context_route_enable)$fatal(1,"COMMIT_PREMATURE_FRAME");end
  end
  broker_finish(0);
  if(!collector_first)begin repeat(2)@(negedge clk);if(frame_valid)$fatal(1,"COMMIT_WITHOUT_CONVERSION");collector_context_valid=1;end
  do @(negedge clk);while(!frame_valid);
  if(!context_route_enable)$fatal(1,"COMMIT_ROUTE_NOT_ENABLED");
  projection_idle=0;finish_valid=1;
  repeat(4)begin @(negedge clk);if(finish_ready || collector_finish_valid || frame_valid || !context_route_enable)$fatal(1,"COMMIT_EARLY_RELEASE");end
  projection_idle=1;#1;if(!finish_ready || !collector_finish_valid || frame_valid)$fatal(1,"COMMIT_FINISH_NOT_FORWARDED");
  @(negedge clk);finish_valid=0;collector_context_valid=0;collector_done_valid=1;
  do @(posedge clk);while(!collector_done_ready);
  @(negedge clk);collector_done_valid=0;
  if(!done_valid || done_error || reset_required || cfg_ready || !busy)$fatal(1,"COMMIT_POSITIVE_DONE");
  repeat(3)@(negedge clk);done_ready=1;@(negedge clk);done_ready=0;
  #1;if(!cfg_ready || busy || done_valid)$fatal(1,"COMMIT_POSITIVE_REUSE");
  positive_frames++;
 endtask
 initial begin
  reset_all();
  collector_cfg_ready=0;cfg_valid=1;repeat(3)begin @(negedge clk);if(cfg_ready || broker_cfg_valid || collector_cfg_valid)$fatal(1,"COMMIT_STAGGERED_READY");end
  cfg_valid=0;collector_cfg_ready=1;
  @(negedge clk);cancel=1;cfg_valid=1;#1;
  if(cfg_ready || broker_cfg_valid || collector_cfg_valid)$fatal(1,"COMMIT_CONFIG_CANCEL_ACCEPTED");
  @(negedge clk);cancel=0;cfg_valid=0;
  cfg_heads=32'h7fffffff;projection_idle=0;cfg_valid=1;#1;
  if(!cfg_ready || broker_cfg_valid || collector_cfg_valid)$fatal(1,"COMMIT_PARTIAL_HEAD_FRAME_ADMITTED");
  @(negedge clk);cfg_valid=0;
  repeat(3)begin @(negedge clk);if(!collector_rst_n || done_valid)$fatal(1,"COMMIT_INVALID_CONFIG_RESET_BEFORE_DRAIN");end
  projection_idle=1;expect_failed(8'h01);reset_all();
  positive_frame(1);positive_frame(0);
  reset_all();configure();broker_row_offer=1;broker_row_query=279;
  @(negedge clk);if(collector_row_valid || broker_row_ready)$fatal(1,"COMMIT_FOREIGN_ROW_FORWARDED");
  broker_row_offer=0;broker_finish(1);expect_failed(8'h03);
  reset_all();configure();send_row(0);broker_row_head=0;broker_row_offer=1;
  @(negedge clk);broker_row_offer=0;broker_finish(1);expect_failed(8'h03);
  reset_all();configure();broker_finish(0);expect_failed(8'h04);
  reset_all();configure();cancel=1;projection_idle=0;
  @(negedge clk);cancel=0;
  if(!broker_cancel || !collector_rst_n || done_valid)$fatal(1,"COMMIT_CANCEL_BEFORE_DRAIN");
  broker_finish(1);repeat(4)begin @(negedge clk);if(done_valid || !collector_rst_n)$fatal(1,"COMMIT_RESET_BEFORE_PROJECTION_DRAIN");end
  projection_idle=1;expect_failed(8'h02);
  reset_all();configure();for(int head=0;head<32;head++)send_row(head);
  broker_finish(0);collector_context_valid=1;do @(negedge clk);while(!frame_valid);
  projection_idle=0;collector_done_error=1;
  repeat(3)begin @(negedge clk);if(frame_valid || !context_route_enable || !collector_rst_n || done_valid)$fatal(1,"COMMIT_ERROR_DROPPED_ACCEPTED_ROUTE");end
  projection_idle=1;expect_failed(8'h06);
  reset_all();cfg_heads=1;cfg_valid=1;@(posedge clk);
  if(!cfg_ready || broker_cfg_valid || collector_cfg_valid)$fatal(1,"COMMIT_INVALID_HEAD_MASK_STARTED");
  @(negedge clk);cfg_valid=0;expect_failed(8'h01);
  $display("ATTENTION_CONTEXT_COMMIT_PASS positive_frames=%0d forwarded_rows=%0d local_resets=%0d",positive_frames,rows,collector_resets);$finish;
 end
 initial begin #100000;$fatal(1,"COMMIT_UNIT_WATCHDOG");end
endmodule
