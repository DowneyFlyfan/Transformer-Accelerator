`timescale 1ns/1ps
// Compile in place of190's bench, preserving its production source/memory bundle.
// Actual predictor -> actual20-core numeric frame; selected contributions only.
module tri_oracle_predicted_feedforward_frame_tb;
  localparam int HIDDEN=2048, DENSE=5632, SELECTED=64, OUTPUTS=35;
  localparam logic [63:0] ActBase=64'h100002000, GateBase=64'h200004000;
  localparam logic [63:0] UpBase=64'h300008000, DownBase=64'h100000;
  logic clk=0; always #5 clk=~clk;
  logic rst_n=0,cfg_valid=0,in_valid=0,in_last=0,in_group_last=0;
  logic [31:0] cfg_tag=0;
  logic [63:0] cfg_activation_base=0,cfg_weight_base=0,cfg_up_weight_base=0,cfg_down_weight_base=0;
  logic [9:0] cfg_features=0;
  logic [16:0] cfg_dense_features=0;
  logic [15:0] cfg_output_count=0;
  logic [5:0] cfg_gate_shift=0,cfg_up_shift=0,cfg_down_shift=0;
  logic [10:0] in_group=0;
  logic [127:0] norm_activations=0;
  logic [255:0] gate_weight_signs=0,up_weight_signs=0;
  wire cfg_ready,in_ready,out_valid,out_last,out_error,out_fallback,req_valid,rsp_ready;
  wire [31:0] out_tag;
  wire [15:0] out_start;
  wire [7:0] out_count;
  wire [5119:0] out_data;
  wire [63:0] req_address;
  wire [4:0] req_length;
  logic rsp_valid=0,rsp_last=0,rsp_error=0;
  logic [63:0] rsp_data=0;
  wire pred_valid,pred_ready,pred_last,pred_error;
  wire [5:0] pred_count;
  wire [511:0] pred_channels;
  wire [255:0] pred_lane_enable;
  int core_instances=0,cluster_instances=0,weight_mask_memories=0,activation_memories=0,result_memories=0;
  byte unsigned activations[HIDDEN],gate_weights[SELECTED*HIDDEN],up_weights[SELECTED*HIDDEN];
  byte unsigned down_weights[OUTPUTS*DENSE],skipped[SELECTED];
  logic [15:0] normalized[HIDDEN],groups[2];
  logic [31:0] expected[OUTPUTS],configuration[5];
  int cycle=0,seen=0,total_seen=0,packets=0,success_stalls=0,requests=0;
  int beat=0,length=0,kind=0,output_wait=0,reset_releases=0;
  int activation_reads=0,gate_reads=0,up_reads=0,down_reads=0,pred_packets=0,pred_channels_seen=0;
  int frame_index=0,output_origin=0;
  int expected_kept[SELECTED],expected_kept_count=0;
  logic [31:0] expected_tag=0;
  bit memory_active=0,request_held=0,held=0,frame_done=0;
  logic [63:0] address=0;
  logic [68:0] held_request=0;
  logic [5178:0] held_output=0;
  string first_fixture,ordinary_fixture;
  wire req_ready=!memory_active && !rsp_valid && cycle%4!=0;
  wire out_ready=output_wait>=4 && cycle%19>=9;

  tri_oracle_predicted_dispatch predictor (
    .clk(clk),.rst_n(rst_n),.in_valid(in_valid),.in_last(in_last),.in_group_last(in_group_last),
    .in_frame_error(1'b0),.out_ready(pred_ready),.in_group(in_group),
    .norm_activations(norm_activations),.gate_weight_signs(gate_weight_signs),
    .up_weight_signs(up_weight_signs),.in_ready(in_ready),.out_valid(pred_valid),
    .out_last(pred_last),.out_error(pred_error),.out_count(pred_count),
    .out_channels(pred_channels),.out_lane_enable(pred_lane_enable));
  tri_oracle_feedforward_frame dut (
    .clk(clk),.rst_n(rst_n),.cfg_valid(cfg_valid),.cfg_ready(cfg_ready),.cfg_tag(cfg_tag),
    .cfg_activation_base(cfg_activation_base),.cfg_weight_base(cfg_weight_base),
    .cfg_up_weight_base(cfg_up_weight_base),.cfg_down_weight_base(cfg_down_weight_base),
    .cfg_features(cfg_features),.cfg_dense_features(cfg_dense_features),.cfg_output_count(cfg_output_count),
    .cfg_gate_shift(cfg_gate_shift),.cfg_up_shift(cfg_up_shift),.cfg_down_shift(cfg_down_shift),
    .in_valid(pred_valid),.in_last(pred_last),.in_fallback(1'b0),.in_ready(pred_ready),
    .in_count({2'b0,pred_count}),.in_channels({2048'b0,pred_channels}),
    .out_valid(out_valid),.out_ready(out_ready),.out_last(out_last),.out_error(out_error),
    .out_fallback(out_fallback),.out_tag(out_tag),.out_start(out_start),.out_count(out_count),
    .out_data(out_data),.req_valid(req_valid),.req_ready(req_ready),.req_address(req_address),
    .req_length(req_length),.rsp_valid(rsp_valid),.rsp_last(rsp_last),.rsp_error(rsp_error),
    .rsp_ready(rsp_ready),.rsp_data(rsp_data));

  function automatic int local_channel(input int original);
    for(int group=0;group<2;group++)
      if(original/32==int'(groups[group])) return group*32+original%32;
    return -1;
  endfunction

  always @(posedge rst_n) reset_releases++;
  always @(posedge clk) begin: memory_peer
    logic [63:0] offset,base;
    int incoming_kind,row,local_row,column;
    bit block_has_selected;
    if(!rst_n) begin cycle<=0;memory_active<=0;rsp_valid<=0;request_held=0;end
    else begin
      if($isunknown({cfg_ready,in_ready,pred_ready,pred_valid,out_valid,req_valid,rsp_ready}))
        $fatal(1,"FORMAT351_UNKNOWN_PROTOCOL");
      cycle<=cycle+1;
      if(out_valid && (memory_active || rsp_valid)) $fatal(1,"FORMAT351_RESULT_BEFORE_DRAIN");
      if(request_held && (req_valid!==1 || {req_address,req_length}!==held_request))
        $fatal(1,"FORMAT351_CHANGED_MEMORY_OFFER");
      request_held=req_valid && !req_ready;held_request={req_address,req_length};
      if(req_valid && req_ready) begin
        if(req_length==0 || req_length>16 || req_address[2:0]!=0) $fatal(1,"FORMAT351_BAD_REQUEST");
        incoming_kind=req_address>=UpBase?3:req_address>=GateBase?1:req_address>=ActBase?0:2;
        case(incoming_kind)
          0:begin base=ActBase;activation_reads++;end
          1:begin base=GateBase;gate_reads++;end
          2:begin base=DownBase;down_reads++;end
          3:begin base=UpBase;up_reads++;end
        endcase
        offset=req_address-base;
        if(incoming_kind==0) begin
          if(req_address<base || offset+64'(req_length)*8>HIDDEN) $fatal(1,"FORMAT351_ACTIVATION_RANGE");
        end else if(incoming_kind==2) begin
          row=int'(offset/DENSE);column=int'(offset%DENSE);block_has_selected=0;
          for(int lane=0;lane<8;lane++) begin
            local_row=local_channel(column+lane);
            if(local_row>=0 && skipped[local_row]==0) block_has_selected=1;
          end
          if(req_address<base || req_length!=1 || row<output_origin || row>=output_origin+OUTPUTS ||
             column+8>DENSE || !block_has_selected) $fatal(1,"FORMAT351_DOWN_ORIGINAL_ADDRESS");
        end else begin
          row=int'(offset/HIDDEN);local_row=local_channel(row);
          if(req_address<base || local_row<0 || offset%HIDDEN+64'(req_length)*8>HIDDEN)
            $fatal(1,"FORMAT351_PROJECTION_ORIGINAL_ADDRESS");
          if(skipped[local_row]!=0) $fatal(1,"FORMAT351_FETCHED_SKIPPED_CHANNEL");
        end
        address<=req_address;length<=int'(req_length);beat<=0;kind<=incoming_kind;memory_active<=1;requests++;
      end
      if(memory_active && !rsp_valid && cycle%3!=0) begin
        rsp_valid<=1;rsp_last<=beat==length-1;
        for(int lane=0;lane<8;lane++) begin
          case(kind)
            0:rsp_data[lane*8+:8]<=activations[int'(address-ActBase)+beat*8+lane];
            1:rsp_data[lane*8+:8]<=gate_weights[local_channel(int'((address-GateBase)/HIDDEN))*HIDDEN+int'((address-GateBase)%HIDDEN)+beat*8+lane];
            2:rsp_data[lane*8+:8]<=down_weights[int'(address-DownBase)-output_origin*DENSE+beat*8+lane];
            3:rsp_data[lane*8+:8]<=up_weights[local_channel(int'((address-UpBase)/HIDDEN))*HIDDEN+int'((address-UpBase)%HIDDEN)+beat*8+lane];
          endcase
        end
      end
      if(rsp_valid && rsp_ready) begin rsp_valid<=0;beat<=beat+1;if(rsp_last) memory_active<=0;end
    end
  end

  always @(posedge clk) begin: scoreboards
    int retained,remaining;
    logic [31:0] golden;
    if(!rst_n) begin held=0;output_wait<=0;end
    else begin
      if(out_valid && !out_ready) output_wait<=output_wait+1;
      if(out_valid && out_ready) output_wait<=0;
      if(held && (!out_valid || {out_last,out_error,out_fallback,out_tag,out_start,out_count,out_data}!==held_output))
        $fatal(1,"FORMAT351_STALLED_OUTPUT_CHANGED");
      if(out_valid && !out_ready) begin
        held_output={out_last,out_error,out_fallback,out_tag,out_start,out_count,out_data};success_stalls++;
      end
      held=out_valid && !out_ready;
      if(pred_valid && pred_ready) begin
        remaining=expected_kept_count-pred_channels_seen;retained=remaining>32?32:remaining;
        if(pred_packets>expected_kept_count/32 || pred_error!==0 || pred_last!==(remaining<32))
          $fatal(1,"FORMAT351_PREDICTION_METADATA");
        for(int lane=0;lane<retained;lane++)
          if(pred_channels[lane*16+:16]!==16'(expected_kept[pred_channels_seen+lane]))
            $fatal(1,"FORMAT351_PREDICTION_ORIGINAL_ID");
        if(pred_count!==6'(retained)) $fatal(1,"FORMAT351_PREDICTION_COUNT");
        for(int lane=0;lane<32;lane++)
          if(pred_lane_enable[lane*8+:8]!==(lane<retained?8'hff:8'h00) ||
             (lane>=retained && pred_channels[lane*16+:16]!==0)) $fatal(1,"FORMAT351_PREDICTION_PADDING");
        pred_channels_seen+=retained;pred_packets++;
      end
      if(out_valid && out_ready) begin
        if(frame_done || out_tag!==expected_tag || out_error!==0 || out_fallback!==0 ||
           out_start!==0 || out_count!==8'(OUTPUTS) || out_last!==1) $fatal(1,"FORMAT351_OUTPUT_METADATA");
        for(int row=0;row<160;row++) begin
          golden=row<OUTPUTS?expected[row]:0;
          if($test$plusargs("CORRUPT_SECOND_REFERENCE") && frame_index==1 && row==0) golden=golden^1;
          if(out_data[row*32+:32]!==golden)
            $fatal(1,"FORMAT351_INTEGER_OUTPUT frame=%0d row=%0d got=%0d expected=%0d",frame_index,row,$signed(out_data[row*32+:32]),$signed(golden));
        end
        seen+=OUTPUTS;total_seen+=OUTPUTS;packets++;frame_done=1;
      end
    end
  end

  task automatic run_frame(input string fixture,input int number);
    $readmemh({fixture,"/activation.hex"},activations);$readmemh({fixture,"/norm.hex"},normalized);
    $readmemh({fixture,"/gate.hex"},gate_weights);$readmemh({fixture,"/up.hex"},up_weights);
    $readmemh({fixture,"/down.hex"},down_weights);$readmemh({fixture,"/skip.hex"},skipped);
    $readmemh({fixture,"/expected.hex"},expected);$readmemh({fixture,"/groups.hex"},groups);
    $readmemh({fixture,"/configuration.hex"},configuration);
    if(configuration[0]>63 || configuration[1]>63 || configuration[2]>63 ||
       configuration[3]+OUTPUTS>HIDDEN || configuration[4]!==OUTPUTS || groups[0]>=groups[1] || groups[1]>=176)
      $fatal(1,"FORMAT351_FIXTURE_CONFIGURATION");
    frame_index=number;output_origin=int'(configuration[3]);expected_tag=32'h35100000+32'(number);
    seen=0;packets=0;success_stalls=0;requests=0;activation_reads=0;gate_reads=0;up_reads=0;down_reads=0;
    pred_packets=0;pred_channels_seen=0;frame_done=0;expected_kept_count=0;
    for(int row=0;row<SELECTED;row++) begin
      if(skipped[row]>1) $fatal(1,"FORMAT351_SKIP_ENCODING");
      if(skipped[row]==0) begin
        expected_kept[expected_kept_count]=int'(groups[row/32])*32+row%32;expected_kept_count++;
      end
    end
    @(negedge clk);while(!cfg_ready) @(negedge clk);
    cfg_tag=expected_tag;cfg_activation_base=ActBase;cfg_weight_base=GateBase;cfg_up_weight_base=UpBase;
    cfg_down_weight_base=DownBase+64'(output_origin)*DENSE;
    cfg_features=HIDDEN/8;cfg_dense_features=DENSE;cfg_output_count=OUTPUTS;
    cfg_gate_shift=6'(configuration[0]);cfg_up_shift=6'(configuration[1]);cfg_down_shift=6'(configuration[2]);
    if(($test$plusargs("WRONG_FIRST_UP") && number==0) || ($test$plusargs("WRONG_SECOND_UP") && number==1))
      cfg_up_shift=cfg_up_shift+6'd1;
    if($test$plusargs("WRONG_SECOND_DOWN") && number==1) cfg_down_shift=cfg_down_shift+6'd1;
    cfg_valid=1;@(posedge clk);if(!cfg_ready) $fatal(1,"FORMAT351_CONFIG_NOT_ACCEPTED");
    @(negedge clk);cfg_valid=0;cfg_tag='1;cfg_activation_base=0;cfg_weight_base=0;cfg_up_weight_base=0;
    cfg_down_weight_base=0;cfg_features=0;cfg_dense_features=0;cfg_output_count=0;
    cfg_gate_shift='1;cfg_up_shift='1;cfg_down_shift='1;
    for(int group=0;group<2;group++) begin
      for(int strip=0;strip<HIDDEN/8;strip++) begin
        @(negedge clk);in_valid=1;in_last=strip==HIDDEN/8-1;in_group=11'(groups[group]);in_group_last=group==1;
        for(int lane=0;lane<8;lane++) begin
          norm_activations[lane*16+:16]=normalized[strip*8+lane];
          for(int row=0;row<32;row++) begin
            gate_weight_signs[row*8+lane]=gate_weights[(group*32+row)*HIDDEN+strip*8+lane][7];
            up_weight_signs[row*8+lane]=up_weights[(group*32+row)*HIDDEN+strip*8+lane][7];
          end
        end
        @(posedge clk);while(!in_ready) @(posedge clk);
        @(negedge clk);in_valid=0;in_group='1;norm_activations='1;gate_weight_signs='1;up_weight_signs='1;
      end
    end
    wait(frame_done);@(negedge clk);
    if(seen!=OUTPUTS || packets!=1 || pred_packets!=expected_kept_count/32+1 || pred_channels_seen!=expected_kept_count || success_stalls==0 ||
       activation_reads==0 || gate_reads==0 || up_reads==0 || down_reads==0 || memory_active || rsp_valid || reset_releases!=1)
      $fatal(1,"FORMAT351_FRAME_INVENTORY");
    $display("FORMAT351_FRAME_PASS frame=%0d outputs=%0d retained=%0d stalls=%0d requests=%0d original_output=%0d",number,seen,pred_channels_seen,success_stalls,requests,output_origin);
  endtask

  initial begin
    if(!$value$plusargs("FIRST_FIXTURE=%s",first_fixture) || !$value$plusargs("ORDINARY_FIXTURE=%s",ordinary_fixture))
      $fatal(1,"FORMAT351_FIXTURES_REQUIRED");
    repeat(3) @(negedge clk);
    if(core_instances!=20 || cluster_instances!=5 || weight_mask_memories!=360 || activation_memories!=40 || result_memories!=200)
      $fatal(1,"FORMAT351_ACTUAL_HIERARCHY");
    $display("FORMAT351_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=600");rst_n=1;
    run_frame(first_fixture,0);run_frame(ordinary_fixture,1);
    if(total_seen!=70 || reset_releases!=1) $fatal(1,"FORMAT351_PAIR_INVENTORY");
    $display("FORMAT351_PAIR_PASS outputs=70 frames=2 external_reset_releases=1 cycles=%0d",cycle);$finish;
  end
  initial begin #(64'd20000000);$fatal(1,"FORMAT351_WATCHDOG");end
endmodule

module tri_oracle_format351_instance_count #(parameter int KIND=0) ();
  initial case(KIND)
    0:$root.tri_oracle_predicted_feedforward_frame_tb.core_instances++;
    1:$root.tri_oracle_predicted_feedforward_frame_tb.cluster_instances++;
    2:$root.tri_oracle_predicted_feedforward_frame_tb.weight_mask_memories++;
    3:$root.tri_oracle_predicted_feedforward_frame_tb.activation_memories++;
    4:$root.tri_oracle_predicted_feedforward_frame_tb.result_memories++;
  endcase
endmodule
bind tri_oracle_sram_memory_compute tri_oracle_format351_instance_count #(.KIND(0)) count_core351 ();
bind tri_oracle_sram_compute_cluster tri_oracle_format351_instance_count #(.KIND(1)) count_cluster351 ();
bind TS5N28HPCPSVTA32X128M2FW tri_oracle_format351_instance_count #(.KIND(2)) count_weight351 ();
bind TS5N28HPCPSVTA512X64M4F tri_oracle_format351_instance_count #(.KIND(3)) count_activation351 ();
bind TS6N28HPCPSVTA16X128M2F tri_oracle_format351_instance_count #(.KIND(4)) count_result351 ();
