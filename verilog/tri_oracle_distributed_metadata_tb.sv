`timescale 1ns/1ps
// Catches an early lease, a newly accepted blocked descriptor, stale flags
// after context overwrites, and changed prediction under output backpressure.
module tri_oracle_distributed_metadata_tb;
  logic clk=0,rst_n=0;
  always #5 clk=~clk;
  logic cfg_valid=0,cfg_ready;
  logic [31:0] cfg_tag=32'h55110000;
  logic meta_valid=0,meta_last=0,meta_ready;
  logic [31:0] meta_tag=0;
  logic [3:0] meta_token=0;
  logic [9:0] meta_index=0;
  logic [7:0] meta_outliers=0,meta_negative=0;
  logic commit_valid=0,commit_ready;
  logic out_valid,out_ready,out_last,done_valid,done_ready=0,done_error;
  logic [31:0] out_tag,done_tag,gate_nearzero_mask,up_nearzero_mask,skip_mask;
  logic [7:0] out_group;
  logic [3:0] out_token;
  logic [12:0] outlier_count;
  logic sign_req_valid,sign_req_ready,sign_rsp_valid=0,sign_rsp_ready;
  logic [63:0] sign_req_address;
  logic [4:0] sign_req_length;
  logic [533:0] strip_request;
  logic [111:0] strip_response;
  wire [111:0] cluster_responses[5];
  for(genvar cluster=0;cluster<5;cluster++)begin:clusters
    wire [587:0] core_requests;
    wire [159:0] core_responses;
    tri_oracle_cluster_strip448 route(
      .request(strip_request[533:531]==3'(cluster) ? strip_request[530:0] : 531'b0),
      .response(cluster_responses[cluster]),.core_requests,.core_responses
    );
    for(genvar core=0;core<4;core++)begin:cores
      tri_oracle_core_strip448 estimator(.clk,.rst_n,
        .request(core_requests[147*core+:147]),.response(core_responses[40*core+:40]));
    end
  end
  assign strip_response=strip_request[533:531]<5 ? cluster_responses[strip_request[533:531]] : 112'b0;
  logic metadata_block,metadata_idle,metadata_rebuilt;
  logic [1:0] ff_ce_n,ff_we_n;
  logic [17:0] ff_address;
  logic [127:0] ff_write_data,ff_read_data;
  logic pending=0,context_owned;
  logic collector_cfg_ready,row_valid=0,row_ready,context_valid,finish_valid=0,finish_ready;
  logic collector_done,collector_done_ready=0,collector_error,metadata_needs_rebuild;
  logic [31:0] context_tag;
  logic [10:0] context_query;
  logic signed [8:0] context_exponent;
  logic [4:0] row_head=0;
  logic [2047:0] row_data=0;
  logic signed [7:0] row_value_exponent=0;
  logic req_valid=0,req_write=0,req_ready,rsp_valid,rsp_error,rsp_ready=0;
  logic [9:0] req_word=0;
  logic [63:0] req_data=0,rsp_data;
  int cycle=0,outputs=0,descriptors=0,sign_reads=0,rebuilds=0,context_writes=0,context_reads=0;
  int vendor_cell_count=0;
  bit lower_cell_seen=0,upper_cell_seen=0;
  logic output_held=0;
  logic [153:0] held_prediction;
  wire [153:0] prediction={out_tag,out_group,out_token,out_last,gate_nearzero_mask,up_nearzero_mask,skip_mask,outlier_count};

  assign out_ready=rst_n && cycle%3!=0;
  assign sign_req_ready=rst_n && !sign_rsp_valid && cycle%5!=0;
  tri_oracle_batched_metadata_replay #(.CORE_STRIP_PREDICTOR(1)) predictor (
    .clk,.rst_n,.cfg_valid,.cfg_ready,.cfg_tag,.cfg_tokens(5'd16),.cfg_strips(10'd4),.cfg_groups(8'd5),
    .cfg_gate_sign_base(64'h1000),.cfg_up_sign_base(64'h2000),
    .meta_valid,.meta_last,.meta_ready,.meta_tag,.meta_token,.meta_index,.meta_outliers,.meta_negative,
    .commit_valid,.commit_ready,.abort_fill(1'b0),
    .out_valid,.out_ready,.out_last,.out_tag,.out_group,.out_token,
    .gate_nearzero_mask,.up_nearzero_mask,.skip_mask,.outlier_count,
    .done_valid,.done_ready,.done_error,.done_tag,
    .req_valid(sign_req_valid),.req_ready(sign_req_ready),.req_address(sign_req_address),.req_length(sign_req_length),
    .rsp_valid(sign_rsp_valid),.rsp_ready(sign_rsp_ready),.rsp_last(1'b1),.rsp_error(1'b0),.rsp_data(64'b0),
    .strip_request,.strip_response,
    .metadata_block,.metadata_idle,.metadata_rebuilt,
    .metadata_ce_n(ff_ce_n),.metadata_we_n(ff_we_n),.metadata_address(ff_address),
    .metadata_write_data(ff_write_data),.metadata_read_data(ff_read_data)
  );
  tri_oracle_metadata_context_handoff collector(
    .clk,.rst_n,.cfg_valid(pending),.cfg_ready(collector_cfg_ready),.cfg_tag(32'hc7110011),.cfg_query(11'd17),.cfg_zero_exponent(-9'sd5),
    .row_valid,.row_ready,.row_error(1'b0),.row_query(11'd17),.row_head,.row_data,.row_value_exponent,
    .metadata_idle,.metadata_block,.metadata_needs_rebuild,.metadata_rebuilt,.lease_active(context_owned),
    .metadata_ce_n(ff_ce_n),.metadata_we_n(ff_we_n),.metadata_address(ff_address),.metadata_write_data(ff_write_data),.metadata_read_data(ff_read_data),
    .context_valid,.context_tag,.context_query,.context_exponent,
    .read_req_valid(req_valid),.read_req_ready(req_ready),.read_req_word(req_word),
    .read_rsp_valid(rsp_valid),.read_rsp_ready(rsp_ready),.read_rsp_error(rsp_error),.read_rsp_data(rsp_data),
    .finish_valid,.finish_ready,.done_valid(collector_done),.done_ready(collector_done_ready),.done_error(collector_error)
  );
  // Literal positive sign weights: every fetched bit is zero. Frame zero
  // has four equal activation signs per token; frame one alternates signs,
  // giving a balanced zero estimate and all32 skip bits after a real rebuild.
  always @(posedge clk)begin
    if(!rst_n)begin cycle<=0;sign_rsp_valid<=0;end
    else begin
      cycle<=cycle+1;
      if(sign_rsp_valid && sign_rsp_ready)sign_rsp_valid<=0;
      if(sign_req_valid && sign_req_ready)begin
        if(sign_req_length!=1 || sign_req_address[2:0]!=0 ||
          !((sign_req_address>=64'h1000 && sign_req_address<64'h1280) ||
            (sign_req_address>=64'h2000 && sign_req_address<64'h2280)))
          $fatal(1,"COUPLED_SIGN_ADDRESS");
        sign_rsp_valid<=1;sign_reads++;
      end
      if(cfg_valid && cfg_ready)descriptors++;
      if(metadata_rebuilt)rebuilds++;
      if(context_owned && (!metadata_idle || cfg_ready || ff_read_data!==0))
        $fatal(1,"COUPLED_CONTEXT_STOLE_PREDICTOR");
      if(output_held && (!out_valid || prediction!==held_prediction))$fatal(1,"COUPLED_PREDICTION_CHANGED_WHILE_HELD");
      output_held<=out_valid && !out_ready;
      held_prediction<=prediction;
      if(out_valid && out_ready)begin
        if(out_tag!==(32'h55110000+32'(outputs/80)) || out_group!==8'((outputs%80)/16) ||
           out_token!==4'(outputs%16) || out_last!==(outputs%80==79) || outlier_count!=4)
          $fatal(1,"COUPLED_PREDICTION_FRAME index=%0d count=%0d",outputs,outlier_count);
        if(outputs<80)begin
          if(gate_nearzero_mask!==(out_token[0]?32'hffffffff:32'b0) || up_nearzero_mask!==0 || skip_mask!==0)
            $fatal(1,"COUPLED_FIRST_FRAME_MASK index=%0d",outputs);
        end else if(gate_nearzero_mask!==32'hffffffff || up_nearzero_mask!==32'hffffffff || skip_mask!==32'hffffffff)
          $fatal(1,"COUPLED_REBUILT_FRAME_MASK index=%0d",outputs);
        outputs++;
      end
    end
  end
  task automatic step;
    @(posedge clk);#2;
  endtask
  task automatic fill_frame(input int frame_number);
    for(int token_number=0;token_number<16;token_number++)begin
      for(int strip_number=0;strip_number<4;strip_number++)begin
        @(negedge clk);meta_valid=1;meta_tag=32'h55110000+32'(frame_number);
        meta_token=4'(token_number);meta_index=10'(strip_number);meta_last=strip_number==3;
        meta_outliers=8'b1<< (token_number%8);
        meta_negative=(frame_number==0 ? token_number%2 : strip_number%2) ? meta_outliers : 8'b0;
        if(frame_number==0 && token_number==0 && strip_number==1)pending=1;
        while(!meta_ready)@(negedge clk);
        step();
      end
    end
    @(negedge clk);meta_valid=0;commit_valid=1;
    wait(commit_ready);step();
    @(negedge clk);commit_valid=0;
  endtask
  // Every raw value is exactly +/-64*65535. Even heads have exponent0;
  // odd heads have exponent-1. The common unit is0: output codes are
  // +/-64 and +/-32, with eight words per head and alternating signs.
  task automatic send_row(input int head_number);
    @(negedge clk);row_head=5'(head_number);row_value_exponent=head_number%2 ? -8'sd1 : 8'sd0;
    for(int lane=0;lane<64;lane++)row_data[32*lane+:32]=lane%2 ? -32'sd4194240 : 32'sd4194240;
    row_valid=1;
    do @(posedge clk);while(!row_ready);
    @(negedge clk);row_valid=0;
  endtask
  task automatic read_context(input int index);
    logic [63:0] expected;
    expected=(index/8)%2 ? 64'he020e020e020e020 : 64'hc040c040c040c040;
    @(negedge clk);req_valid=1;req_word=10'(index);
    if(!req_ready)$fatal(1,"COLLECTOR_CONTEXT_REQUEST_NOT_READY");
    step();
    if(!rsp_valid || rsp_error || rsp_data!==expected)$fatal(1,"COLLECTOR_CONTEXT_WORD index=%0d got=%016h expected=%016h",index,rsp_data,expected);
    @(negedge clk);req_valid=0;finish_valid=1;
    repeat(3)begin
      step();if(!rsp_valid || req_ready || finish_ready || cfg_ready || !context_owned || rsp_data!==expected)
        $fatal(1,"COLLECTOR_CONTEXT_HELD_RESPONSE");
    end
    @(negedge clk);finish_valid=0;rsp_ready=1;step();
    @(negedge clk);rsp_ready=0;context_reads++;
  endtask
  initial begin
    repeat(3)step();@(negedge clk);rst_n=1;cfg_valid=1;
    wait(cfg_ready);step();@(negedge clk);cfg_valid=0;
    fill_frame(0);
    wait(done_valid);#2;
    if(done_error || done_tag!==32'h55110000 || outputs!=80 || descriptors!=1 || rebuilds!=1)$fatal(1,"COUPLED_FIRST_FRAME_DONE");
    @(negedge clk);cfg_valid=1;cfg_tag=32'h55110001;
    repeat(8)begin
      step();if(context_owned || cfg_ready || metadata_idle || !done_valid || !metadata_block)$fatal(1,"COUPLED_LEASE_BEFORE_RETIREMENT");
    end
    @(negedge clk);done_ready=1;step();@(negedge clk);done_ready=0;
    wait(context_owned);#2;
    if(descriptors!=1 || cfg_ready || !metadata_idle)$fatal(1,"COUPLED_BLOCKED_DESCRIPTOR_ACCEPTED");
    for(int i=0;i<32;i++)send_row((17*i+31)%32);
    wait(context_valid);#2;
    if(collector_done || collector_error || context_tag!==32'hc7110011 || context_query!=17 || context_exponent!==0 || !metadata_needs_rebuild)
      $fatal(1,"COLLECTOR_CONTEXT_FRAME");
    for(int i=0;i<256;i++)read_context(i);
    @(negedge clk);finish_valid=1;req_valid=1;req_word=10'd0;#1;
    if(!finish_ready || req_ready)$fatal(1,"COLLECTOR_FINISH_PRIORITY");
    step();@(negedge clk);finish_valid=0;req_valid=0;pending=0;
    wait(collector_done);#2;
    repeat(5)begin
      step();if(collector_error || context_owned || cfg_ready || !metadata_block || !metadata_needs_rebuild)
        $fatal(1,"COLLECTOR_COMPLETION_FENCE");
    end
    @(negedge clk);collector_done_ready=1;step();@(negedge clk);collector_done_ready=0;
    wait(cfg_ready);step();@(negedge clk);cfg_valid=0;
    fill_frame(1);wait(done_valid);#2;
    if(done_error || done_tag!==32'h55110001 || outputs!=160 || descriptors!=2 || sign_reads!=1280 || rebuilds!=2 ||
       metadata_needs_rebuild || context_reads!=256 || vendor_cell_count!=2 || !lower_cell_seen || !upper_cell_seen)
      $fatal(1,"COUPLED_REBUILT_FRAME_DONE outputs=%0d descriptors=%0d signs=%0d rebuilds=%0d",outputs,descriptors,sign_reads,rebuilds);
    @(negedge clk);done_ready=1;step();
    $display("DISTRIBUTED_METADATA_CONNECTION_PASS frames=2 tokens=32 metadata_strips=128 predictions=160 sign_reads=1280 supplied_raw_head_rows=32 context_words=256 vendor_cells=2 clusters=5 core_predictors=20 held_completion=1 blocked_descriptor=1 rebuild=1");
    $finish;
  end
  initial begin #1000000;$fatal(1,"COUPLED_PREDICTOR_CONTEXT_TIMEOUT");end
endmodule
