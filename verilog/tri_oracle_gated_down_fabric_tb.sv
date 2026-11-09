`timescale 1ns/1ps

module tri_oracle_gated_down_fabric_tb;
  localparam logic [63:0] ActBase=64'h100002000,GateBase=64'h200004000,UpBase=64'h300008000,DownBase=64'h100000;
  logic clk=0;always #5 clk=~clk;
  logic rst_n=0,in_valid=0,in_is_down=0,in_last=0,in_fallback=0,in_accumulate=0,out_ready=0;
  logic [31:0] in_tag=0;
  logic [2559:0] in_channels=0;
  logic [1023:0] in_data=0;
  logic [7:0] in_count=0,in_output_count=0;
  logic [63:0] in_activation_base=ActBase,in_weight_base=GateBase,in_up_weight_base=UpBase;
  logic [9:0] in_features=0;
  logic [16:0] in_dense_features=5632;
  logic [15:0] in_output_start=0;
  logic [5:0] in_shift=0,in_gate_shift=7,in_up_shift=7;
  logic [3:0] in_slot=0;
  wire in_ready,out_valid,out_is_down,out_last,out_fallback,out_error,req_valid,rsp_ready;
  wire [31:0] out_tag;
  wire [7:0] out_count;
  wire [2559:0] out_channels;
  wire [5119:0] out_data;
  wire [15:0] out_start;
  wire [3:0] out_slot;
  wire [63:0] req_address;
  wire [4:0] req_length;
  logic rsp_valid=0,rsp_last=0,rsp_error=0;
  logic [63:0] rsp_data=0;
  int core_instances=0,cluster_instances=0,weight_mask_memories=0,activation_memories=0,result_memories=0;
  int cycle=0,cases_checked=0,exact_dots=0,nonlinear_codes=0,returned_hidden_outputs=0;
  logic [19:0] active_cores=0;
  bit model_is_down=0,memory_active=0,weight_burst=0,request_held=0,inject_error=0,error_fired=0;
  int beat=0,length=0,matrix_phase=0,current_phase=0,requests=0;
  logic [63:0] address=0;
  logic [68:0] held_request;
  int strips=0,rows=0,salt=0,down_count=0,down_outputs=0,down_start=0,down_slot=0,down_shift=0;
  logic [511:0] selected_ids=0;
  logic [1023:0] selected_codes=0;
  logic [2559:0] expected_channels=0,latest_channels=0;
  logic [5119:0] latest_codes=0;
  int latest_count=0;
  logic [31:0] expected_tag;
  bit expected_last,expected_fallback;
  longint signed gate_sum[160],up_sum[160],golden[16][160];
  wire req_ready=!memory_active && !rsp_valid && cycle%4!=0;
  tri_oracle_gated_down_fabric dut(.*);

  function automatic int activation_value(input int feature);
    return (feature*17+salt*11)%256-128;
  endfunction
  function automatic int weight_value(input int channel,feature,phase);
    return phase==0?(channel*7+feature*13+salt*3)%256-128:(channel*11+feature*5+salt*7)%256-128;
  endfunction
  function automatic int down_weight(input int row,column);
    return (row*3+column*7)%255-127;
  endfunction
  function automatic int code16(input longint signed raw,input int shift);
    real value;
    longint signed rounded;
    value=real'(raw)/(2.0**shift);
    rounded=value>=0.0?longint'($floor(value+0.5)):-longint'($floor(-value+0.5));
    return rounded>32767?32767:rounded < -32768?-32768:int'(rounded);
  endfunction
  function automatic int code8(input int index);
    real value;
    int rounded;
    value=real'($signed(selected_codes[index*32+:32]))/(2.0**down_shift);
    rounded=value>=0.0?$rtoi(value+0.5):-$rtoi(-value+0.5);
    return rounded>127?127:rounded < -128?-128:rounded;
  endfunction
  function automatic int nonlinear_reference(input int row);
    real x,value;
    int g,u,rounded;
    g=code16(gate_sum[row],7);u=code16(up_sum[row],7);x=real'(g)/256.0;
    value=x/(1.0+$exp(-x))*real'(u);
    rounded=value>=0.0?$rtoi(value+0.5):-$rtoi(-value+0.5);
    return rounded>32767?32767:rounded < -32768?-32768:rounded;
  endfunction

  for(genvar c=0;c<5;c++) begin: monitors
    for(genvar k=0;k<4;k++) begin: cores
      always @(posedge clk)
        if(rst_n && dut.backend.clusters[c].cluster.cores[k].cmd_valid &&
           dut.backend.clusters[c].cluster.cores[k].cmd_ready) active_cores[c*4+k]=1;
    end
  end

  always @(posedge clk) begin: exact_projection_reference
    int expected;
    if(rst_n && dut.projection_in_valid && dut.projection_in_ready)
      current_phase=dut.projection_in_weight_base==UpBase?1:0;
    if(rst_n && dut.projection_out_valid && dut.projection_out_ready && !dut.projection_out_error) begin
      if(model_is_down) $fatal(1,"NONLINEAR_OWNER_PROJECTED_DURING_DOWN");
      for(int row=0;row<rows;row++) begin
        expected=int'(current_phase==0?gate_sum[row]:up_sum[row]);
        if($test$plusargs("CORRUPT_DOT_REFERENCE") && row==0) expected++;
        if(dut.projection_out_data[row*32+:32]!==32'(expected))
          $fatal(1,"GATED_DOWN_EXACT_DOT_MISMATCH phase=%0d row=%0d",current_phase,row);
        exact_dots++;
      end
    end
  end

  always @(posedge clk) begin: memory_peer
    logic [63:0] offset,base;
    bit is_activation,selected;
    int row,column,phase;
    if(!rst_n) begin
      cycle<=0;memory_active<=0;rsp_valid<=0;request_held=0;
    end else begin
      cycle<=cycle+1;
      if(!dut.controller_reset_n && (req_valid || memory_active || rsp_valid || request_held))
        $fatal(1,"OWNER_RESET_BEFORE_MEMORY_DRAIN");
      if(out_valid && (memory_active || rsp_valid)) $fatal(1,"OWNER_EARLY_RESULT");
      if(request_held && (req_valid!==1 || {req_address,req_length}!==held_request))
        $fatal(1,"OWNER_MEMORY_OFFER_CHANGED");
      request_held=req_valid && !req_ready;held_request={req_address,req_length};
      if(req_valid && req_ready) begin
        if(req_length==0 || req_length>16 || req_address[2:0]!=0) $fatal(1,"OWNER_BAD_MEMORY_REQUEST");
        is_activation=!model_is_down && req_address>=ActBase && {1'b0,req_address}<{1'b0,ActBase}+65'(strips*8);
        phase=req_address>=UpBase?1:0;base=phase==1?UpBase:GateBase;
        if(model_is_down) begin
          if(req_length!==5'd1 || req_address<DownBase) $fatal(1,"OWNER_BAD_DOWN_GATHER");
          offset=req_address-DownBase;row=int'(offset/5632);column=int'(offset%5632);selected=0;
          for(int i=0;i<down_count;i++)
            if(int'(selected_ids[i*16+:16])/8==column/8 && code8(i)!=0) selected=1;
          if(row<down_start || row>=down_start+down_outputs || !selected) $fatal(1,"OWNER_UNUSED_DOWN_ROW_OR_COLUMN");
        end else if(is_activation) begin
          if({1'b0,req_address}+65'(req_length*8)>{1'b0,ActBase}+65'(strips*8)) $fatal(1,"OWNER_ACTIVATION_PADDING_READ");
        end else begin
          if(req_address<base) $fatal(1,"OWNER_BAD_MATRIX_BASE");
          offset=req_address-base;row=int'(offset/64'(strips*8));column=int'(offset%64'(strips*8));selected=0;
          for(int i=0;i<rows;i++) if(row==int'(expected_channels[i*16+:16])) selected=1;
          if(!selected || column+int'(req_length)*8>strips*8) $fatal(1,"OWNER_UNUSED_GATE_UP_ROW");
        end
        address<=req_address;length<=int'(req_length);beat<=0;weight_burst<=!is_activation;
        matrix_phase<=phase;memory_active<=1;requests++;
        if(inject_error && !error_fired && !model_is_down && current_phase==1 && !is_activation) begin
          error_fired=1;rsp_error<=1;
        end else rsp_error<=0;
      end
      if(memory_active && !rsp_valid && cycle%3!=0) begin
        rsp_valid<=1;rsp_last<=beat==length-1;
        for(int lane=0;lane<8;lane++) begin
          if(model_is_down) begin
            offset=address-DownBase+64'(beat*8+lane);
            rsp_data[lane*8+:8]<=8'(down_weight(int'(offset/5632),int'(offset%5632)));
          end else if(!weight_burst)
            rsp_data[lane*8+:8]<=8'(activation_value(int'(address-ActBase)+beat*8+lane));
          else begin
            base=matrix_phase==1?UpBase:GateBase;offset=address-base+64'(beat*8+lane);
            rsp_data[lane*8+:8]<=8'(weight_value(int'(offset/64'(strips*8)),int'(offset%64'(strips*8)),matrix_phase));
          end
        end
      end
      if(rsp_valid && rsp_ready) begin
        rsp_valid<=0;beat<=beat+1;if(rsp_last) memory_active<=0;
      end
    end
  end

  task automatic hold_and_release;
    logic [7743:0] held;
    begin
      held={out_is_down,out_start,out_slot,out_count,out_last,out_fallback,out_error,out_tag,out_channels,out_data};
      repeat(6) begin
        @(negedge clk);
        if(!out_valid || in_ready || held!=={out_is_down,out_start,out_slot,out_count,out_last,out_fallback,out_error,out_tag,out_channels,out_data})
          $fatal(1,"OWNER_STALLED_RESULT_CHANGED");
      end
      out_ready=1;@(posedge clk);@(negedge clk);out_ready=0;cases_checked++;
    end
  endtask

  task automatic gated_launch(input int n,features,case_salt,input bit last=0,bad_up=0,memory_error=0);
    begin
      @(negedge clk);while(!in_ready) @(negedge clk);
      model_is_down=0;strips=features;rows=n;salt=case_salt;requests=0;inject_error=memory_error;error_fired=0;current_phase=0;
      expected_channels=0;
      for(int row=0;row<160;row++) begin
        expected_channels[row*16+:16]=16'(row==0?5631:(row*37+case_salt*7)%5632);
        gate_sum[row]=0;up_sum[row]=0;
        if(row<n) for(int feature=0;feature<features*8;feature++) begin
          gate_sum[row]+=longint'(activation_value(feature))*longint'(weight_value(int'(expected_channels[row*16+:16]),feature,0));
          up_sum[row]+=longint'(activation_value(feature))*longint'(weight_value(int'(expected_channels[row*16+:16]),feature,1));
        end
      end
      expected_tag=32'h93000000+32'(case_salt);expected_last=last;expected_fallback=case_salt%2!=0;
      in_is_down=0;in_count=8'(n);in_features=10'(features);in_channels=expected_channels;
      in_tag=expected_tag;in_last=last;in_fallback=expected_fallback;in_activation_base=ActBase;
      in_weight_base=GateBase;in_up_weight_base=bad_up?UpBase+1:UpBase;in_gate_shift=7;in_up_shift=7;
      in_valid=1;@(posedge clk);if(!in_ready) $fatal(1,"OWNER_GATED_NOT_ACCEPTED");
      @(negedge clk);in_valid=0;in_is_down=1;in_tag='1;in_channels='1;in_count=0;in_up_weight_base=0;
    end
  endtask

  task automatic gated_result(input bit error_expected=0);
    int timeout,actual,expected,tolerance,u;
    begin
      timeout=0;while(!out_valid && timeout<2000000) begin @(negedge clk);timeout++;end
      if(!out_valid || out_is_down!==0 || out_error!==error_expected || out_tag!==expected_tag ||
         out_count!==8'(error_expected?0:rows) || out_last!==(error_expected || expected_last) ||
         out_fallback!==(!error_expected && expected_fallback) || out_start!==0 || out_slot!==0 ||
         out_channels!==(error_expected?2560'b0:expected_channels)) $fatal(1,"OWNER_GATED_METADATA");
      for(int row=0;row<160;row++) begin
        actual=int'($signed(out_data[row*32+:32]));
        if(error_expected || row>=rows) begin if(out_data[row*32+:32]!==0) $fatal(1,"OWNER_GATED_PADDING_OR_ERROR_DATA");end
        else begin
          expected=nonlinear_reference(row);u=code16(up_sum[row],7);tolerance=(2*(u<0?-u:u)+255)/256+1;
          if((^out_data[row*32+:32])===1'bx || actual-expected>tolerance || expected-actual>tolerance)
            $fatal(1,"OWNER_NONLINEAR_REFERENCE row=%0d got=%0d expected=%0d",row,actual,expected);
          nonlinear_codes++;
        end
      end
      if(inject_error && !error_fired) $fatal(1,"OWNER_UP_ERROR_NOT_EXERCISED");
      if(!error_expected) begin latest_codes=out_data;latest_channels=out_channels;latest_count=rows;end
      hold_and_release();
      $display("GATED_DOWN_GATED_CASE_PASS rows=%0d error=%0d",rows,error_expected);$fflush();
    end
  endtask

  task automatic gated_case(input int n,features,case_salt,input bit last=0,bad_up=0,memory_error=0);
    gated_launch(n,features,case_salt,last,bad_up,memory_error);
    gated_result(bad_up || memory_error);
    if(bad_up && requests!=0) $fatal(1,"OWNER_INVALID_UP_CONFIG_READ_MEMORY");
  endtask

  task automatic down_case(input int n,outputs,start,slot,input bit append,last,
                           input logic [31:0] tag,input bit use_latest=1,error_expected=0,input int subgroup=0);
    int timeout,value;
    begin
      @(negedge clk);while(!in_ready) @(negedge clk);
      model_is_down=1;down_count=n;down_outputs=outputs;down_start=start;down_slot=slot;down_shift=use_latest?8:0;
      requests=0;inject_error=0;error_fired=0;selected_ids=0;selected_codes=0;
      if(use_latest) begin
        if(n>0 && subgroup*32+n>latest_count) $fatal(1,"OWNER_PRODUCER_READ_PADDING");
        selected_ids=latest_channels[subgroup*512+:512];selected_codes=latest_codes[subgroup*1024+:1024];
      end else for(int i=0;i<n;i++) begin
        selected_ids[i*16+:16]=16'(i*173%5632);selected_codes[i*32+:32]=32'(i%2?-31:27);
      end
      if(!error_expected) begin
        if(!append) for(int row=0;row<160;row++) golden[slot][row]=0;
        for(int row=0;row<outputs;row++) for(int i=0;i<n;i++)
          golden[slot][row]+=longint'(code8(i))*longint'(down_weight(start+row,int'(selected_ids[i*16+:16])));
      end
      in_is_down=1;in_accumulate=append;in_last=last;in_fallback=1;in_tag=tag;in_count=8'(n);
      in_output_count=8'(outputs);in_output_start=16'(start);in_slot=4'(slot);in_shift=6'(down_shift);
      in_dense_features=5632;in_channels={2048'b0,selected_ids};in_data=selected_codes;in_weight_base=DownBase;
      in_valid=1;@(posedge clk);if(!in_ready) $fatal(1,"OWNER_DOWN_NOT_ACCEPTED");
      @(negedge clk);in_valid=0;in_is_down=0;in_tag='1;in_channels='1;in_data='1;in_slot=0;
      timeout=0;while(!out_valid && timeout<2000000) begin @(negedge clk);timeout++;end
      if(!out_valid || out_is_down!==1 || out_error!==error_expected || out_tag!==tag ||
         out_count!==8'(error_expected?0:outputs) || out_start!==16'(start) || out_slot!==4'(slot) ||
         out_last!==(last || error_expected) || out_fallback!==0 || out_channels!==0) $fatal(1,"OWNER_DOWN_METADATA");
      for(int row=0;row<160;row++) begin
        value=error_expected || row>=outputs?0:int'(golden[slot][row]);
        if($test$plusargs("CORRUPT_DOWN_REFERENCE") && row==2 && !error_expected) value++;
        if(out_data[row*32+:32]!==32'(value)) $fatal(1,"GATED_DOWN_DOWN_REFERENCE row=%0d",row);
      end
      if(n==0 && requests!=0) $fatal(1,"OWNER_EMPTY_DOWN_READ_MEMORY");
      hold_and_release();
      $display("GATED_DOWN_DOWN_CASE_PASS start=%0d slot=%0d error=%0d",start,slot,error_expected);$fflush();
    end
  endtask

  initial begin
    repeat(3) @(negedge clk);
    if(core_instances!=20 || cluster_instances!=5 || weight_mask_memories!=360 || activation_memories!=40 || result_memories!=200)
      $fatal(1,"GATED_DOWN_ACTUAL_HIERARCHY_MISMATCH");
    $display("GATED_DOWN_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=600");
    rst_n=1;
    if($test$plusargs("DOT_SMOKE")) begin gated_case(3,5,200);$fatal(1,"Wrong dot reference accepted");end
    if($test$plusargs("DOWN_SMOKE")) begin down_case(32,160,0,1,0,1,32'h9310,0);$fatal(1,"Wrong down reference accepted");end
    for(int round=0;round<13;round++) down_case(0,round==12?128:160,round*160,round+1,0,0,32'h9300,0);
    gated_case(32,256,201);
    for(int round=0;round<13;round++) down_case(32,round==12?128:160,round*160,round+1,1,0,32'h9300);
    gated_case(32,256,202,1);
    for(int round=0;round<13;round++) down_case(32,round==12?128:160,round*160,round+1,1,0,32'h9300);
    gated_case(0,1,203,1);
    for(int round=0;round<13;round++) begin
      down_case(0,round==12?128:160,round*160,round+1,1,1,32'h9300);
      returned_hidden_outputs+=round==12?128:160;
    end
    gated_case(160,5,204,1);
    for(int subgroup=0;subgroup<5;subgroup++) down_case(32,160,0,14,subgroup!=0,subgroup==4,32'h9314,1,0,subgroup);
    down_case(0,160,0,1,0,0,32'h9310,0);
    gated_case(3,5,205,0,1);
    down_case(0,160,0,1,1,1,32'h9310,0,1);
    down_case(32,160,0,1,0,1,32'h9311,0);
    gated_case(3,5,206,0,0,1);
    gated_case(3,5,207,1);
    down_case(0,160,0,7,0,0,32'h9317,0);
    gated_launch(7,67,208);wait(memory_active);
    @(negedge clk);rst_n=0;repeat(3) @(negedge clk);rst_n=1;
    down_case(0,160,0,7,1,1,32'h9317,0,1);
    gated_case(3,5,209,1);
    if(cases_checked!=70 || returned_hidden_outputs!=2048 || active_cores!==20'hfffff || exact_dots<448)
      $fatal(1,"GATED_DOWN_CASE_INVENTORY");
    $display("GATED_DOWN_PASS cases=%0d hidden_outputs=%0d exact_dots=%0d nonlinear_codes=%0d",cases_checked,returned_hidden_outputs,exact_dots,nonlinear_codes);
    $finish;
  end
  initial begin #300000000;$fatal(1,"GATED_DOWN_WATCHDOG");end
endmodule

module tri_oracle_gated_down_instance_count #(parameter int KIND = 0) ();
  initial begin
    case (KIND)
      0: $root.tri_oracle_gated_down_fabric_tb.core_instances++;
      1: $root.tri_oracle_gated_down_fabric_tb.cluster_instances++;
      2: $root.tri_oracle_gated_down_fabric_tb.weight_mask_memories++;
      3: $root.tri_oracle_gated_down_fabric_tb.activation_memories++;
      4: $root.tri_oracle_gated_down_fabric_tb.result_memories++;
    endcase
  end
endmodule

bind tri_oracle_sram_memory_compute tri_oracle_gated_down_instance_count
    #(.KIND(0)) count_actual_core ();
bind tri_oracle_sram_compute_cluster tri_oracle_gated_down_instance_count
    #(.KIND(1)) count_actual_cluster ();
bind TS5N28HPCPSVTA32X128M2FW tri_oracle_gated_down_instance_count
    #(.KIND(2)) count_actual_weight_mask ();
bind TS5N28HPCPSVTA512X64M4F tri_oracle_gated_down_instance_count
    #(.KIND(3)) count_actual_activation ();
bind TS6N28HPCPSVTA16X128M2F tri_oracle_gated_down_instance_count
    #(.KIND(4)) count_actual_result ();
