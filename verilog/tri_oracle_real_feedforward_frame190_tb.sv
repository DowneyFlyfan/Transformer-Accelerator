`timescale 1ns/1ps
// This alternative bench uses the same top name so the qualified source and
// mapped bundles can substitute only their stimulus. Compile one bench at a time.
// One complete trained first-layer feed-forward fixture; no model-accuracy claim.
module tri_oracle_predicted_feedforward_frame_tb;
  localparam int HIDDEN = 2048;
  localparam int INTERMEDIATE = 5632;
  localparam int OUTPUTS = 2048;
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
  int core_instances=0,cluster_instances=0,weight_mask_memories=0,activation_memories=0,result_memories=0;
  byte unsigned activations[HIDDEN],gate_weights[INTERMEDIATE*HIDDEN],up_weights[INTERMEDIATE*HIDDEN];
  byte unsigned down_weights[OUTPUTS*INTERMEDIATE];
  logic [15:0] normalized[HIDDEN];
  logic [31:0] expected[OUTPUTS],configuration[5];
  int cycle=0,seen=0,packets=0,success_stalls=0,requests=0,groups_sent=0,strips_sent=0;
  int beat=0,length=0,kind=0,progress_file=0;
  int activation_reads=0,gate_reads=0,up_reads=0,down_reads=0;
  int prediction_channels_seen,prediction_packets_seen;
  bit prediction_done;
  bit memory_active=0,request_held=0,held=0,frame_done=0;
  logic [63:0] address=0;
  logic [68:0] held_request=0;
  logic [5178:0] held_output=0;
  string fixture,progress_path;
  wire req_ready=!memory_active && !rsp_valid && cycle%4!=0;
  wire out_ready=cycle%19>=9;
  tri_oracle_predicted_feedforward_frame dut(.*);
  tri_oracle_real_channel_sequence190_monitor prediction_monitor (
      .clk(clk),.rst_n(rst_n),.packet_valid(dut.packet_valid),.packet_ready(dut.packet_ready),
      .packet_last(dut.packet_last),.packet_error(dut.packet_error),.packet_fallback(dut.packet_fallback),
      .packet_tag(dut.packet_tag),.packet_count(dut.packet_count),.packet_channels(dut.packet_channels),
      .channels_seen(prediction_channels_seen),.packets_seen(prediction_packets_seen),.done(prediction_done));

  always @(posedge clk) begin: memory_peer
    logic [63:0] offset,base;
    int incoming_kind;
    if(!rst_n) begin cycle<=0;memory_active<=0;rsp_valid<=0;request_held=0;end
    else begin
      if($isunknown({cfg_ready,in_ready,out_valid,req_valid,rsp_ready}))
        $fatal(1,"REAL_FRAME_UNKNOWN_PROTOCOL");
      cycle<=cycle+1;
      if(out_valid && (memory_active || rsp_valid)) $fatal(1,"REAL_FRAME_RESULT_BEFORE_DRAIN");
      if(request_held && (req_valid!==1 || {req_address,req_length}!==held_request))
        $fatal(1,"REAL_FRAME_CHANGED_MEMORY_OFFER");
      request_held=req_valid && !req_ready;held_request={req_address,req_length};
      if(req_valid && req_ready) begin
        if(req_length==0 || req_length>16 || req_address[2:0]!=0) $fatal(1,"REAL_FRAME_BAD_REQUEST");
        incoming_kind=req_address>=UpBase?3:req_address>=GateBase?1:req_address>=ActBase?0:2;
        case(incoming_kind)
          0: begin base=ActBase; activation_reads++; end
          1: begin base=GateBase; gate_reads++; end
          2: begin base=DownBase; down_reads++; end
          3: begin base=UpBase; up_reads++; end
        endcase
        offset=req_address-base;
        if(incoming_kind==0) begin
          if(req_address<base || offset+64'(req_length)*8>HIDDEN) $fatal(1,"REAL_FRAME_ACTIVATION_RANGE");
        end else if(incoming_kind==2) begin
          if(req_address<base || req_length!=1 || offset+8>OUTPUTS*INTERMEDIATE)
            $fatal(1,"REAL_FRAME_DOWN_RANGE");
        end else if(req_address<base || offset+64'(req_length)*8>INTERMEDIATE*HIDDEN ||
                    offset%HIDDEN+64'(req_length)*8>HIDDEN)
          $fatal(1,"REAL_FRAME_PROJECTION_RANGE");
        address<=req_address;length<=int'(req_length);beat<=0;kind<=incoming_kind;memory_active<=1;requests++;
      end
      if(memory_active && !rsp_valid && cycle%3!=0) begin
        rsp_valid<=1;rsp_last<=beat==length-1;
        for(int lane=0;lane<8;lane++) begin
          case(kind)
            0:rsp_data[lane*8+:8]<=activations[int'(address-ActBase)+beat*8+lane];
            1:rsp_data[lane*8+:8]<=gate_weights[int'(address-GateBase)+beat*8+lane];
            2:rsp_data[lane*8+:8]<=down_weights[int'(address-DownBase)+beat*8+lane];
            3:rsp_data[lane*8+:8]<=up_weights[int'(address-UpBase)+beat*8+lane];
          endcase
        end
      end
      if(rsp_valid && rsp_ready) begin rsp_valid<=0;beat<=beat+1;if(rsp_last) memory_active<=0;end
    end
  end

  always @(posedge clk) begin: scoreboard
    int amount;
    logic [31:0] golden;
    if(!rst_n) held=0;
    else begin
      if(held && (!out_valid || {out_last,out_error,out_fallback,out_tag,out_start,out_count,out_data}!==held_output))
        $fatal(1,"REAL_FRAME_STALLED_OUTPUT_CHANGED");
      if(out_valid && !out_ready) begin
        held_output={out_last,out_error,out_fallback,out_tag,out_start,out_count,out_data};success_stalls++;
      end
      held=out_valid && !out_ready;
    end
    if(rst_n && out_valid && out_ready) begin
      if(frame_done || out_tag!==32'h19001234 || out_error!==0 || out_fallback!==0)
        $fatal(1,"REAL_FRAME_METADATA");
      amount=OUTPUTS-seen>160?160:OUTPUTS-seen;
      if(out_start!==16'(seen) || out_count!==8'(amount) || out_last!==(seen+amount==OUTPUTS))
        $fatal(1,"REAL_FRAME_OUTPUT_SHAPE");
      for(int row=0;row<160;row++) begin
        golden=row<amount?expected[seen+row]:0;
        if($test$plusargs("CORRUPT_REAL_REFERENCE") && seen==0 && row==0) golden=golden^1;
        if(out_data[row*32+:32]!==golden)
          $fatal(1,"REAL_FRAME_INTEGER_OUTPUT row=%0d got=%0d expected=%0d",seen+row,$signed(out_data[row*32+:32]),$signed(golden));
      end
      seen+=amount;packets++;
      if(progress_file) begin
        $fdisplay(progress_file,"REAL_FRAME_OUTPUT time=%0t outputs=%0d packets=%0d requests=%0d",$time,seen,packets,requests);
        $fflush(progress_file);
      end
      if(out_last) frame_done=1;
    end
  end

  // A separate file with an explicit handle provides live progress even when
  // simulator console output is buffered. It observes time and counters only.
  initial forever begin
    #1000000;
    if(progress_file) begin
      $fdisplay(progress_file,"REAL_FRAME_PROGRESS time=%0t cycles=%0d groups=%0d strips=%0d outputs=%0d requests=%0d",
                $time,cycle,groups_sent,strips_sent,seen,requests);
      $fflush(progress_file);
    end
  end

  initial begin
    if(!$value$plusargs("FIXTURE=%s",fixture)) $fatal(1,"REAL_FRAME_FIXTURE_REQUIRED");
    if($value$plusargs("PROGRESS_FILE=%s",progress_path)) begin
      progress_file=$fopen(progress_path,"w");
      if(!progress_file) $fatal(1,"REAL_FRAME_PROGRESS_OPEN");
    end
    $readmemh({fixture,"/activation.hex"},activations);
    $readmemh({fixture,"/gate.hex"},gate_weights);
    $readmemh({fixture,"/up.hex"},up_weights);
    $readmemh({fixture,"/down.hex"},down_weights);
    $readmemh({fixture,"/norm.hex"},normalized);
    $readmemh({fixture,"/expected.hex"},expected);
    $readmemh({fixture,"/configuration.hex"},configuration);
    if(configuration[0]!==6 || configuration[1]!==0 || configuration[2]!==6 ||
       configuration[3]!==0 || configuration[4]!==OUTPUTS) $fatal(1,"REAL_FRAME_CONFIGURATION");
    repeat(3) @(negedge clk);
    if(core_instances!=20 || cluster_instances!=5 || weight_mask_memories!=360 || activation_memories!=40 || result_memories!=200)
      $fatal(1,"REAL_FRAME_ACTUAL_HIERARCHY");
    $display("REAL_FRAME_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=600");rst_n=1;
    @(negedge clk);while(!cfg_ready) @(negedge clk);
    cfg_tag=32'h19001234;cfg_activation_base=ActBase;cfg_weight_base=GateBase;
    cfg_up_weight_base=UpBase;cfg_down_weight_base=DownBase;
    cfg_features=HIDDEN/8;cfg_dense_features=INTERMEDIATE;cfg_output_count=OUTPUTS;
    cfg_gate_shift=6;cfg_up_shift=0;cfg_down_shift=6;
    cfg_valid=1;@(posedge clk);if(!cfg_ready) $fatal(1,"REAL_FRAME_CONFIG_NOT_ACCEPTED");
    @(negedge clk);cfg_valid=0;cfg_tag='1;cfg_activation_base=0;cfg_weight_base=0;
    cfg_up_weight_base=0;cfg_down_weight_base=0;cfg_features=0;cfg_dense_features=0;cfg_output_count=0;
    cfg_gate_shift='1;cfg_up_shift='1;cfg_down_shift='1;
    for(int group=0;group<INTERMEDIATE/32;group++) begin
      for(int strip=0;strip<HIDDEN/8;strip++) begin
        @(negedge clk);in_valid=1;in_last=strip==HIDDEN/8-1;
        in_group=11'(group);in_group_last=group==INTERMEDIATE/32-1;
        for(int lane=0;lane<8;lane++) begin
          norm_activations[lane*16+:16]=normalized[strip*8+lane];
          for(int row=0;row<32;row++) begin
            gate_weight_signs[row*8+lane]=gate_weights[(group*32+row)*HIDDEN+strip*8+lane][7];
            up_weight_signs[row*8+lane]=up_weights[(group*32+row)*HIDDEN+strip*8+lane][7];
          end
        end
        @(posedge clk);while(!in_ready) @(posedge clk);strips_sent++;
        @(negedge clk);in_valid=0;in_group='1;norm_activations='1;gate_weight_signs='1;up_weight_signs='1;
      end
      groups_sent++;
    end
    wait(frame_done);
    if(seen!=OUTPUTS || packets!=13 || groups_sent!=176 || strips_sent!=45056 || success_stalls==0 ||
       !prediction_done || prediction_channels_seen!=5632 || prediction_packets_seen!=36 ||
       activation_reads==0 || gate_reads==0 || up_reads==0 || down_reads==0) $fatal(1,"REAL_FRAME_INVENTORY");
    $display("REAL_FRAME_PASS outputs=%0d packets=%0d groups=%0d strips=%0d channels=%0d prediction_packets=%0d stalls=%0d requests=%0d",
             seen,packets,groups_sent,strips_sent,prediction_channels_seen,prediction_packets_seen,success_stalls,requests);
    if(progress_file) $fclose(progress_file);
    $finish;
  end
  initial begin #(64'd4000000000); $fatal(1,"REAL_FRAME_WATCHDOG"); end
endmodule

module tri_oracle_joined_instance_count #(parameter int KIND=0) ();
  initial begin
    case(KIND)
      0:$root.tri_oracle_predicted_feedforward_frame_tb.core_instances++;
      1:$root.tri_oracle_predicted_feedforward_frame_tb.cluster_instances++;
      2:$root.tri_oracle_predicted_feedforward_frame_tb.weight_mask_memories++;
      3:$root.tri_oracle_predicted_feedforward_frame_tb.activation_memories++;
      4:$root.tri_oracle_predicted_feedforward_frame_tb.result_memories++;
    endcase
  end
endmodule
bind tri_oracle_sram_memory_compute tri_oracle_joined_instance_count #(.KIND(0)) count_joined_core ();
bind tri_oracle_sram_compute_cluster tri_oracle_joined_instance_count #(.KIND(1)) count_joined_cluster ();
bind TS5N28HPCPSVTA32X128M2FW tri_oracle_joined_instance_count #(.KIND(2)) count_joined_weight_mask ();
bind TS5N28HPCPSVTA512X64M4F tri_oracle_joined_instance_count #(.KIND(3)) count_joined_activation ();
bind TS6N28HPCPSVTA16X128M2F tri_oracle_joined_instance_count #(.KIND(4)) count_joined_result ();
