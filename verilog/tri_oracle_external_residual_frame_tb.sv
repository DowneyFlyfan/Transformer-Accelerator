`timescale 1ns/1ps
module tri_oracle_external_residual_frame_tb;
 localparam logic[63:0] Base=64'h10000,ScalarBase=64'h14000;
 localparam logic[31:0] Tag=32'h39300001;
 localparam logic[63:0] Scalar0=64'h0123456789abcdef,Scalar1=64'hfedcba9876543210;
 logic clk=0,rst_n=0;always #5 clk=~clk;
 logic cfg_valid=0,cfg_ready,abort_frame=0;
 logic[31:0] cfg_tag=Tag;
 logic[63:0] cfg_base=Base;
 logic[9:0] cfg_rows=512;
 logic[4:0] cfg_tokens=2;
 logic[8:0] cfg_strips=256;
 logic bypass_valid,bypass_ready,normalization_valid,normalization_ready;
 logic[31:0] bypass_tag=Tag,normalization_tag=Tag;
 logic[8:0] bypass_row,normalization_row;
 logic[231:0] bypass_data;
 logic[127:0] normalization_data;
 logic source_done_valid=0,source_done_ready,source_done_error=0;
 logic[31:0] source_done_tag=Tag;
 logic captured_valid,captured_error;
 logic[31:0] captured_tag;
 logic[7:0] captured_code;
 logic normalization_start_valid=0,normalization_start_ready,normalization_done,frame_fault;
 logic[7:0] fault_code;
 logic[3:0] normalization_token,consumer_token;
 logic[8:0] normalization_strip;
 logic stats_valid,stats_last,replay_valid,replay_last,stats_ready,replay_ready;
 logic[127:0] stats_data,replay_data;
 logic bank_read_valid=0,bank_read_ready,bank_response_valid,bank_response_error,bank_response_ready=0;
 logic[8:0] bank_read_row=0;
 logic[231:0] bank_response_data;
 logic release_valid=0,release_ready;
 logic[1:0] scalar_req_valid=0,scalar_req_ready,scalar_rsp_valid,scalar_rsp_last,scalar_rsp_error,scalar_rsp_ready;
 logic[127:0] scalar_req_address=0,scalar_rsp_data;
 logic[9:0] scalar_req_length=0;
 logic scalar_write_req_valid=0,scalar_write_req_ready;
 logic[63:0] scalar_write_address=ScalarBase,scalar_write_data=0;
 logic[4:0] scalar_write_length=2;
 logic scalar_write_data_valid=0,scalar_write_data_last=0,scalar_write_data_ready;
 logic[7:0] scalar_write_strobe=8'hff;
 logic scalar_write_rsp_valid,scalar_write_rsp_error,scalar_write_rsp_ready=0;
 logic mr_req_valid,mr_req_ready,mr_rsp_valid,mr_last,mr_error,mr_rsp_ready;
 logic[63:0] mr_address,mr_data;
 logic[4:0] mr_length;
 logic mw_req_valid,mw_req_ready,mw_data_valid,mw_last,mw_data_ready,mw_rsp_valid,mw_error,mw_rsp_ready;
 logic[63:0] mw_address,mw_data;
 logic[4:0] mw_length;
 logic[7:0] mw_strobe;
 tri_oracle_external_residual_frame hub(.*);
 logic input_valid=0,input_ready;
 logic[8:0] input_row=0;
 logic[279:0] input_residual=0;
 logic[63:0] input_codes=0;
 logic[4:0] input_shift=0;
 tri_oracle_attention_residual_store producer(
  .clk,.rst_n,.in_valid(input_valid),.in_ready(input_ready),.in_row(input_row),
  .residual_q32(input_residual),.projection_codes(input_codes),.projection_shift(input_shift),
  .write_valid(bypass_valid),.write_ready(bypass_ready),.write_row(bypass_row),.write_data(bypass_data),
  .norm_valid(normalization_valid),.norm_ready(normalization_ready),.norm_row(normalization_row),.norm_data(normalization_data)
 );
 logic[279:0] producer_residual[512];
 logic[63:0] producer_codes[512];
 logic[4:0] producer_shifts[512];
 logic[127:0] expected_norm[512];
 logic[231:0] expected_bypass[512];
 // The only assignments to writable memory data are accepted external beats.
 logic[63:0] memory[4096];
 bit memory_valid[4096];
 int cycle=0,w_start=0,w_beat=0,w_length=0,w_delay=0,r_start=0,r_beat=0,r_length=0,r_delay=0;
 int write_beats=0,write_acks=0,read_packets=0,read_beats=0;
 int producer_bypass=0,producer_normal=0,stats_rows=0,replay_rows=0,bank_rows=0,stage=0,contention=0;
 int scalar_requests[2]='{0,0},scalar_beats[2]='{0,0};
 bit w_busy=0,w_ack=0,r_busy=0;
 bit checking_abort=0;
 string root,trained;
 always_comb begin
  mw_req_ready=rst_n && !w_busy && !w_ack && cycle%5!=0;
  mw_data_ready=rst_n && w_busy && cycle%3!=0;
  mw_rsp_valid=rst_n && w_ack && w_delay==0;mw_error=0;
  mr_req_ready=rst_n && !r_busy && cycle%4!=0;
  mr_rsp_valid=rst_n && r_busy && r_delay==0;mr_last=r_beat+1==r_length;mr_error=0;
  mr_data=r_busy ? memory[12'($unsigned(r_start+r_beat))]:64'd0;
  stats_ready=rst_n && cycle%7>=3;replay_ready=rst_n && cycle%5>=2;
  scalar_rsp_ready={1'(cycle%4>=2),1'(cycle%3!=0)};
  consumer_token=4'(stage<4 ? stage/2:1);
 end
 always @(posedge clk)if(rst_n)begin
  cycle<=cycle+1;if(cycle>500000)$fatal(1,"HUB_WATCHDOG");
  if(frame_fault && !checking_abort)$fatal(1,"HUB_UNEXPECTED_FAULT code=%0d",fault_code);
  if(mw_req_valid && mw_req_ready)begin
   if(mw_address<Base || mw_address+64'(mw_length)*8>Base+32768 || mw_address[2:0]!=0 || mw_length==0 || mw_length>16)
    $fatal(1,"HUB_WRITE_RANGE");
   w_busy<=1;w_start<=int'((mw_address-Base)>>3);w_length<=int'(mw_length);w_beat<=0;
   $display("HUB_WRITE_REQUEST address=%016h length=%0d",mw_address,mw_length);
  end
  if(mw_data_valid && mw_data_ready)begin
   if(mw_strobe!==8'hff || mw_last!==(w_beat+1==w_length))$fatal(1,"HUB_WRITE_PROTOCOL");
   memory[12'($unsigned(w_start+w_beat))]<=mw_data;memory_valid[12'($unsigned(w_start+w_beat))]<=1;write_beats++;
   $display("HUB_WRITE_BEAT word=%0d data=%016h",w_start+w_beat,mw_data);
   if(mw_last)begin w_busy<=0;w_ack<=1;w_delay<=4;end else w_beat<=w_beat+1;
  end
  if(w_delay>0)w_delay<=w_delay-1;
  if(mw_rsp_valid && mw_rsp_ready)begin w_ack<=0;write_acks++;$display("HUB_WRITE_ACK index=%0d",write_acks);end
  if(mr_req_valid && mr_req_ready)begin
   if(mr_address<Base || mr_address+64'(mr_length)*8>Base+32768 || mr_address[2:0]!=0 || mr_length==0 || mr_length>16)
    $fatal(1,"HUB_READ_RANGE");
   r_busy<=1;r_start<=int'((mr_address-Base)>>3);r_length<=int'(mr_length);r_beat<=0;r_delay<=3;read_packets++;
   $display("HUB_READ_REQUEST address=%016h length=%0d",mr_address,mr_length);
  end
  if(r_delay>0)r_delay<=r_delay-1;
  if(mr_rsp_valid && mr_rsp_ready)begin
   if(!memory_valid[12'($unsigned(r_start+r_beat))])$fatal(1,"HUB_UNWRITTEN_READ");
   $display("HUB_READ_BEAT word=%0d data=%016h last=%0d",r_start+r_beat,mr_data,mr_last);
   read_beats++;if(mr_last)r_busy<=0;else begin r_beat<=r_beat+1;r_delay<=cycle%3;end
  end
  if(bypass_valid && bypass_ready)begin
   if(bypass_row!==9'(producer_bypass) || bypass_data!==expected_bypass[producer_bypass])$fatal(1,"HUB_PRODUCER_BYPASS_WRONG");
   $display("HUB_PRODUCER_BYPASS row=%0d data=%058h",bypass_row,bypass_data);producer_bypass++;
  end
  if(normalization_valid && normalization_ready)begin
   if(normalization_row!==9'(producer_normal) || normalization_data!==expected_norm[producer_normal])$fatal(1,"HUB_PRODUCER_NORMAL_WRONG");
   $display("HUB_PRODUCER_NORMAL row=%0d data=%032h",normalization_row,normalization_data);producer_normal++;
  end
  if(stats_valid && stats_ready)begin
   if(normalization_token!==4'(stats_rows/256) || normalization_strip!==9'(stats_rows%256) ||
      stats_last!==(stats_rows%256==255) || stats_data!==expected_norm[stats_rows] || stage!=2*(stats_rows/256))
    $fatal(1,"HUB_STATS_WRONG");
   $display("HUB_STATS token=%0d strip=%0d data=%032h",normalization_token,normalization_strip,stats_data);
   stats_rows++;if(stats_last)stage<=stage+1;
  end
  if(replay_valid && replay_ready)begin
   if(normalization_token!==4'(replay_rows/256) || normalization_strip!==9'(replay_rows%256) ||
      replay_last!==(replay_rows%256==255) || replay_data!==expected_norm[replay_rows] || stage!=2*(replay_rows/256)+1)
    $fatal(1,"HUB_REPLAY_WRONG");
   $display("HUB_REPLAY token=%0d strip=%0d data=%032h",normalization_token,normalization_strip,replay_data);
   replay_rows++;if(replay_last)stage<=stage+1;
  end
  if(bank_response_valid && bank_response_ready)begin
   if(bank_response_error || bank_response_data!==expected_bypass[bank_rows])$fatal(1,"HUB_BANK_WRONG");
   $display("HUB_BANK row=%0d data=%058h",bank_rows,bank_response_data);bank_rows++;
  end
  if(scalar_req_valid==2'b11)contention++;
  for(int client=0;client<2;client++)begin
   if(scalar_req_valid[client] && scalar_req_ready[client])scalar_requests[client]++;
   if(scalar_rsp_valid[client] && scalar_rsp_ready[client])begin
    if(scalar_rsp_error[client] || scalar_rsp_last[client]!==1'(scalar_beats[client]%2) ||
       scalar_rsp_data[client*64+:64]!==(scalar_beats[client]%2==0 ? Scalar0:Scalar1))$fatal(1,"HUB_SCALAR_RESPONSE_WRONG");
    $display("HUB_SCALAR client=%0d beat=%0d data=%016h last=%0d",client,scalar_beats[client],scalar_rsp_data[client*64+:64],scalar_rsp_last[client]);
    scalar_beats[client]++;
   end
  end
 end
 task automatic send_producer;
  for(int row=0;row<512;row++)begin
   @(negedge clk);input_valid=1;input_row=9'(row);input_residual=producer_residual[row];input_codes=producer_codes[row];input_shift=producer_shifts[row];
   do @(posedge clk);while(!input_ready);
  end
  @(negedge clk);input_valid=0;
  while(producer_bypass!=512 || producer_normal!=512)@(negedge clk);
  source_done_valid=1;do @(posedge clk);while(!source_done_ready);
  @(negedge clk);source_done_valid=0;
 endtask
 task automatic write_scalar;
  @(negedge clk);scalar_write_req_valid=1;
  do @(posedge clk);while(!scalar_write_req_ready);
  @(negedge clk);scalar_write_req_valid=0;scalar_write_address='1;scalar_write_length='1;
  for(int beat=0;beat<2;beat++)begin
   scalar_write_data_valid=1;scalar_write_data=beat==0 ? Scalar0:Scalar1;scalar_write_data_last=beat==1;
   do @(posedge clk);while(!scalar_write_data_ready);
   @(negedge clk);
  end
  scalar_write_data_valid=0;repeat(4)@(negedge clk);scalar_write_rsp_ready=1;
  do @(posedge clk);while(!scalar_write_rsp_valid);
  if(scalar_write_rsp_error)$fatal(1,"HUB_SCALAR_WRITE_ERROR");
  @(negedge clk);scalar_write_rsp_ready=0;
  $display("HUB_SCALAR_WRITE_PASS words=2");
 endtask
 task automatic scalar_reader(input int client);
  for(int request=0;request<12;request++)begin
   @(negedge clk);scalar_req_valid[client]=1;scalar_req_address[client*64+:64]=ScalarBase;scalar_req_length[client*5+:5]=2;
   do @(posedge clk);while(!scalar_req_ready[client]);
   @(negedge clk);scalar_req_valid[client]=0;scalar_req_address[client*64+:64]='1;scalar_req_length[client*5+:5]='1;
   while(scalar_beats[client]<(request+1)*2)@(negedge clk);
  end
 endtask
 initial begin
  int timeout_count;
  if(!$value$plusargs("ROOT=%s",root) || !$value$plusargs("TRAINED_ROOT=%s",trained))$fatal(1,"HUB_NO_FIXTURE");
  $readmemh({root,"/producer_residual_q32.hex"},producer_residual);$readmemh({root,"/producer_codes.hex"},producer_codes);
  $readmemh({root,"/producer_shifts.hex"},producer_shifts);$readmemh({trained,"/computed_normalization_q13.hex"},expected_norm);
  $readmemh({trained,"/computed_bypass_q26.hex"},expected_bypass);
  repeat(4)@(negedge clk);rst_n=1;@(negedge clk);cfg_valid=1;timeout_count=0;
  while(!cfg_ready)begin @(posedge clk);#1;timeout_count++;if(timeout_count>50)$fatal(1,"HUB_CFG_TIMEOUT");end
  @(posedge clk);@(negedge clk);cfg_valid=0;cfg_tag='1;cfg_base='1;cfg_rows=0;cfg_tokens=0;cfg_strips=0;
  fork send_producer();write_scalar();join
  while(!captured_valid)@(negedge clk);
  if(captured_error || captured_tag!==Tag || captured_code!=0 || write_beats!=2050 || write_acks!=257)
   $fatal(1,"HUB_CAPTURE_NOT_ACKNOWLEDGED");
  $display("HUB_CAPTURE_PASS rows=512 write_beats=2050 write_acks=257");
  normalization_start_valid=1;do @(posedge clk);while(!normalization_start_ready);
  @(negedge clk);normalization_start_valid=0;
  fork scalar_reader(0);scalar_reader(1);join
  while(!normalization_done)@(negedge clk);
  if(stats_rows!=512 || replay_rows!=512)$fatal(1,"HUB_NORMALIZATION_INCOMPLETE");
  for(int row=0;row<512;row++)begin
   @(negedge clk);bank_read_valid=1;bank_read_row=9'(row);
   do @(posedge clk);while(!bank_read_ready);
   @(negedge clk);bank_read_valid=0;bank_read_row='1;
   while(!bank_response_valid)@(negedge clk);
   repeat(3)begin @(posedge clk);#1;if(!bank_response_valid || release_ready)$fatal(1,"HUB_HELD_BANK_DROPPED");end
   @(negedge clk);bank_response_ready=1;@(posedge clk);@(negedge clk);bank_response_ready=0;
  end
  if(bank_rows!=512 || read_packets!=792 || read_beats!=6192 || scalar_requests[0]!=12 || scalar_requests[1]!=12 ||
     scalar_beats[0]!=24 || scalar_beats[1]!=24 || contention==0 || w_busy || w_ack || r_busy)$fatal(1,"HUB_FINAL_INVENTORY");
  release_valid=1;do @(posedge clk);while(!release_ready);
  @(negedge clk);release_valid=0;
  if(captured_valid || normalization_done || !cfg_ready)$fatal(1,"HUB_RELEASE_NOT_ATOMIC");
  $display("HUB_RELEASE_PASS captured=0 normalization_done=0 cfg_ready=1");
  // An aborted capture has never started replay; its error terminal must be
  // releasable without a consumer reset and without new memory transactions.
  @(negedge clk);checking_abort=1;cfg_valid=1;cfg_tag=Tag+1;cfg_base=Base;
  cfg_rows=2;cfg_tokens=1;cfg_strips=2;
  do @(posedge clk);while(!cfg_ready);
  @(negedge clk);cfg_valid=0;abort_frame=1;
  while(!captured_valid)@(negedge clk);
  if(!captured_error || captured_code!==8'd2 || !frame_fault || fault_code!==8'd2 ||
     normalization_start_ready || normalization_done || stats_valid || replay_valid || bank_response_valid)
   $fatal(1,"HUB_CAPTURE_ABORT_NOT_HELD");
  abort_frame=0;release_valid=1;timeout_count=0;
  while(!release_ready)begin
   @(posedge clk);#1;timeout_count++;
   if(timeout_count>50)$fatal(1,"HUB_CAPTURE_ABORT_RELEASE_TIMEOUT");
  end
  @(posedge clk);@(negedge clk);release_valid=0;
  if(captured_valid || frame_fault || !cfg_ready || normalization_done || write_beats!=2050 ||
     write_acks!=257 || read_packets!=792 || read_beats!=6192)
   $fatal(1,"HUB_CAPTURE_ABORT_RELEASE_WRONG");
  $display("HUB_CAPTURE_ABORT_PASS error=2 released=1");
  $display("HUB_PIPELINE_PASS producer_rows=512 stats=512 replay=512 bypass=512 write_beats=2050 write_acks=257 scalar_requests=24 scalar_beats=48 read_packets=792 read_beats=6192");
  $finish;
 end
endmodule
