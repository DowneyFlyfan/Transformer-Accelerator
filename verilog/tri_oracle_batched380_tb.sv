`timescale 1ns/1ps
// Trained gate/up pairing, per-token precision and nonlinear outputs. The bus
// scoreboard checks all original addresses and every activation/weight read.
module tri_oracle_batched380_tb;
  parameter int TOKENS=16, CASE=0;
  localparam int HIDDEN=2048,ROWS=80,DENSE=5632;
  localparam logic [63:0] ACT_BASE=64'h00000001ffffc000;
  localparam logic [63:0] GATE_BASE=64'h00000003ffff8000;
  localparam logic [63:0] UP_BASE=64'h00000005ffff8000;
  logic clk=0;always #5 clk=~clk;
  logic rst_n=0,cfg_valid=0,done_ready=0;
  wire cfg_ready,out_valid,out_last,done_valid,done_error;
  logic [31:0] cfg_tag=0;
  logic [4:0] cfg_tokens=0;
  logic [9:0] cfg_feature_words=0;
  logic [16:0] cfg_dense_rows=0;
  logic [6:0] cfg_count=0;
  logic [1279:0] cfg_channels=0,cfg_keep=0;
  logic [63:0] cfg_activation_base=0,cfg_weight_base=0,cfg_up_weight_base=0;
  logic [31:0] cfg_activation_stride=0;
  logic [95:0] cfg_gate_shifts=0,cfg_up_shifts=0,cfg_down_shifts=0;
  wire [31:0] out_tag,done_tag;
  wire [3:0] out_token;
  wire [6:0] out_count;
  wire [1279:0] out_channels,out_gated;
  wire [639:0] out_down_input;
  wire req_valid,rsp_ready;
  wire [63:0] req_address;
  wire [4:0] req_length;
  int cycle=0,seen=0,seen_raw=0,stalls=0,first_hold=0;
  bit hold_done=0,inject_fault=CASE==1 || CASE==2,up_fault_seen=0;
  wire out_ready=hold_done && cycle%11>=5;
  logic active=0,bubble=0;
  logic [63:0] address=0;
  int beat=0,length=0,requests=0,activation_beats=0,gate_beats=0,up_beats=0;
  wire req_ready=!active && cycle%7>=3;
  wire rsp_valid=active && !bubble;
  wire rsp_last=beat+1==length;
  wire rsp_error=inject_fault && CASE==1 && !up_fault_seen && address>=UP_BASE;
  logic [63:0] rsp_data;
  byte unsigned activations[16*HIDDEN],gate[ROWS*HIDDEN],up[ROWS*HIDDEN],keep[16*ROWS],shifts[48];
  logic [15:0] channels[ROWS],expected_gated[16*ROWS];
  logic [31:0] expected_gate_raw[16*ROWS],expected_up_raw[16*ROWS];
  byte unsigned expected_down[16*ROWS];
  int activation_reads[TOKENS*HIDDEN/8],gate_reads[ROWS*HIDDEN/8],up_reads[ROWS*HIDDEN/8];
  bit union_keep[ROWS],held_request=0,held_output=0;
  logic [68:0] previous_request;
  logic [3243:0] previous_output;
  string fixture;
  tri_oracle_batched_gated380 dut(.*);

  function automatic int row_index(input int original);
    for(int i=0;i<ROWS;i++)if(int'(channels[i])==original)return i;
    return -1;
  endfunction
  always_comb begin: bus_word
    logic [63:0] current;
    int offset,row;
    current=address+64'(beat*8);rsp_data=0;
    if(current>=ACT_BASE && current<ACT_BASE+64'(TOKENS*HIDDEN))begin
      offset=int'(current-ACT_BASE);
      for(int b=0;b<8;b++)rsp_data[b*8+:8]=activations[offset+b];
    end else if(current>=GATE_BASE && current<GATE_BASE+64'(DENSE*HIDDEN))begin
      offset=int'(current-GATE_BASE);row=row_index(offset/HIDDEN);
      if(row>=0)for(int b=0;b<8;b++)rsp_data[b*8+:8]=gate[row*HIDDEN+offset%HIDDEN+b];
    end else if(current>=UP_BASE && current<UP_BASE+64'(DENSE*HIDDEN))begin
      offset=int'(current-UP_BASE);row=row_index(offset/HIDDEN);
      if(row>=0)for(int b=0;b<8;b++)rsp_data[b*8+:8]=up[row*HIDDEN+offset%HIDDEN+b];
    end
  end
  task automatic configure;
    @(negedge clk);cfg_tag=32'h38000001;cfg_tokens=5'(TOKENS);cfg_feature_words=HIDDEN/8;
    cfg_dense_rows=DENSE;cfg_count=ROWS;cfg_activation_base=ACT_BASE;cfg_weight_base=GATE_BASE;
    cfg_up_weight_base=UP_BASE+(inject_fault && CASE==2 ? 1 : 0);cfg_activation_stride=HIDDEN;
    for(int token=0;token<TOKENS;token++)begin
      cfg_gate_shifts[token*6+:6]=6'(shifts[token*3]);
      cfg_up_shifts[token*6+:6]=6'(shifts[token*3+1]);
      cfg_down_shifts[token*6+:6]=6'(shifts[token*3+2]);
      for(int column=0;column<ROWS;column++)cfg_keep[token*80+column]=CASE!=3 && keep[token*ROWS+ROWS-1-column]!=0;
    end
    for(int column=0;column<ROWS;column++)cfg_channels[column*16+:16]=channels[ROWS-1-column];
    cfg_valid=1;@(posedge clk);if(!cfg_ready)$fatal(1,"BATCH380_CONFIG_NOT_ACCEPTED");
    @(negedge clk);cfg_valid=0;cfg_tag='1;cfg_tokens='1;cfg_feature_words='1;cfg_dense_rows='1;
    cfg_count='1;cfg_channels='1;cfg_keep=0;cfg_activation_base='1;cfg_weight_base='1;cfg_up_weight_base='1;
    cfg_activation_stride='1;cfg_gate_shifts='1;cfg_up_shifts='1;cfg_down_shifts='1;
  endtask
  always @(posedge clk)if(rst_n)begin: protocol
    logic [63:0] current;
    int offset,row,kind;
    cycle<=cycle+1;
    if(active && bubble)bubble<=0;
    if(req_valid && req_ready)begin
      if(active || req_length==0 || req_length>16 || req_address[2:0]!=0)$fatal(1,"BATCH380_REQUEST_PROTOCOL");
      if(req_address>=ACT_BASE && req_address<ACT_BASE+64'(TOKENS*HIDDEN))begin
        offset=int'(req_address-ACT_BASE);
      end else begin
        if(req_address>=GATE_BASE && req_address<GATE_BASE+64'(DENSE*HIDDEN))offset=int'(req_address-GATE_BASE);
        else if(req_address>=UP_BASE && req_address<UP_BASE+64'(DENSE*HIDDEN))offset=int'(req_address-UP_BASE);
        else $fatal(1,"BATCH380_UNKNOWN_WEIGHT_BASE");
        row=row_index(offset/HIDDEN);
        if(row<0 || !union_keep[row])$fatal(1,"BATCH380_ORIGINAL_ID_OR_UNION_MASK");
      end
      if(offset%HIDDEN+8*int'(req_length)>HIDDEN)$fatal(1,"BATCH380_BURST_CROSSED_ROW");
      active<=1;address<=req_address;beat<=0;length<=int'(req_length);bubble<=0;requests++;
    end
    if(rsp_valid && rsp_ready)begin
      current=address+64'(beat*8);
      if(current>=ACT_BASE && current<ACT_BASE+64'(TOKENS*HIDDEN))begin
        activation_reads[int'(current-ACT_BASE)/8]++;activation_beats++;
      end else begin
        kind=current>=UP_BASE;
        offset=int'(current-(kind!=0?UP_BASE:GATE_BASE));row=row_index(offset/HIDDEN);
        if(row<0)$fatal(1,"BATCH380_RESPONSE_ORIGINAL_ID");
        if(kind!=0)begin up_reads[(row*HIDDEN+offset%HIDDEN)/8]++;up_beats++;end
        else begin gate_reads[(row*HIDDEN+offset%HIDDEN)/8]++;gate_beats++;end
      end
      if(rsp_error)up_fault_seen<=1;
      if(rsp_last)active<=0;
      else begin beat<=beat+1;bubble<=cycle%5==0;end
    end
    if(held_request && (!req_valid || {req_address,req_length}!==previous_request))$fatal(1,"BATCH380_REQUEST_CHANGED_UNDER_STALL");
    held_request=req_valid && !req_ready;if(held_request)previous_request={req_address,req_length};
    if(out_valid && !hold_done)begin first_hold<=first_hold+1;if(first_hold==3)hold_done<=1;end
    if(held_output && (!out_valid || {out_tag,out_token,out_last,out_count,out_channels,out_gated,out_down_input}!==previous_output))
      $fatal(1,"BATCH380_OUTPUT_CHANGED_UNDER_STALL");
    held_output=out_valid && !out_ready;
    if(held_output)begin previous_output={out_tag,out_token,out_last,out_count,out_channels,out_gated,out_down_input};stalls++;end
    if(dut.projection_valid && dut.projection_out_ready && !inject_fault)begin
      if(seen_raw>=TOKENS || dut.projection_token!==4'(seen_raw))$fatal(1,"BATCH380_RAW_PACKET_ORDER");
      for(int column=0;column<ROWS;column++)begin
        row=(column/16)*32+column%16;
        if(dut.projection_data[row*32+:32]!==32'(CASE==3 ? 0 : expected_gate_raw[seen_raw*ROWS+ROWS-1-column]))
          $fatal(1,"BATCH380_RAW_GATE token=%0d column=%0d",seen_raw,column);
        if(dut.projection_data[(row+16)*32+:32]!==32'(CASE==3 ? 0 : expected_up_raw[seen_raw*ROWS+ROWS-1-column]))
          $fatal(1,"BATCH380_RAW_UP token=%0d column=%0d",seen_raw,column);
      end
      seen_raw++;
    end
    if(out_valid && out_ready)begin
      if(inject_fault || seen>=TOKENS || out_tag!==32'h38000001 || out_token!==4'(seen) || out_last!==(seen==TOKENS-1) || out_count!==7'(ROWS))
        $fatal(1,"BATCH380_OUTPUT_METADATA");
      for(int column=0;column<ROWS;column++)begin
        row=ROWS-1-column;
        if(out_channels[column*16+:16]!==channels[row])$fatal(1,"BATCH380_OUTPUT_CHANNEL");
        if(out_gated[column*16+:16]!==16'(CASE==3 ? 0 : expected_gated[seen*ROWS+row]))
          $fatal(1,"BATCH380_GATED token=%0d row=%0d got=%0d expected=%0d",seen,row,$signed(out_gated[column*16+:16]),$signed(expected_gated[seen*ROWS+row]));
        if(out_down_input[column*8+:8]!==8'(CASE==3 ? 0 : expected_down[seen*ROWS+row]))
          $fatal(1,"BATCH380_DOWN_INPUT token=%0d row=%0d",seen,row);
      end
      seen++;
    end
    if($isunknown({cfg_ready,out_valid,done_valid,req_valid,rsp_ready}))$fatal(1,"BATCH380_UNKNOWN_PROTOCOL");
  end
  initial begin: stimulus
    int rows_kept;
    if(!$value$plusargs("FIXTURE=%s",fixture))$fatal(1,"BATCH380_FIXTURE_REQUIRED");
    $readmemh({fixture,"/activation.hex"},activations);$readmemh({fixture,"/gate.hex"},gate);
    $readmemh({fixture,"/up.hex"},up);$readmemh({fixture,"/keep.hex"},keep);
    $readmemh({fixture,"/channels.hex"},channels);$readmemh({fixture,"/shifts.hex"},shifts);
    $readmemh({fixture,"/gated.hex"},expected_gated);$readmemh({fixture,"/down_input.hex"},expected_down);
    $readmemh({fixture,"/gate_raw.hex"},expected_gate_raw);$readmemh({fixture,"/up_raw.hex"},expected_up_raw);
    rows_kept=0;
    for(int row=0;row<ROWS;row++)begin
      union_keep[row]=0;
      for(int token=0;token<TOKENS;token++)union_keep[row]|=CASE!=3 && keep[token*ROWS+row]!=0;
      if(union_keep[row])rows_kept++;
    end
    foreach(activation_reads[i])activation_reads[i]=0;
    foreach(gate_reads[i])begin gate_reads[i]=0;up_reads[i]=0;end
    repeat(3)@(negedge clk);rst_n=1;configure();
    if(inject_fault)begin
      wait(done_valid);repeat(4)begin
        @(negedge clk);if(!done_valid || !done_error || done_tag!==32'h38000001 || active || rsp_valid || seen!=0)
          $fatal(1,"BATCH380_FAULT_NOT_DRAINED");
      end
      if(CASE==1 && (!up_fault_seen || up_beats!=16 || gate_beats==0 || activation_beats!=TOKENS*256))
        $fatal(1,"BATCH380_UP_ERROR_OWNERSHIP");
      if(CASE==2 && requests!=0)$fatal(1,"BATCH380_INVALID_UP_BASE_ISSUED");
      $display("BATCH380_FAULT_DRAINED case=%0d requests=%0d up_beats=%0d",CASE,requests,up_beats);
      done_ready=1;@(posedge clk);@(negedge clk);done_ready=0;
      inject_fault=0;requests=0;activation_beats=0;gate_beats=0;up_beats=0;
      foreach(activation_reads[i])activation_reads[i]=0;
      foreach(gate_reads[i])begin gate_reads[i]=0;up_reads[i]=0;end
      configure();
    end
    wait(done_valid);repeat(4)begin
      @(negedge clk);if(!done_valid || done_error || done_tag!==32'h38000001 || active || rsp_valid)
        $fatal(1,"BATCH380_DONE_METADATA");
    end
    if(seen!=TOKENS || seen_raw!=TOKENS || first_hold!=4 || stalls<4)$fatal(1,"BATCH380_OUTPUT_INVENTORY");
    foreach(activation_reads[i])if(activation_reads[i]!=1)$fatal(1,"BATCH380_ACTIVATION_REUSE");
    foreach(gate_reads[i])if(gate_reads[i]!=int'(union_keep[i/256]) || up_reads[i]!=int'(union_keep[i/256]))
      $fatal(1,"BATCH380_WEIGHT_REUSE");
    if(requests!=TOKENS*16+rows_kept*32 || activation_beats!=TOKENS*256 || gate_beats!=rows_kept*256 || up_beats!=rows_kept*256)
      $fatal(1,"BATCH380_TRANSFER_INVENTORY");
    done_ready=1;@(posedge clk);@(negedge clk);done_ready=0;
    if(!cfg_ready)$fatal(1,"BATCH380_DID_NOT_RELEASE_OWNER");
    $display("BATCH380_PASS tokens=%0d hidden=2048 rows=80 gated_words=%0d down_words=%0d requests=%0d activation_beats=%0d gate_beats=%0d up_beats=%0d stalls=%0d case=%0d",TOKENS,80*TOKENS,80*TOKENS,requests,activation_beats,gate_beats,up_beats,stalls,CASE);$finish;
  end
  initial begin #12000000;$fatal(1,"BATCH380_WATCHDOG");end
endmodule
