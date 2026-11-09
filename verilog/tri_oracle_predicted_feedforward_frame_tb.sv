`timescale 1ns/1ps
module tri_oracle_predicted_feedforward_frame_tb;
  localparam logic [63:0] ActBase=64'h100002000,GateBase=64'h200004000,UpBase=64'h300008000,DownBase=64'h100000;
  logic clk=0;always #5 clk=~clk;
  logic rst_n=0,cfg_valid=0,in_valid=0,in_last=0,in_group_last=0;
  logic [31:0] cfg_tag=0;
  logic [63:0] cfg_activation_base=0,cfg_weight_base=0,cfg_up_weight_base=0,cfg_down_weight_base=0;
  logic [9:0] cfg_features=0;
  logic [16:0] cfg_dense_features=0;
  logic [15:0] cfg_output_count=0;
  logic [5:0] cfg_gate_shift=0,cfg_up_shift=0,cfg_down_shift=8;
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
  int cycle=0,completed=0,dense=0,outputs=0,pattern=0,features=3,seen=0,requests=0,hidden_checked=0;
  int beat=0,length=0,kind=0,success_stalls=0,error_stalls=0;
  bit frame_done=0,expect_error=0,memory_active=0,request_held=0,held=0,inject_up=0,error_fired=0,force_hold=0;
  logic [31:0] tag=0;
  logic [63:0] address=0;
  logic [68:0] held_request=0;
  logic [5178:0] held_output=0;
  longint signed golden[2400];
  wire req_ready=!memory_active && !rsp_valid && cycle%4!=0;
  wire out_ready=!force_hold && cycle%19>=9;
  tri_oracle_predicted_feedforward_frame dut(.*);
  function automatic bit keep(input int channel,mode);
    return mode==1 || (mode==0 && channel%2==0) || (mode==3 && (channel%29==0 || channel==5631));
  endfunction
  function automatic int down_weight(input int row,column);return (row+column)%7+1;endfunction

  always @(posedge clk) begin: memory_peer
    logic [63:0] offset,base;
    int incoming_kind,row,column;
    if(!rst_n) begin cycle<=0;memory_active<=0;rsp_valid<=0;request_held=0;end
    else begin
      cycle<=cycle+1;
      if(out_valid && (memory_active || rsp_valid)) $fatal(1,"JOINED_RESULT_BEFORE_MEMORY_DRAIN");
      if(request_held && (req_valid!==1 || {req_address,req_length}!==held_request)) $fatal(1,"JOINED_CHANGED_MEMORY_OFFER");
      request_held=req_valid && !req_ready;held_request={req_address,req_length};
      if(req_valid && req_ready) begin
        if(req_length==0 || req_length>16 || req_address[2:0]!=0) $fatal(1,"JOINED_BAD_MEMORY_REQUEST");
        incoming_kind=req_address>=UpBase?3:req_address>=GateBase?1:req_address>=ActBase?0:2;
        if(incoming_kind==0) begin
          if({1'b0,req_address}+65'(req_length*8)>{1'b0,ActBase}+65'(features*8)) $fatal(1,"JOINED_ACTIVATION_PADDING");
        end else if(incoming_kind==2) begin
          offset=req_address-DownBase;row=int'(offset/64'(dense));column=int'(offset%64'(dense));
          if(req_address<DownBase || row>=outputs || req_length!=1) $fatal(1,"JOINED_BAD_DOWN_ADDRESS");
        end else begin
          base=incoming_kind==3?UpBase:GateBase;offset=req_address-base;
          row=int'(offset/64'(features*8));column=int'(offset%64'(features*8));
          if(row>=dense || !keep(row,pattern) || column+int'(req_length)*8>features*8) $fatal(1,"JOINED_FETCHED_PRUNED_OR_PADDING_ROW");
        end
        address<=req_address;length<=int'(req_length);beat<=0;kind<=incoming_kind;memory_active<=1;requests++;
        if(inject_up && incoming_kind==3 && !error_fired) begin rsp_error<=1;error_fired=1;end
        else rsp_error<=0;
      end
      if(memory_active && !rsp_valid && cycle%3!=0) begin
        rsp_valid<=1;rsp_last<=beat==length-1;
        for(int lane=0;lane<8;lane++) begin
          offset=address-DownBase+64'(beat*8+lane);
          if(kind==2) rsp_data[lane*8+:8]<=8'(down_weight(int'(offset/64'(dense)),int'(offset%64'(dense))));
          else rsp_data[lane*8+:8]<=kind==0?8'd16:8'd8;
        end
      end
      if(rsp_valid && rsp_ready) begin rsp_valid<=0;beat<=beat+1;if(rsp_last) memory_active<=0;end
    end
  end

  always @(posedge clk) begin: scoreboard
    int amount,value;
    if(!rst_n) held=0;
    else begin
      if(held && (!out_valid || {out_last,out_error,out_fallback,out_tag,out_start,out_count,out_data}!==held_output))
        $fatal(1,"JOINED_STALLED_OUTPUT_CHANGED");
      if(out_valid && !out_ready) begin
        held_output={out_last,out_error,out_fallback,out_tag,out_start,out_count,out_data};
        if(out_error) error_stalls++;else success_stalls++;
      end
      held=out_valid && !out_ready;
    end
    if(rst_n && out_valid && out_ready) begin
      if(out_tag!==tag || out_error!==expect_error || out_fallback!==0) $fatal(1,"JOINED_FRAME_METADATA");
      if(out_error) begin
        if(out_last!==1 || out_count!==0 || out_start!==0 || out_data!==0) $fatal(1,"JOINED_ERROR_PACKET");
        completed++;frame_done=1;
      end else begin
        amount=outputs-seen>160?160:outputs-seen;
        if(out_start!==16'(seen) || out_count!==8'(amount) || out_last!==(seen+amount==outputs)) $fatal(1,"JOINED_OUTPUT_SHAPE");
        for(int row=0;row<160;row++) begin
          value=row<amount?int'(golden[seen+row]):0;
          if($test$plusargs("CORRUPT_JOINED_REFERENCE") && row==0) value++;
          if(out_data[row*32+:32]!==32'(value)) $fatal(1,"JOINED_HIDDEN_SUM row=%0d got=%0d expected=%0d",seen+row,$signed(out_data[row*32+:32]),value);
        end
        seen+=amount;hidden_checked+=amount;
        if(out_last) begin completed++;frame_done=1;end
      end
    end
  end

  task automatic configure(input int h,n,mode,input bit error_expected=0,input int strips=3);
    begin
      @(negedge clk);while(!cfg_ready) @(negedge clk);
      outputs=h;dense=n;pattern=mode;features=strips;seen=0;requests=0;expect_error=error_expected;frame_done=0;
      if(error_expected) force_hold=1;
      inject_up=0;error_fired=0;tag=32'h10100000+32'(completed);
      for(int row=0;row<2400;row++) begin
        golden[row]=0;
        if(row<h) for(int col=0;col<n;col++) if(keep(col,mode)) golden[row]+=127*down_weight(row,col);
      end
      cfg_tag=tag;cfg_activation_base=ActBase;cfg_weight_base=GateBase;cfg_up_weight_base=UpBase;cfg_down_weight_base=DownBase;
      cfg_features=10'(strips);cfg_dense_features=17'(n);cfg_output_count=16'(h);cfg_gate_shift=0;cfg_up_shift=0;cfg_down_shift=8;
      cfg_valid=1;@(posedge clk);if(!cfg_ready) $fatal(1,"JOINED_CONFIG_NOT_ACCEPTED");
      @(negedge clk);cfg_valid=0;cfg_tag='1;cfg_activation_base=0;cfg_weight_base=0;cfg_up_weight_base=0;cfg_down_weight_base=0;
      cfg_features=0;cfg_dense_features=0;cfg_output_count=0;cfg_gate_shift='1;cfg_up_shift='1;cfg_down_shift='1;
    end
  endtask
  task automatic group(input int g,input bit malformed=0);
    begin
      for(int strip=0;strip<features;strip++) begin
        @(negedge clk);in_valid=1;in_last=strip==features-1;in_group=11'(malformed?g+1:g);in_group_last=g==dense/32-1;
        norm_activations={8{16'd1024}};
        for(int row=0;row<32;row++) begin
          gate_weight_signs[row*8+:8]=keep(g*32+row,pattern)?8'h00:8'h55;
          up_weight_signs[row*8+:8]=gate_weight_signs[row*8+:8];
        end
        @(posedge clk);while(!in_ready) @(posedge clk);
        @(negedge clk);in_valid=0;in_group='1;norm_activations='1;gate_weight_signs='1;up_weight_signs='1;
      end
    end
  endtask
  task automatic send_frame;
    for(int g=0;g<dense/32;g++) group(g);
  endtask
  task automatic finish_frame(input bit no_memory=0);
    int timeout;
    begin
      if(expect_error) begin wait(out_valid);repeat(9) @(negedge clk);force_hold=0;end
      timeout=0;while(!frame_done && timeout<3000000) begin @(negedge clk);timeout++;end
      if(!frame_done) $fatal(1,"JOINED_COMPLETION_TIMEOUT");
      if(no_memory && requests!=0) $fatal(1,"JOINED_EMPTY_OR_INVALID_READ_MEMORY");
      if(inject_up && !error_fired) $fatal(1,"JOINED_UP_ERROR_NOT_EXERCISED");
      $display("JOINED_CASE_PASS case=%0d outputs=%0d error=%0d requests=%0d",completed,seen,expect_error,requests);$fflush();
    end
  endtask
  initial begin
    repeat(3) @(negedge clk);
    if(core_instances!=20 || cluster_instances!=5 || weight_mask_memories!=360 || activation_memories!=40 || result_memories!=200)
      $fatal(1,"JOINED_ACTUAL_HIERARCHY");
    $display("JOINED_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=600");rst_n=1;
    configure(129,64,0);send_frame();finish_frame();
    if($test$plusargs("CORRUPT_JOINED_REFERENCE")) $fatal(1,"JOINED_WRONG_REFERENCE_ACCEPTED");
    configure(161,192,1);send_frame();finish_frame();
    configure(2048,64,0);send_frame();finish_frame();
    configure(2048,5632,3,0,256);send_frame();finish_frame();
    configure(1,64,2);send_frame();finish_frame(1);
    configure(160,64,0,1,0);finish_frame(1);
    // The two children reject different configuration subsets. Neither may
    // leave the other waiting forever for a configuration or packet.
    configure(160,24,0,1);finish_frame(1);
    configure(0,64,0,1);finish_frame(1);
    configure(160,64,0,1);group(0,1);finish_frame(1);
    configure(161,320,1,1);for(int g=0;g<6;g++) group(g);
    wait(memory_active);
    if(dut.numeric.in_ready) $fatal(1,"JOINED_LATE_ERROR_NUMERIC_NOT_BUSY");
    group(6,1);finish_frame();
    if(requests==0) $fatal(1,"JOINED_LATE_PREDICTION_ERROR_NOT_EXERCISED");
    configure(129,64,0,1);inject_up=1;send_frame();finish_frame();
    configure(2048,192,1);send_frame();wait(memory_active);
    @(negedge clk);rst_n=0;repeat(3) @(negedge clk);rst_n=1;
    configure(33,64,1);send_frame();finish_frame();
    if(completed!=12 || hidden_checked!=4420 || success_stalls==0 || error_stalls==0) $fatal(1,"JOINED_CASE_INVENTORY");
    $display("JOINED_PASS cases=%0d hidden_outputs=%0d success_stalls=%0d error_stalls=%0d",completed,hidden_checked,success_stalls,error_stalls);$finish;
  end
  initial begin #200000000;$fatal(1,"JOINED_WATCHDOG");end
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
