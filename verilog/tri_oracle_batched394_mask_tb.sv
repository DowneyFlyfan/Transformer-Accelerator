`timescale 1ns/1ps
// Complete feedforward reference through one native compute fabric. Literal
// controls check both tails and errors; trained mode uses all original rows.
module tri_oracle_batched394_mask_tb;
  parameter int FAULT=0,HIDDEN=64,INTERMEDIATE=96,OUTPUTS=173,TOKENS=3;
  parameter bit TRAINED=0,HONOR_CANCEL=1;
  localparam int GATE_GROUPS=(INTERMEDIATE+79)/80,OUTPUT_GROUPS=(OUTPUTS+159)/160;
  localparam logic [63:0] ACT_BASE=64'h00000001ffffc000;
  localparam logic [63:0] GATE_BASE=64'h00000003fffff000;
  localparam logic [63:0] UP_BASE=64'h00000005fffff000;
  localparam logic [63:0] DOWN_BASE=64'h00000007fffff000;
  localparam logic [63:0] SCRATCH_BASE=64'h00000009ffffff80;
  logic clk=0;always #5 clk=~clk;
  logic rst_n=0,cfg_valid=0,done_ready=0;
  wire cfg_ready,done_valid,done_error;
  logic [31:0] cfg_tag=0;
  logic [4:0] cfg_tokens=0;
  logic [15:0] cfg_input_features=0,cfg_intermediate_features=0;
  logic [16:0] cfg_output_features=0;
  logic [63:0] cfg_activation_base=0,cfg_gate_base=0,cfg_up_base=0,cfg_down_base=0,cfg_intermediate_base=0;
  logic [31:0] cfg_activation_stride=0;
  logic [95:0] cfg_gate_shifts=0,cfg_up_shifts=0,cfg_down_shifts=0;
  logic mask_valid=0,mask_last=0;
  wire mask_ready;
  logic [31:0] mask_tag=0;
  logic [15:0] mask_start=0;
  logic [6:0] mask_count=0;
  logic [1279:0] mask_bits=0;
  wire out_valid,out_last;
  wire [31:0] out_tag,done_tag;
  wire [3:0] out_token;
  wire [15:0] out_start;
  wire [7:0] out_count;
  wire [5119:0] out_data;
  int cycle=0,seen=0,stalls=0,first_hold=0;
  bit hold_done=0,inject_fault=FAULT!=0,fault_seen=0;
  wire out_ready=hold_done && cycle%11>=5;
  wire req_valid,rsp_ready;
  wire [63:0] req_address;
  wire [4:0] req_length;
  bit read_active=0,read_bubble=0;
  logic [63:0] read_address=0;
  int read_beat=0,read_length=0,read_requests=0,read_beats=0;
  wire req_ready=!read_active && cycle%7>=3;
  wire rsp_valid=read_active && !read_bubble;
  wire rsp_last=read_beat+1==read_length;
  wire rsp_error=inject_fault && !fault_seen &&
     ((FAULT==2 && read_address>=DOWN_BASE && read_address<DOWN_BASE+64'(OUTPUTS*INTERMEDIATE)) ||
      (FAULT==3 && read_address>=DOWN_BASE+64'(160*INTERMEDIATE) && read_address<DOWN_BASE+64'(OUTPUTS*INTERMEDIATE)));
  logic [63:0] rsp_data;
  wire wr_req_valid,wr_data_valid,wr_data_last,wr_rsp_ready;
  wire [63:0] wr_address,wr_data;
  wire [4:0] wr_length;
  wire [7:0] wr_strobe;
  bit write_active=0,write_response=0;
  logic [63:0] write_address=0;
  int write_beat=0,write_length=0,response_delay=0,write_requests=0,write_bytes=0;
  wire wr_req_ready=!write_active && !write_response && response_delay==0 && cycle%5>=2;
  wire wr_data_ready=write_active && cycle%7!=0;
  wire wr_rsp_valid=write_response;
  wire wr_rsp_error=inject_fault && FAULT==1 && !fault_seen;
  byte unsigned scratch[TOKENS*INTERMEDIATE];
  bit committed[TOKENS*INTERMEDIATE];
  int writes[TOKENS*INTERMEDIATE],scratch_reads[TOKENS*INTERMEDIATE/8];
  int golden_down[TOKENS][INTERMEDIATE],golden[TOKENS][OUTPUTS];
  byte unsigned fixture_activation[TOKENS*HIDDEN],fixture_gate[INTERMEDIATE*HIDDEN],fixture_up[INTERMEDIATE*HIDDEN];
  byte unsigned fixture_down[OUTPUTS*INTERMEDIATE],fixture_keep[TOKENS*INTERMEDIATE],fixture_shifts[TOKENS*3];
  byte unsigned fixture_intermediate[TOKENS*INTERMEDIATE];
  logic [31:0] fixture_output[TOKENS*OUTPUTS];
  string fixture;
  bit held_read_req=0,held_write_req=0,held_write_data=0,held_output=0,held_mask=0;
  logic [1335:0] prior_mask;
  int held_mask_cycles=0,cancelled_masks=0;
  logic [68:0] prior_read_req,prior_write_req;
  logic [72:0] prior_write_data;
  logic [5280:0] prior_output;
  tri_oracle_batched_frame393 dut(.*);

  function automatic int activation(input int token,feature);
    if(TRAINED)return int'($signed(fixture_activation[token*HIDDEN+feature]));
    return (token*7+feature*3)%19-9;
  endfunction
  function automatic int gate_weight(input int channel,feature);
    if(TRAINED)return int'($signed(fixture_gate[channel*HIDDEN+feature]));
    return (channel*3+feature*5)%23-11;
  endfunction
  function automatic int up_weight(input int channel,feature);
    if(TRAINED)return int'($signed(fixture_up[channel*HIDDEN+feature]));
    return (channel*5+feature*7)%29-14;
  endfunction
  function automatic int down_weight(input int output_row,channel);
    if(TRAINED)return int'($signed(fixture_down[output_row*INTERMEDIATE+channel]));
    return (output_row*7+channel*11)%17-8;
  endfunction
  function automatic bit kept(input int token,channel);
    if(TRAINED)return fixture_keep[token*INTERMEDIATE+channel]!=0;
    return channel!=7 && (token+channel)%5!=0;
  endfunction
  function automatic int shift_gate(input int token);return TRAINED ? int'(fixture_shifts[token*3]) : token;endfunction
  function automatic int shift_up(input int token);return TRAINED ? int'(fixture_shifts[token*3+1]) : token==0 ? 2 : token==1 ? 3 : 1;endfunction
  function automatic int shift_down(input int token);return TRAINED ? int'(fixture_shifts[token*3+2]) : token==0 ? 2 : token==1 ? 0 : 4;endfunction
  function automatic int quant(input longint signed value,input int shift,bits);
    longint signed magnitude,rounded,limit;
    magnitude=value<0 ? -value : value;
    rounded=shift==0 ? magnitude : (magnitude+(64'sd1<<(shift-1)))>>shift;
    if(value<0)rounded=-rounded;
    limit=64'sd1<<(bits-1);
    return int'(rounded>=limit ? limit-1 : rounded< -limit ? -limit : rounded);
  endfunction
  function automatic int sample(input int index);
    real x,y;
    x=-8.0+real'(index)/16.0;y=256.0*x/(1.0+$exp(-x));
    return y>=0 ? $rtoi(y+0.5) : -$rtoi(-y+0.5);
  endfunction
  function automatic int silu(input int value);
    int position,index,remainder;
    if(value<=-2048)return 0;
    if(value>=2048)return value;
    position=value+2048;index=position/16;remainder=position%16;
    return quant(sample(index)*(16-remainder)+sample(index+1)*remainder,4,16);
  endfunction
  always_comb begin: read_word
    logic [63:0] current;
    int offset,token,row,feature;
    current=read_address+64'(read_beat*8);rsp_data=0;
    if(current>=ACT_BASE && current<ACT_BASE+64'(TOKENS*HIDDEN))begin
      offset=int'(current-ACT_BASE);token=offset/HIDDEN;feature=offset%HIDDEN;
      for(int b=0;b<8;b++)rsp_data[b*8+:8]=8'(activation(token,feature+b));
    end else if(current>=GATE_BASE && current<GATE_BASE+64'(INTERMEDIATE*HIDDEN))begin
      offset=int'(current-GATE_BASE);row=offset/HIDDEN;feature=offset%HIDDEN;
      for(int b=0;b<8;b++)rsp_data[b*8+:8]=8'(gate_weight(row,feature+b));
    end else if(current>=UP_BASE && current<UP_BASE+64'(INTERMEDIATE*HIDDEN))begin
      offset=int'(current-UP_BASE);row=offset/HIDDEN;feature=offset%HIDDEN;
      for(int b=0;b<8;b++)rsp_data[b*8+:8]=8'(up_weight(row,feature+b));
    end else if(current>=DOWN_BASE && current<DOWN_BASE+64'(OUTPUTS*INTERMEDIATE))begin
      offset=int'(current-DOWN_BASE);row=offset/INTERMEDIATE;feature=offset%INTERMEDIATE;
      for(int b=0;b<8;b++)rsp_data[b*8+:8]=8'(down_weight(row,feature+b));
    end else if(current>=SCRATCH_BASE && current<SCRATCH_BASE+64'(TOKENS*INTERMEDIATE))begin
      offset=int'(current-SCRATCH_BASE);
      for(int b=0;b<8;b++)rsp_data[b*8+:8]=scratch[offset+b];
    end
  end
  task automatic configure;
    @(negedge clk);cfg_tag=32'h39300001;cfg_tokens=TOKENS;cfg_input_features=HIDDEN;
    cfg_intermediate_features=INTERMEDIATE;cfg_output_features=OUTPUTS;
    cfg_activation_base=ACT_BASE;cfg_gate_base=GATE_BASE;cfg_up_base=UP_BASE;cfg_down_base=DOWN_BASE;
    cfg_intermediate_base=SCRATCH_BASE;cfg_activation_stride=HIDDEN;
    if(inject_fault && FAULT==5)cfg_intermediate_base=ACT_BASE;
    if(inject_fault && FAULT==6)cfg_intermediate_base=64'hffffffffffffff80;
    for(int token=0;token<TOKENS;token++)begin
      cfg_gate_shifts[token*6+:6]=6'(shift_gate(token));cfg_up_shifts[token*6+:6]=6'(shift_up(token));
      cfg_down_shifts[token*6+:6]=6'(shift_down(token));
    end
    cfg_valid=1;@(posedge clk);if(!cfg_ready)$fatal(1,"BATCH394_CONFIG_NOT_ACCEPTED");
    @(negedge clk);cfg_valid=0;cfg_tag='1;cfg_tokens='1;cfg_input_features='1;cfg_intermediate_features='1;
    cfg_output_features='1;cfg_activation_base='1;cfg_gate_base='1;cfg_up_base='1;cfg_down_base='1;
    cfg_intermediate_base='1;cfg_activation_stride='1;cfg_gate_shifts='1;cfg_up_shifts='1;cfg_down_shifts='1;
  endtask
  task automatic send_masks;
    int count;
    for(int start=0;start<INTERMEDIATE;start+=80)begin
      @(negedge clk);
      count=INTERMEDIATE-start>80 ? 80 : INTERMEDIATE-start;
      mask_tag=32'h39300001;mask_start=16'(start+(inject_fault && FAULT==4 ? 1 : 0));
      mask_count=7'(count);mask_last=start+count==INTERMEDIATE;mask_bits=0;
      for(int token=0;token<TOKENS;token++)for(int row=0;row<count;row++)mask_bits[token*80+row]=kept(token,start+row);
      // A producer can offer a packet while the current tile is still busy.
      // A tagged terminal error cancels the unaccepted offer before done ACK.
      mask_valid=1;
      while(!mask_ready)begin
        if(done_valid)begin
          if(!done_error || done_tag!==mask_tag || held_mask_cycles==0 || mask_start!=80)
            $fatal(1,"BATCH394_INVALID_MASK_CANCELLATION");
          if(HONOR_CANCEL)begin
            mask_valid=0;cancelled_masks++;
            $display("BATCH394_MASK_CANCELLED start=%0d held_cycles=%0d",mask_start,held_mask_cycles);
          end
          return;
        end
        @(negedge clk);
      end
      @(posedge clk);if(!mask_ready)$fatal(1,"BATCH394_MASK_NOT_ACCEPTED");
      $display("BATCH394_MASK_ACCEPTED start=%0d count=%0d",mask_start,mask_count);
      @(negedge clk);mask_valid=0;mask_tag='1;mask_start='1;mask_count='1;mask_last=0;mask_bits='1;
    end
  endtask
  always @(posedge clk)if(rst_n)begin: bus_and_scoreboard
    logic [63:0] current;
    int offset,row,token,expected_start,expected_token,expected_count;
    cycle<=cycle+1;
    if(held_mask && !(done_valid && done_error && done_tag==prior_mask[1335:1304]) &&
       (!mask_valid || {mask_tag,mask_start,mask_count,mask_last,mask_bits}!==prior_mask))
      $fatal(1,"BATCH394_MASK_CHANGED_UNDER_STALL");
    held_mask=mask_valid && !mask_ready;
    if(held_mask)begin prior_mask={mask_tag,mask_start,mask_count,mask_last,mask_bits};held_mask_cycles++;end
    if(read_active && read_bubble)read_bubble<=0;
    if(req_valid && req_ready)begin
      if(read_active || req_length==0 || req_length>16 || req_address[2:0]!=0)$fatal(1,"BATCH394_READ_REQUEST");
      if(req_address>=SCRATCH_BASE && req_address<SCRATCH_BASE+64'(TOKENS*INTERMEDIATE))begin
        offset=int'(req_address-SCRATCH_BASE);
        for(int b=0;b<int'(req_length)*8;b++)if(!committed[offset+b])$fatal(1,"BATCH394_READ_BEFORE_WRITE_ACK");
      end else if(!((req_address>=ACT_BASE && req_address<ACT_BASE+64'(TOKENS*HIDDEN)) ||
           (req_address>=GATE_BASE && req_address<GATE_BASE+64'(INTERMEDIATE*HIDDEN)) ||
           (req_address>=UP_BASE && req_address<UP_BASE+64'(INTERMEDIATE*HIDDEN)) ||
           (req_address>=DOWN_BASE && req_address<DOWN_BASE+64'(OUTPUTS*INTERMEDIATE))))$fatal(1,"BATCH394_UNKNOWN_READ_ADDRESS %h",req_address);
      read_active<=1;read_address<=req_address;read_beat<=0;read_length<=int'(req_length);read_bubble<=0;read_requests++;
    end
    if(rsp_valid && rsp_ready)begin
      current=read_address+64'(read_beat*8);read_beats++;
      if(current>=SCRATCH_BASE && current<SCRATCH_BASE+64'(TOKENS*INTERMEDIATE))scratch_reads[int'(current-SCRATCH_BASE)/8]++;
      if(rsp_error)fault_seen<=1;
      if(rsp_last)read_active<=0;else begin read_beat<=read_beat+1;read_bubble<=cycle%5==0;end
    end
    if(wr_req_valid && wr_req_ready)begin
      if(write_active || write_response || wr_length==0 || wr_length>10 || wr_address[2:0]!=0 ||
         wr_address<SCRATCH_BASE || wr_address+64'(wr_length)*8>SCRATCH_BASE+64'(TOKENS*INTERMEDIATE))$fatal(1,"BATCH394_WRITE_REQUEST");
      offset=int'(wr_address-SCRATCH_BASE);
      row=offset%INTERMEDIATE;
      if(row%80!=0 || int'(wr_length)*8!=(INTERMEDIATE-row>80 ? 80 : INTERMEDIATE-row))$fatal(1,"BATCH394_WRITE_TILE_ADDRESS");
      write_active<=1;write_address<=wr_address;write_beat<=0;write_length<=int'(wr_length);write_requests++;
    end
    if(wr_data_valid && wr_data_ready)begin
      if(!write_active || wr_strobe!==8'hff || wr_data_last!==(write_beat+1==write_length))$fatal(1,"BATCH394_WRITE_DATA_PROTOCOL");
      offset=int'(write_address-SCRATCH_BASE)+write_beat*8;
      for(int b=0;b<8;b++)begin
        token=(offset+b)/INTERMEDIATE;row=(offset+b)%INTERMEDIATE;
        if(wr_data[b*8+:8]!==8'(golden_down[token][row]))$fatal(1,"BATCH394_GATED_INTERMEDIATE token=%0d channel=%0d",token,row);
        scratch[offset+b]=wr_data[b*8+:8];writes[offset+b]++;write_bytes++;
      end
      if(wr_data_last)begin write_active<=0;response_delay<=3;end
      else write_beat<=write_beat+1;
    end
    if(response_delay>0)begin response_delay<=response_delay-1;if(response_delay==1)write_response<=1;end
    if(wr_rsp_valid && wr_rsp_ready)begin
      if(wr_rsp_error)fault_seen<=1;
      else for(int b=0;b<write_length*8;b++)committed[int'(write_address-SCRATCH_BASE)+b]=1;
      write_response<=0;
    end
    if(held_read_req && (!req_valid || {req_address,req_length}!==prior_read_req))$fatal(1,"BATCH394_READ_REQUEST_CHANGED");
    held_read_req=req_valid && !req_ready;if(held_read_req)prior_read_req={req_address,req_length};
    if(held_write_req && (!wr_req_valid || {wr_address,wr_length}!==prior_write_req))$fatal(1,"BATCH394_WRITE_REQUEST_CHANGED");
    held_write_req=wr_req_valid && !wr_req_ready;if(held_write_req)prior_write_req={wr_address,wr_length};
    if(held_write_data && (!wr_data_valid || {wr_data,wr_strobe,wr_data_last}!==prior_write_data))$fatal(1,"BATCH394_WRITE_DATA_CHANGED");
    held_write_data=wr_data_valid && !wr_data_ready;if(held_write_data)prior_write_data={wr_data,wr_strobe,wr_data_last};
    if(out_valid && !hold_done)begin first_hold<=first_hold+1;if(first_hold==3)hold_done<=1;end
    if(held_output && (!out_valid || {out_tag,out_token,out_start,out_count,out_last,out_data}!==prior_output))$fatal(1,"BATCH394_OUTPUT_CHANGED");
    held_output=out_valid && !out_ready;
    if(held_output)begin prior_output={out_tag,out_token,out_start,out_count,out_last,out_data};stalls++;end
    if(out_valid && out_ready)begin
      expected_start=(seen/TOKENS)*160;expected_token=seen%TOKENS;expected_count=OUTPUTS-expected_start>160 ? 160 : OUTPUTS-expected_start;
      if(seen>=OUTPUT_GROUPS*TOKENS || out_tag!==32'h39300001 || out_token!==4'(expected_token) || out_start!==16'(expected_start) || out_count!==8'(expected_count) ||
         out_last!==(expected_start+expected_count==OUTPUTS && expected_token==TOKENS-1))$fatal(1,"BATCH394_OUTPUT_METADATA");
      for(int column=0;column<expected_count;column++)
        if(out_data[column*32+:32]!==32'(golden[expected_token][expected_start+column]))
          $fatal(1,"BATCH394_OUTPUT_INTEGER token=%0d row=%0d got=%0d expected=%0d",expected_token,expected_start+column,$signed(out_data[column*32+:32]),golden[expected_token][expected_start+column]);
      for(int column=expected_count;column<160;column++)if(out_data[column*32+:32]!==0)$fatal(1,"BATCH394_NONZERO_PADDED_OUTPUT");
      if(expected_token==TOKENS-1)$display("BATCH394_OUTPUT_TILE start=%0d count=%0d",expected_start,expected_count);
      seen++;
    end
    if($isunknown({cfg_ready,mask_ready,req_valid,rsp_ready,wr_req_valid,wr_data_valid,wr_rsp_ready,out_valid,done_valid}))$fatal(1,"BATCH394_UNKNOWN_PROTOCOL");
  end
  initial begin: stimulus
    int gate_dot,up_dot,gated;
    foreach(committed[i])begin committed[i]=0;writes[i]=0;end
    foreach(scratch_reads[i])scratch_reads[i]=0;
    if(TRAINED)begin
      if(!$value$plusargs("FIXTURE=%s",fixture))$fatal(1,"BATCH394_FIXTURE_REQUIRED");
      $readmemh({fixture,"/activation.hex"},fixture_activation);$readmemh({fixture,"/gate.hex"},fixture_gate);
      $readmemh({fixture,"/up.hex"},fixture_up);$readmemh({fixture,"/down.hex"},fixture_down);
      $readmemh({fixture,"/keep.hex"},fixture_keep);$readmemh({fixture,"/shifts.hex"},fixture_shifts);
      $readmemh({fixture,"/intermediate.hex"},fixture_intermediate);$readmemh({fixture,"/expected.hex"},fixture_output);
      for(int token=0;token<TOKENS;token++)begin
        for(int channel=0;channel<INTERMEDIATE;channel++)golden_down[token][channel]=int'($signed(fixture_intermediate[token*INTERMEDIATE+channel]));
        for(int row=0;row<OUTPUTS;row++)golden[token][row]=int'($signed(fixture_output[token*OUTPUTS+row]));
      end
    end else for(int token=0;token<TOKENS;token++)begin
      for(int channel=0;channel<INTERMEDIATE;channel++)begin
        gate_dot=0;up_dot=0;
        for(int feature=0;feature<HIDDEN;feature++)begin
          gate_dot+=activation(token,feature)*gate_weight(channel,feature);up_dot+=activation(token,feature)*up_weight(channel,feature);
        end
        gated=quant(silu(quant(gate_dot,shift_gate(token),16))*quant(up_dot,shift_up(token),16),8,16);
        golden_down[token][channel]=kept(token,channel) ? quant(gated,shift_down(token),8) : 0;
      end
      for(int row=0;row<OUTPUTS;row++)begin
        golden[token][row]=0;
        for(int channel=0;channel<INTERMEDIATE;channel++)golden[token][row]+=golden_down[token][channel]*down_weight(row,channel);
      end
    end
    repeat(3)@(negedge clk);rst_n=1;configure();
    fork send_masks();wait(done_valid);join
    if(inject_fault)begin
      repeat(4)begin
        @(negedge clk);if(!done_valid || !done_error || done_tag!==32'h39300001 || read_active || write_active || write_response || response_delay!=0)
          $fatal(1,"BATCH394_FAULT_OWNERSHIP");
      end
      if((FAULT<4 && !fault_seen) || seen!=(FAULT==3 ? TOKENS : 0) || (FAULT>=4 && (read_requests!=0 || write_requests!=0)))$fatal(1,"BATCH394_EXPECTED_FAULT_PHASE");
      $display("BATCH394_FAULT_DRAINED fault=%0d output_prefix_packets=%0d",FAULT,seen);
      if(FAULT==1 && HONOR_CANCEL && (cancelled_masks!=1 || mask_valid))$fatal(1,"BATCH394_MASK_CANCEL_NOT_COMPLETE");
      if(FAULT==1 && !HONOR_CANCEL && (!mask_valid || mask_start!=80))$fatal(1,"BATCH394_STALE_OFFER_MISSING");
      done_ready=1;@(posedge clk);@(negedge clk);done_ready=0;
      if(FAULT==1 && !HONOR_CANCEL)begin
        configure();wait(done_valid);
        if(done_error && done_tag==32'h39300001 && mask_start==80)
          $fatal(1,"BATCH394_STALE_MASK_REJECTED_AFTER_IGNORED_CANCEL");
        $fatal(1,"BATCH394_IGNORED_CANCEL_WRONG_RESULT");
      end
      inject_fault=0;seen=0;read_requests=0;read_beats=0;write_requests=0;write_bytes=0;
      foreach(committed[i])begin committed[i]=0;writes[i]=0;end
      foreach(scratch_reads[i])scratch_reads[i]=0;
      configure();fork send_masks();wait(done_valid);join
    end
    repeat(4)begin
      @(negedge clk);if(!done_valid || done_error || done_tag!==32'h39300001 || read_active || write_active || write_response || response_delay!=0)
        $fatal(1,"BATCH394_DONE_METADATA");
    end
    if(seen!=OUTPUT_GROUPS*TOKENS || write_requests!=GATE_GROUPS*TOKENS || write_bytes!=TOKENS*INTERMEDIATE || first_hold!=4 || stalls<4)$fatal(1,"BATCH394_FINAL_INVENTORY");
    foreach(committed[i])if(!committed[i] || writes[i]!=1)$fatal(1,"BATCH394_INTERMEDIATE_WRITE_COUNT");
    foreach(scratch_reads[i])if(scratch_reads[i]!=OUTPUT_GROUPS)$fatal(1,"BATCH394_INTERMEDIATE_READ_COUNT");
    done_ready=1;@(posedge clk);@(negedge clk);done_ready=0;if(!cfg_ready)$fatal(1,"BATCH394_OWNER_NOT_RELEASED");
    if(held_mask_cycles==0 || cancelled_masks!=(FAULT==1 ? 1 : 0))$fatal(1,"BATCH394_MASK_FLOW_COVERAGE");
    $display("BATCH394_MASK_FLOW held_cycles=%0d cancelled=%0d",held_mask_cycles,cancelled_masks);
    $display("BATCH394_PASS tokens=%0d hidden=%0d intermediate=%0d outputs=%0d exact_outputs=%0d intermediate_bytes=%0d output_packets=%0d read_requests=%0d read_bytes=%0d fault=%0d trained=%0d",TOKENS,HIDDEN,INTERMEDIATE,OUTPUTS,TOKENS*OUTPUTS,write_bytes,seen,read_requests,read_beats*8,FAULT,TRAINED);$finish;
  end
  initial begin #(TRAINED ? 300000000 : 15000000);$fatal(1,"BATCH394_WATCHDOG");end
endmodule
