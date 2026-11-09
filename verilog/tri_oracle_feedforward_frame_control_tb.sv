`timescale 1ns/1ps

// Control-contract test only. The deterministic peer below replaces arithmetic;
// actual600-memory integration is a separate mandatory qualification.
module tri_oracle_feedforward_frame_control_tb;
  logic clk=0;always #5 clk=~clk;
  logic rst_n=0,cfg_valid=0,cfg_ready,in_valid=0,in_ready,in_last=0,in_fallback=0,out_ready;
  logic [31:0] cfg_tag=0;
  logic [63:0] cfg_activation_base=0,cfg_weight_base=0,cfg_up_weight_base=0,cfg_down_weight_base=0;
  logic [9:0] cfg_features=0;
  logic [16:0] cfg_dense_features=0;
  logic [15:0] cfg_output_count=0;
  logic [5:0] cfg_gate_shift=0,cfg_up_shift=0,cfg_down_shift=0;
  logic [7:0] in_count=0;
  logic [2559:0] in_channels=0;
  wire out_valid,out_last,out_error,out_fallback,req_valid,rsp_ready;
  wire [31:0] out_tag;
  wire [15:0] out_start;
  wire [7:0] out_count;
  wire [5119:0] out_data;
  wire [63:0] req_address;
  wire [4:0] req_length;
  logic req_ready=1,rsp_valid=0,rsp_last=0,rsp_error=0;
  logic [63:0] rsp_data=0;
  int cycle=0,completed=0,frame_outputs=0,frame_dense=0,frame_features=0,frame_shift=0,seen=0,prefixes=0;
  int gate_accepts=0,down_accepts=0;
  int successful_stall_cycles=0,error_stall_cycles=0;
  bit was_stalled=0;
  logic [5178:0] held_output=0;
  logic [31:0] frame_tag=0;
  bit expect_error=0,frame_done=0,frame_fallback=0,inject_late_error=0;
  int golden[2400];
  tri_oracle_feedforward_frame dut(.*);
  always_comb out_ready=cycle%19>=9;
  function automatic int code(input int channel);return channel%31-15;endfunction
  function automatic int quant(input int value,shift);
    real scaled;int rounded;
    scaled=real'(value)/(2.0**shift);
    rounded=scaled>=0.0?$rtoi(scaled+0.5):-$rtoi(-scaled+0.5);
    return rounded>127?127:rounded < -128?-128:rounded;
  endfunction
  function automatic int weight(input int row,column);return (row*3+column*7)%255-127;endfunction
  always @(posedge clk) begin: scoreboard
    int amount,value;
    cycle<=cycle+1;
    if(!rst_n) was_stalled=0;
    else begin
      if(was_stalled && (!out_valid ||
          {out_last,out_error,out_fallback,out_tag,out_start,out_count,out_data}!==held_output))
        $fatal(1,"FRAME_CONTROL_STALLED_PACKET_CHANGED");
      if(out_valid && !out_ready) begin
        if(out_error) error_stall_cycles++;else successful_stall_cycles++;
        held_output={out_last,out_error,out_fallback,out_tag,out_start,out_count,out_data};
        if($test$plusargs("CORRUPT_HELD_REFERENCE")) held_output[0]=!held_output[0];
      end
      was_stalled=out_valid && !out_ready;
    end
    if(rst_n && out_valid && out_ready) begin
      if(out_tag!==frame_tag) $fatal(1,"FRAME_CONTROL_TAG");
      if(out_error) begin
        if(!expect_error || !out_last || out_count!==0 || out_start!==0 || out_fallback!==0 || out_data!==0)
          $fatal(1,"FRAME_CONTROL_ERROR_PACKET");
        if(dut.engine.valid_slots!==0) $fatal(1,"FRAME_CONTROL_CONTEXTS_SURVIVED_ERROR");
        frame_done=1;completed++;
      end else begin
        if(seen>=frame_outputs || out_start!==16'(seen)) $fatal(1,"FRAME_CONTROL_OUTPUT_ORDER");
        amount=frame_outputs-seen>160?160:frame_outputs-seen;
        if(out_count!==8'(amount) || out_last!==(seen+amount==frame_outputs) || out_fallback!==frame_fallback)
          $fatal(1,"FRAME_CONTROL_OUTPUT_SHAPE");
        for(int row=0;row<160;row++) begin
          value=row<amount?golden[seen+row]:0;
          if($test$plusargs("CORRUPT_FRAME_REFERENCE") && row==0) value++;
          if(out_data[row*32+:32]!==32'(value)) $fatal(1,"FRAME_CONTROL_SUM row=%0d",seen+row);
        end
        seen+=amount;prefixes++;
        if(out_last) begin
          if(expect_error) $fatal(1,"FRAME_CONTROL_EXPECTED_ERROR");
          frame_done=1;completed++;
        end
      end
      $display("FRAME_CONTROL_PACKET tag=%h error=%b seen=%0d",out_tag,out_error,seen);$fflush();
    end
    if(rst_n && req_valid) $fatal(1,"CONTROL_TEST_PEER_UNEXPECTED_MEMORY");
  end

  task automatic configure(input int outputs,dense,features,input bit error_expected=0,input int bad=0);
    begin
      @(negedge clk);while(!cfg_ready) @(negedge clk);
      frame_outputs=outputs;frame_dense=dense;frame_features=features;frame_shift=completed%3;
      frame_tag=32'h95000000+32'(completed);expect_error=error_expected;frame_done=0;frame_fallback=0;
      seen=0;prefixes=0;gate_accepts=0;down_accepts=0;inject_late_error=0;
      for(int row=0;row<2400;row++) golden[row]=0;
      cfg_tag=frame_tag;cfg_output_count=16'(outputs);cfg_dense_features=17'(dense);cfg_features=10'(features);
      cfg_activation_base=64'h1000;cfg_weight_base=64'h100000;cfg_up_weight_base=64'h200000;cfg_down_weight_base=64'h300000;
      cfg_gate_shift=7;cfg_up_shift=12;cfg_down_shift=6'(frame_shift);
      if(bad==1) cfg_up_weight_base=64'h200001;
      if(bad==2) cfg_down_weight_base=64'hfffffffffffffff8;
      cfg_valid=1;@(posedge clk);if(!cfg_ready) $fatal(1,"FRAME_CONTROL_CONFIG_NOT_ACCEPTED");
      @(negedge clk);cfg_valid=0;cfg_tag='1;cfg_output_count=0;cfg_dense_features=0;cfg_features=0;
      cfg_activation_base=0;cfg_weight_base=0;cfg_up_weight_base=0;cfg_down_weight_base=0;
      cfg_gate_shift=0;cfg_up_shift=0;cfg_down_shift=0;
    end
  endtask
  task automatic packet(input int count,salt,input bit last,fallback=0,bad_id=0);
    int channel;
    begin
      @(negedge clk);while(!in_ready) @(negedge clk);
      in_count=8'(count);in_last=last;in_fallback=fallback;in_channels=0;frame_fallback|=fallback;
      for(int i=0;i<count && i<160;i++) begin
        channel=bad_id?frame_dense:(salt*173+i*37)%frame_dense;
        in_channels[i*16+:16]=16'(channel);
        for(int row=0;row<frame_outputs && row<2400;row++)
          golden[row]+=quant(code(channel),frame_shift)*weight(row,channel);
      end
      in_valid=1;@(posedge clk);if(!in_ready) $fatal(1,"FRAME_CONTROL_PACKET_NOT_ACCEPTED");
      @(negedge clk);in_valid=0;in_channels='1;in_count='1;in_last=!last;in_fallback=!fallback;
    end
  endtask
  task automatic finish_frame(input int expected_gates=-1,expected_down=-1);
    int timeout;
    begin
      timeout=0;while(!frame_done && timeout<30000) begin @(negedge clk);timeout++;end
      if(!frame_done) $fatal(1,"FRAME_CONTROL_COMPLETION_TIMEOUT");
      if(expected_gates>=0 && gate_accepts!=expected_gates) $fatal(1,"FRAME_CONTROL_GATE_COUNT got=%0d expected=%0d",gate_accepts,expected_gates);
      if(expected_down>=0 && down_accepts!=expected_down) $fatal(1,"FRAME_CONTROL_DOWN_COUNT got=%0d expected=%0d",down_accepts,expected_down);
    end
  endtask
  initial begin
    repeat(3) @(negedge clk);rst_n=1;
    configure(2048,5632,256);packet(160,1,0,1);packet(33,2,1);finish_frame(2,91);
    configure(161,64,3);packet(33,1,1);finish_frame(1,4);
    configure(1,8,1);packet(0,0,1);finish_frame(1,1);
    configure(2400,32,1);packet(0,0,0);packet(0,0,1);finish_frame(2,30);
    configure(320,256,3);packet(32,1,0);packet(0,0,1);finish_frame(2,4);
    configure(0,64,3,1);finish_frame(0,0);
    configure(2401,64,3,1);finish_frame(0,0);
    configure(160,64,0,1);finish_frame(0,0);
    configure(160,7,3,1);finish_frame(0,0);
    configure(160,64,3,1,1);finish_frame(0,0);
    configure(160,64,3,1,2);finish_frame(0,0);
    configure(160,5632,3,1);packet(161,1,1);finish_frame(0,0);
    configure(160,64,3,1);packet(1,1,1,0,1);finish_frame(0,0);
    configure(160,8,3,1);packet(9,1,1);finish_frame(0,0);
    configure(480,64,3,1);inject_late_error=1;packet(32,1,0);packet(32,2,1);finish_frame();
    if(prefixes!=1) $fatal(1,"FRAME_CONTROL_LATE_ERROR_PREFIX_NOT_EXERCISED");
    configure(2048,64,3);packet(32,1,1);wait(dut.engine.pending);
    @(negedge clk);rst_n=0;repeat(3) @(negedge clk);rst_n=1;
    configure(129,64,3);packet(3,1,1);finish_frame(1,1);
    if(completed!=16) $fatal(1,"FRAME_CONTROL_CASE_INVENTORY");
    if(successful_stall_cycles<9 || error_stall_cycles<9) $fatal(1,"FRAME_CONTROL_STALL_COVERAGE");
    $display("FRAME_CONTROL_STALLS success=%0d error=%0d",successful_stall_cycles,error_stall_cycles);
    $display("FRAME_CONTROL_PASS cases=%0d mock_arithmetic_only=1",completed);$finish;
  end
  initial begin #5000000;$fatal(1,"FRAME_CONTROL_WATCHDOG");end
endmodule

// Deterministic protocol peer; not the actual accelerator.
module tri_oracle_gated_down_fabric (
    input logic clk,rst_n,in_valid,in_is_down,in_last,in_fallback,in_accumulate,out_ready,
    input logic [31:0] in_tag,
    input logic [2559:0] in_channels,
    input logic [1023:0] in_data,
    input logic [7:0] in_count,in_output_count,
    input logic [63:0] in_activation_base,in_weight_base,in_up_weight_base,
    input logic [9:0] in_features,
    input logic [16:0] in_dense_features,
    input logic [15:0] in_output_start,
    input logic [5:0] in_shift,in_gate_shift,in_up_shift,
    input logic [3:0] in_slot,
    output logic in_ready,out_valid,out_is_down,out_last,out_fallback,out_error,
    output logic [31:0] out_tag,
    output logic [7:0] out_count,
    output logic [2559:0] out_channels,
    output logic [5119:0] out_data,
    output logic [15:0] out_start,
    output logic [3:0] out_slot,
    output logic req_valid,
    input logic req_ready,
    output logic [63:0] req_address,
    output logic [4:0] req_length,
    input logic rsp_valid,rsp_last,rsp_error,
    output logic rsp_ready,
    input logic [63:0] rsp_data
);

  int cycle=0,delay_count=0;
  logic pending=0;
  logic [15:0] valid_slots=0;
  logic [31:0] tags[16];
  logic [15:0] starts[16];
  logic [7:0] counts[16];
  int sums[16][160];
  always_comb begin
    in_ready=rst_n && !pending && !out_valid && cycle%3!=0;
    req_valid=0;req_address=0;req_length=0;rsp_ready=0;
  end
  function automatic int quant(input int value,input int shift);
    real scaled;int rounded;
    scaled=real'(value)/(2.0**shift);rounded=scaled>=0.0?$rtoi(scaled+0.5):-$rtoi(-scaled+0.5);
    return rounded>127?127:rounded < -128?-128:rounded;
  endfunction
  function automatic int weight(input int row,column);return (row*3+column*7)%255-127;endfunction
  always @(posedge clk or negedge rst_n) begin: model
    int amount,value;
    bit error_now;
    if(!rst_n) begin
      cycle<=0;pending<=0;out_valid<=0;valid_slots<=0;out_data<=0;out_error<=0;
      out_last<=0;out_fallback<=0;out_tag<=0;out_count<=0;out_channels<=0;out_start<=0;out_slot<=0;out_is_down<=0;delay_count<=0;
    end else begin
      cycle<=cycle+1;
      if(out_valid && out_ready) out_valid<=0;
      if(pending) begin
        if(delay_count==0) begin pending<=0;out_valid<=1;end
        else delay_count<=delay_count-1;
      end
      if(in_valid && in_ready) begin
        if(in_tag!==$root.tri_oracle_feedforward_frame_control_tb.frame_tag) $fatal(1,"PEER_CAPTURED_FRAME_TAG");
        pending<=1;delay_count<=cycle%4+1;out_tag<=in_tag;out_is_down<=in_is_down;
        out_last<=in_last;out_fallback<=!in_is_down && in_fallback;out_error<=0;out_data<=0;
        out_channels<=in_is_down?2560'b0:in_channels;out_start<=in_is_down?in_output_start:16'b0;out_slot<=in_is_down?in_slot:4'b0;
        if(!in_is_down) begin
          if(in_activation_base!==64'h1000 || in_weight_base!==64'h100000 || in_up_weight_base!==64'h200000 ||
             in_features!==10'($root.tri_oracle_feedforward_frame_control_tb.frame_features) || in_gate_shift!==7 || in_up_shift!==12)
            $fatal(1,"PEER_CAPTURED_GATED_CONFIGURATION");
          $root.tri_oracle_feedforward_frame_control_tb.gate_accepts++;
          out_count<=in_count;
          for(int row=0;row<160;row++) if(row<int'(in_count)) out_data[row*32+:32]<=32'(int'(in_channels[row*16+:16])%31-15);
        end else begin
          if(in_weight_base!==64'h300000 || in_dense_features!==17'($root.tri_oracle_feedforward_frame_control_tb.frame_dense) ||
             in_shift!==6'($root.tri_oracle_feedforward_frame_control_tb.frame_shift) || in_count>32 ||
             in_output_start%160!=0 || in_slot!=in_output_start/160+1) $fatal(1,"PEER_CAPTURED_DOWN_CONFIGURATION");
          amount=$root.tri_oracle_feedforward_frame_control_tb.frame_outputs-int'(in_output_start);
          if(amount>160) amount=160;
          if(in_output_count!==8'(amount)) $fatal(1,"PEER_WRONG_OUTPUT_RANGE");
          $root.tri_oracle_feedforward_frame_control_tb.down_accepts++;
          error_now=(in_accumulate && (!valid_slots[in_slot] || tags[in_slot]!=in_tag || starts[in_slot]!=in_output_start || counts[in_slot]!=in_output_count)) ||
              ($root.tri_oracle_feedforward_frame_control_tb.inject_late_error && in_last && in_output_start==160);
          if(error_now) begin
            valid_slots<=0;out_error<=1;out_last<=1;out_count<=0;out_data<=0;
          end else begin
            for(int row=0;row<160;row++) if(row<int'(in_output_count)) begin
              value=in_accumulate?sums[in_slot][row]:0;
              for(int i=0;i<int'(in_count);i++)
                value+=quant($signed(in_data[i*32+:32]),int'(in_shift))*weight(int'(in_output_start)+row,int'(in_channels[i*16+:16]));
              sums[in_slot][row]=value;out_data[row*32+:32]<=32'(value);
            end
            valid_slots[in_slot]<=!in_last;tags[in_slot]<=in_tag;starts[in_slot]<=in_output_start;counts[in_slot]<=in_output_count;
            out_count<=in_output_count;
          end
        end
      end
    end
  end
endmodule
