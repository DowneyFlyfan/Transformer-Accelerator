`timescale 1ns/1ps

// Actual twenty-core frame integration. The producer sends selected packets;
// every subgroup/output-round loop executes inside production hardware.
module tri_oracle_feedforward_frame_tb;
  localparam logic [63:0] ActBase=64'h100002000,GateBase=64'h200004000,
                            UpBase=64'h300008000,DownBase=64'h100000;
  logic clk=0;always #5 clk=~clk;
  logic rst_n=0,cfg_valid=0,in_valid=0,in_last=0,in_fallback=0;
  logic [31:0] cfg_tag=0;
  logic [63:0] cfg_activation_base=0,cfg_weight_base=0,cfg_up_weight_base=0,cfg_down_weight_base=0;
  logic [9:0] cfg_features=0;
  logic [16:0] cfg_dense_features=0;
  logic [15:0] cfg_output_count=0;
  logic [5:0] cfg_gate_shift=0,cfg_up_shift=0,cfg_down_shift=0;
  logic [7:0] in_count=0;
  logic [2559:0] in_channels=0;
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
  int cycle=0,completed=0,frame_outputs=0,frame_dense=0,frame_features=0,frame_shift=8;
  int seen=0,prefixes=0,requests=0,salt=0,packet_rows=0,current_phase=0;
  int exact_dots=0,nonlinear_codes=0,checked_hidden_outputs=0,successful_stall_cycles=0,error_stall_cycles=0;
  int gate_accepts=0,down_accepts=0;
  bit expect_error=0,frame_done=0,frame_fallback=0,fault_up=0,fault_down=0,error_fired=0;
  bit memory_active=0,request_held=0,was_stalled=0;
  int beat=0,length=0,memory_kind=0;
  logic [63:0] address=0;
  logic [68:0] held_request=0;
  logic [5178:0] held_output=0;
  logic [31:0] frame_tag=0;
  logic [2559:0] packet_ids=0;
  logic [19:0] active_cores=0;
  longint signed golden[2400],gate_sum[160],up_sum[160];
  wire req_ready=!memory_active && !rsp_valid && cycle%4!=0;
  wire out_ready=cycle%19>=9;
  tri_oracle_feedforward_frame dut(.*);

  function automatic int activation_value(input int feature);
    return (feature*17+salt*11)%256-128;
  endfunction
  function automatic int weight_value(input int channel,feature,phase);
    return phase==0?(channel*7+feature*13+salt*3)%256-128:(channel*11+feature*5+salt*7)%256-128;
  endfunction
  function automatic int down_weight(input int row,column);return (row*3+column*7)%255-127;endfunction
  function automatic int code16(input longint signed raw);
    real value;longint signed rounded;
    value=real'(raw)/128.0;
    rounded=value>=0.0?longint'($floor(value+0.5)):-longint'($floor(-value+0.5));
    return rounded>32767?32767:rounded < -32768?-32768:int'(rounded);
  endfunction
  function automatic int code8(input int raw);
    real value;int rounded;
    value=real'(raw)/(2.0**frame_shift);
    rounded=value>=0.0?$rtoi(value+0.5):-$rtoi(-value+0.5);
    return rounded>127?127:rounded < -128?-128:rounded;
  endfunction
  function automatic int nonlinear_reference(input int row);
    real x,value;int g,u,rounded;
    g=code16(gate_sum[row]);u=code16(up_sum[row]);x=real'(g)/256.0;
    value=x/(1.0+$exp(-x))*real'(u);
    rounded=value>=0.0?$rtoi(value+0.5):-$rtoi(-value+0.5);
    return rounded>32767?32767:rounded < -32768?-32768:rounded;
  endfunction

  for(genvar c=0;c<5;c++) begin: monitors
    for(genvar k=0;k<4;k++) begin: cores
      always @(posedge clk)
        if(rst_n && dut.engine.backend.clusters[c].cluster.cores[k].cmd_valid &&
           dut.engine.backend.clusters[c].cluster.cores[k].cmd_ready) active_cores[c*4+k]=1;
    end
  end

  always @(posedge clk) begin: independent_arithmetic_reference
    int expected,actual,tolerance,u;
    if(rst_n && dut.engine.projection_in_valid && dut.engine.projection_in_ready)
      current_phase=dut.engine.projection_in_weight_base==UpBase?1:0;
    if(rst_n && dut.engine.projection_out_valid && dut.engine.projection_out_ready && !dut.engine.projection_out_error) begin
      for(int row=0;row<packet_rows;row++) begin
        expected=int'(current_phase==0?gate_sum[row]:up_sum[row]);
        if($test$plusargs("CORRUPT_DOT_REFERENCE") && row==0) expected++;
        if(dut.engine.projection_out_data[row*32+:32]!==32'(expected))
          $fatal(1,"FRAME_EXACT_DOT_MISMATCH phase=%0d row=%0d",current_phase,row);
        exact_dots++;
      end
    end
    if(rst_n && dut.engine.in_valid && dut.engine.in_ready) begin
      if(dut.engine.in_is_down) down_accepts++;else gate_accepts++;
    end
    if(rst_n && dut.engine.out_valid && dut.engine.out_ready && !dut.engine.out_is_down && !dut.engine.out_error) begin
      if(dut.engine.out_count!==8'(packet_rows) || dut.engine.out_channels!==packet_ids)
        $fatal(1,"FRAME_NONLINEAR_PACKET_IDENTITY");
      for(int i=0;i<160;i++) begin
        actual=int'($signed(dut.engine.out_data[i*32+:32]));
        if(i>=packet_rows) begin
          if(actual!==0) $fatal(1,"FRAME_NONLINEAR_PADDING");
        end else begin
          expected=nonlinear_reference(i);u=code16(up_sum[i]);tolerance=(2*(u<0?-u:u)+255)/256+1;
          if((^dut.engine.out_data[i*32+:32])===1'bx || actual-expected>tolerance || expected-actual>tolerance)
            $fatal(1,"FRAME_NONLINEAR_REFERENCE row=%0d got=%0d expected=%0d",i,actual,expected);
          nonlinear_codes++;
          // All output rows are summed directly, independently of production
          // subgroup, slot, round, append and finalization counters.
          for(int row=0;row<frame_outputs;row++)
            golden[row]+=longint'(code8(actual))*longint'(down_weight(row,int'(packet_ids[i*16+:16])));
        end
      end
    end
  end

  always @(posedge clk) begin: memory_peer
    logic [63:0] offset,base;
    int kind,row,column;
    bit selected;
    if(!rst_n) begin
      cycle<=0;memory_active<=0;rsp_valid<=0;request_held=0;
    end else begin
      cycle<=cycle+1;
      if(!dut.engine.controller_reset_n && (req_valid || memory_active || rsp_valid || request_held))
        $fatal(1,"FRAME_OWNER_RESET_BEFORE_MEMORY_DRAIN");
      if(out_valid && (memory_active || rsp_valid)) $fatal(1,"FRAME_EARLY_RESULT");
      if(request_held && (req_valid!==1 || {req_address,req_length}!==held_request))
        $fatal(1,"FRAME_MEMORY_OFFER_CHANGED");
      request_held=req_valid && !req_ready;held_request={req_address,req_length};
      if(req_valid && req_ready) begin
        if(req_length==0 || req_length>16 || req_address[2:0]!=0) $fatal(1,"FRAME_BAD_MEMORY_REQUEST");
        kind=req_address>=UpBase?3:req_address>=GateBase?1:req_address>=ActBase?0:2;
        if(kind==0) begin
          if(req_address<ActBase || {1'b0,req_address}+65'(req_length*8)>{1'b0,ActBase}+65'(frame_features*8))
            $fatal(1,"FRAME_ACTIVATION_PADDING_READ");
        end else if(kind==2) begin
          if(req_length!==5'd1 || req_address<DownBase) $fatal(1,"FRAME_BAD_DOWN_GATHER");
          offset=req_address-DownBase;row=int'(offset/64'(frame_dense));column=int'(offset%64'(frame_dense));selected=0;
          for(int i=0;i<packet_rows;i++) if(int'(packet_ids[i*16+:16])/8==column/8) selected=1;
          if(row>=frame_outputs || !selected) $fatal(1,"FRAME_UNUSED_DOWN_ROW_OR_COLUMN");
        end else begin
          base=kind==3?UpBase:GateBase;offset=req_address-base;
          row=int'(offset/64'(frame_features*8));column=int'(offset%64'(frame_features*8));selected=0;
          for(int i=0;i<packet_rows;i++) if(row==int'(packet_ids[i*16+:16])) selected=1;
          if(!selected || column+int'(req_length)*8>frame_features*8) $fatal(1,"FRAME_UNUSED_GATE_UP_ROW");
        end
        address<=req_address;length<=int'(req_length);beat<=0;memory_kind<=kind;memory_active<=1;requests++;
        if(!error_fired && ((fault_up && kind==3) || (fault_down && kind==2 && prefixes>0))) begin
          error_fired=1;rsp_error<=1;
        end else rsp_error<=0;
      end
      if(memory_active && !rsp_valid && cycle%3!=0) begin
        rsp_valid<=1;rsp_last<=beat==length-1;
        for(int lane=0;lane<8;lane++) begin
          if(memory_kind==2) begin
            offset=address-DownBase+64'(beat*8+lane);
            rsp_data[lane*8+:8]<=8'(down_weight(int'(offset/64'(frame_dense)),int'(offset%64'(frame_dense))));
          end else if(memory_kind==0)
            rsp_data[lane*8+:8]<=8'(activation_value(int'(address-ActBase)+beat*8+lane));
          else begin
            base=memory_kind==3?UpBase:GateBase;offset=address-base+64'(beat*8+lane);
            rsp_data[lane*8+:8]<=8'(weight_value(int'(offset/64'(frame_features*8)),int'(offset%64'(frame_features*8)),memory_kind==3?1:0));
          end
        end
      end
      if(rsp_valid && rsp_ready) begin
        rsp_valid<=0;beat<=beat+1;if(rsp_last) memory_active<=0;
      end
    end
  end

  always @(posedge clk) begin: frame_scoreboard
    int amount,value;
    if(!rst_n) was_stalled=0;
    else begin
      if(was_stalled && (!out_valid || {out_last,out_error,out_fallback,out_tag,out_start,out_count,out_data}!==held_output))
        $fatal(1,"FRAME_STALLED_PACKET_CHANGED");
      if(out_valid && !out_ready) begin
        held_output={out_last,out_error,out_fallback,out_tag,out_start,out_count,out_data};
        if(out_error) error_stall_cycles++;else successful_stall_cycles++;
      end
      was_stalled=out_valid && !out_ready;
    end
    if(rst_n && out_valid && out_ready) begin
      if(out_tag!==frame_tag) $fatal(1,"FRAME_TAG");
      if(out_error) begin
        if(!expect_error || !out_last || out_count!==0 || out_start!==0 || out_fallback!==0 || out_data!==0)
          $fatal(1,"FRAME_ERROR_PACKET");
        if(dut.engine.backend.context_valid!==0) $fatal(1,"FRAME_CONTEXTS_SURVIVED_ERROR");
        frame_done=1;completed++;
      end else begin
        if(seen>=frame_outputs || out_start!==16'(seen)) $fatal(1,"FRAME_OUTPUT_ORDER");
        amount=frame_outputs-seen>160?160:frame_outputs-seen;
        if(out_count!==8'(amount) || out_last!==(seen+amount==frame_outputs) || out_fallback!==frame_fallback)
          $fatal(1,"FRAME_OUTPUT_SHAPE");
        for(int row=0;row<160;row++) begin
          value=row<amount?int'(golden[seen+row]):0;
          if($test$plusargs("CORRUPT_FRAME_REFERENCE") && row==0) value++;
          if(out_data[row*32+:32]!==32'(value)) $fatal(1,"FRAME_HIDDEN_SUM row=%0d got=%0d expected=%0d",seen+row,$signed(out_data[row*32+:32]),value);
        end
        seen+=amount;checked_hidden_outputs+=amount;prefixes++;
        if(out_last) begin
          if(expect_error) $fatal(1,"FRAME_EXPECTED_ERROR");
          frame_done=1;completed++;
        end
      end
      $display("FRAME_OUTPUT_PACKET tag=%h error=%b seen=%0d",out_tag,out_error,seen);$fflush();
    end
  end

  task automatic configure(input int outputs,dense,features,input bit error_expected=0,input int bad=0);
    begin
      @(negedge clk);while(!cfg_ready) @(negedge clk);
      frame_outputs=outputs;frame_dense=dense;frame_features=features;salt=201+completed;
      frame_tag=32'h95000000+32'(completed);expect_error=error_expected;frame_done=0;frame_fallback=0;
      seen=0;prefixes=0;requests=0;gate_accepts=0;down_accepts=0;fault_up=0;fault_down=0;error_fired=0;
      for(int row=0;row<2400;row++) golden[row]=0;
      cfg_tag=frame_tag;cfg_output_count=16'(outputs);cfg_dense_features=17'(dense);cfg_features=10'(features);
      cfg_activation_base=ActBase;cfg_weight_base=GateBase;cfg_up_weight_base=UpBase;cfg_down_weight_base=DownBase;
      cfg_gate_shift=7;cfg_up_shift=7;cfg_down_shift=6'(frame_shift);
      if(bad==1) cfg_up_weight_base=UpBase+1;
      if(bad==2) cfg_down_weight_base=64'hfffffffffffffff8;
      cfg_valid=1;@(posedge clk);if(!cfg_ready) $fatal(1,"FRAME_CONFIG_NOT_ACCEPTED");
      @(negedge clk);cfg_valid=0;cfg_tag='1;cfg_output_count=0;cfg_dense_features=0;cfg_features=0;
      cfg_activation_base=0;cfg_weight_base=0;cfg_up_weight_base=0;cfg_down_weight_base=0;
      cfg_gate_shift=0;cfg_up_shift=0;cfg_down_shift=0;
    end
  endtask

  task automatic packet(input int count,packet_salt,input bit last,fallback=0,bad_id=0);
    int channel;
    begin
      @(negedge clk);while(!in_ready) @(negedge clk);
      in_count=8'(count);in_last=last;in_fallback=fallback;packet_ids=0;packet_rows=count;current_phase=0;
      frame_fallback|=fallback;
      for(int i=0;i<160;i++) begin
        channel=bad_id?frame_dense:(i==0?frame_dense-1:(packet_salt*173+i*37)%frame_dense);
        if(i<count) packet_ids[i*16+:16]=16'(channel);
        gate_sum[i]=0;up_sum[i]=0;
        if(i<count && count<=160 && !bad_id) for(int feature=0;feature<frame_features*8;feature++) begin
          gate_sum[i]+=longint'(activation_value(feature))*longint'(weight_value(channel,feature,0));
          up_sum[i]+=longint'(activation_value(feature))*longint'(weight_value(channel,feature,1));
        end
      end
      in_channels=packet_ids;in_valid=1;@(posedge clk);if(!in_ready) $fatal(1,"FRAME_PACKET_NOT_ACCEPTED");
      @(negedge clk);in_valid=0;in_channels='1;in_count='1;in_last=!last;in_fallback=!fallback;
    end
  endtask

  task automatic finish_frame(input int expected_gates=-1,expected_down=-1,input bit no_memory=0);
    int timeout;
    begin
      timeout=0;while(!frame_done && timeout<12000000) begin @(negedge clk);timeout++;end
      if(!frame_done) $fatal(1,"FRAME_COMPLETION_TIMEOUT");
      if(expected_gates>=0 && gate_accepts!=expected_gates) $fatal(1,"FRAME_GATE_COUNT got=%0d expected=%0d",gate_accepts,expected_gates);
      if(expected_down>=0 && down_accepts!=expected_down) $fatal(1,"FRAME_DOWN_COUNT got=%0d expected=%0d",down_accepts,expected_down);
      if(no_memory && requests!=0) $fatal(1,"FRAME_INVALID_OR_EMPTY_READ_MEMORY");
      if((fault_up || fault_down) && !error_fired) $fatal(1,"FRAME_MEMORY_ERROR_NOT_EXERCISED");
      $display("FRAME_CASE_PASS case=%0d outputs=%0d error=%0d gate=%0d down=%0d",completed,seen,expect_error,gate_accepts,down_accepts);$fflush();
    end
  endtask

  initial begin
    repeat(3) @(negedge clk);
    if(core_instances!=20 || cluster_instances!=5 || weight_mask_memories!=360 || activation_memories!=40 || result_memories!=200)
      $fatal(1,"FRAME_ACTUAL_HIERARCHY_MISMATCH");
    $display("FRAME_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=600");$fflush();
    rst_n=1;
    if($test$plusargs("REFERENCE_SMOKE")) begin
      configure(33,64,3);packet(3,1,1);finish_frame();$fatal(1,"FRAME_WRONG_REFERENCE_ACCEPTED");
    end
    configure(2048,5632,256);packet(160,1,0,1);packet(33,2,1);finish_frame(2,91);
    configure(161,64,3);packet(33,1,1);finish_frame(1,4);
    configure(1,8,1);packet(0,0,1);finish_frame(1,1,1);
    configure(2400,32,1);packet(0,0,0);packet(0,0,1);finish_frame(2,30,1);
    configure(320,256,3);packet(32,1,0);packet(0,0,1);finish_frame(2,4);
    configure(1,65536,1);packet(1,1,1);finish_frame(1,1);
    configure(0,64,3,1);finish_frame(0,0,1);
    configure(2401,64,3,1);finish_frame(0,0,1);
    configure(160,64,0,1);finish_frame(0,0,1);
    configure(160,7,3,1);finish_frame(0,0,1);
    configure(160,64,3,1,1);finish_frame(0,0,1);
    configure(160,64,3,1,2);finish_frame(0,0,1);
    configure(160,5632,3,1);packet(161,1,1);finish_frame(0,0,1);
    configure(160,64,3,1);packet(1,1,1,0,1);finish_frame(0,0,1);
    configure(160,8,3,1);packet(9,1,1);finish_frame(0,0,1);
    configure(480,64,3,1);fault_down=1;packet(32,1,0);packet(32,2,1);finish_frame();
    if(prefixes!=1) $fatal(1,"FRAME_LATE_ERROR_PREFIX_NOT_EXERCISED");
    configure(160,64,5,1);fault_up=1;packet(3,1,1);finish_frame();
    configure(2048,64,67);packet(7,1,1);wait(memory_active);
    @(negedge clk);rst_n=0;repeat(3) @(negedge clk);rst_n=1;
    configure(129,64,3);packet(3,1,1);finish_frame(1,1);
    if(completed!=18 || active_cores!==20'hfffff || exact_dots<652 || nonlinear_codes<326 ||
       successful_stall_cycles<9 || error_stall_cycles<9) $fatal(1,"FRAME_CASE_INVENTORY");
    $display("FRAME_PASS cases=%0d hidden_outputs=%0d exact_dots=%0d nonlinear_codes=%0d success_stalls=%0d error_stalls=%0d",
        completed,checked_hidden_outputs,exact_dots,nonlinear_codes,successful_stall_cycles,error_stall_cycles);$finish;
  end
  initial begin #500000000;$fatal(1,"FRAME_WATCHDOG");end
endmodule

module tri_oracle_frame_instance_count #(parameter int KIND=0) ();
  initial begin
    case(KIND)
      0:$root.tri_oracle_feedforward_frame_tb.core_instances++;
      1:$root.tri_oracle_feedforward_frame_tb.cluster_instances++;
      2:$root.tri_oracle_feedforward_frame_tb.weight_mask_memories++;
      3:$root.tri_oracle_feedforward_frame_tb.activation_memories++;
      4:$root.tri_oracle_feedforward_frame_tb.result_memories++;
    endcase
  end
endmodule
bind tri_oracle_sram_memory_compute tri_oracle_frame_instance_count #(.KIND(0)) count_frame_core ();
bind tri_oracle_sram_compute_cluster tri_oracle_frame_instance_count #(.KIND(1)) count_frame_cluster ();
bind TS5N28HPCPSVTA32X128M2FW tri_oracle_frame_instance_count #(.KIND(2)) count_frame_weight_mask ();
bind TS5N28HPCPSVTA512X64M4F tri_oracle_frame_instance_count #(.KIND(3)) count_frame_activation ();
bind TS6N28HPCPSVTA16X128M2F tri_oracle_frame_instance_count #(.KIND(4)) count_frame_result ();
