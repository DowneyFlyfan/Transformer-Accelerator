`timescale 1ns/1ps
// Real operand-transfer ownership, original channel IDs and trained arithmetic.
// The independent bus model supplies row-major operands, never core writes.
module tri_oracle_batched373_tb;
  parameter int TOKENS=16;
  parameter int FAULT=0;
  localparam int HIDDEN=2048, ROWS=160;
  localparam logic [63:0] ACTIVATION_BASE=64'h00000001ffffc000;
  localparam logic [63:0] WEIGHT_BASE=64'h00000003ffff8000;
  logic clk=0;
  always #5 clk=~clk;
  logic rst_n=0,cfg_valid=0;
  wire cfg_ready;
  logic [31:0] cfg_tag=0;
  logic [4:0] cfg_tokens=0;
  logic [9:0] cfg_feature_words=0;
  logic [16:0] cfg_dense_rows=0;
  logic [7:0] cfg_count=0;
  logic [2559:0] cfg_channels=0,cfg_keep=0;
  logic [63:0] cfg_activation_base=0,cfg_weight_base=0;
  logic [31:0] cfg_activation_stride=0;
  wire out_valid,out_last,done_valid,done_error;
  wire [31:0] out_tag,done_tag;
  wire [3:0] out_token;
  wire [7:0] out_count;
  wire [2559:0] out_channels;
  wire [5119:0] out_data;
  logic done_ready=0;
  int cycle=0,seen=0,output_stalls=0,first_hold_cycles=0;
  bit first_hold_done=0;
  wire out_ready=first_hold_done && cycle%11>=5;
  wire req_valid,rsp_ready;
  wire [63:0] req_address;
  wire [4:0] req_length;
  logic active=0,bubble=0;
  logic [63:0] address=0;
  int beat=0,length=0,requests=0,activation_beats=0,weight_beats=0;
  wire req_ready=!active && cycle%7>=3;
  wire rsp_valid=active && !bubble;
  bit inject_fault=FAULT!=0;
  wire rsp_last=inject_fault && requests==1 && FAULT==2 ? beat==0 :
                inject_fault && requests==1 && FAULT==3 ? beat==length : beat+1==length;
  wire rsp_error=inject_fault && requests==1 && FAULT==1 && beat==0;
  logic [63:0] rsp_data;
  bit held_request=0,held_output=0;
  logic [68:0] previous_request;
  logic [7724:0] previous_output;
  byte unsigned activations[16*HIDDEN],weights[ROWS*HIDDEN],keep[16*ROWS];
  logic [31:0] expected[16*ROWS];
  int activation_reads[TOKENS*HIDDEN/8],weight_reads[ROWS*HIDDEN/8];
  bit union_keep[ROWS];
  string fixture;
  `ifdef BATCH372_RED_OWNER
  tri_oracle_batched_dma366 dut(.*);
`else
  tri_oracle_batched_dma372 dut(.*);
`endif
  // Inject only in the testbench while an accepted read still owns more beats.
  initial if(FAULT==6)begin
    wait(rst_n && inject_fault && dut.load_valid && dut.load_kind==1);
    @(negedge clk);force dut.load_error=1'b1;
    @(posedge clk);@(negedge clk);release dut.load_error;
  end

  initial if(FAULT==7)begin
    wait(rst_n && inject_fault && req_valid);
    force req_ready=1'b0;
    @(negedge clk);force dut.load_error=1'b1;
    repeat(4)@(posedge clk);
    @(negedge clk);release dut.load_error;release req_ready;
  end
  initial if(FAULT==8)begin
    wait(rst_n && inject_fault && dut.load_valid && dut.load_kind==1 && dut.beat_index==15);
    @(negedge clk);force dut.load_error=1'b1;
    @(posedge clk);@(negedge clk);release dut.load_error;
  end
  task automatic configure;
    @(negedge clk);cfg_tag=32'h36600001;cfg_tokens=5'(inject_fault && FAULT==5 ? 17 : TOKENS);
    cfg_feature_words=10'(HIDDEN/8);cfg_dense_rows=5632;cfg_count=ROWS;
    cfg_activation_base=ACTIVATION_BASE;cfg_weight_base=WEIGHT_BASE;cfg_activation_stride=HIDDEN;
    for(int column=0;column<ROWS;column++)begin
      cfg_channels[column*16+:16]=16'(ROWS-1-column);
      for(int token=0;token<TOKENS;token++)cfg_keep[token*ROWS+column]=keep[token*ROWS+ROWS-1-column]!=0;
    end
    if(inject_fault && FAULT==4)cfg_channels[15:0]=16'd5632;
    cfg_valid=1;@(posedge clk);if(!cfg_ready)$fatal(1,"BATCH373_CONFIG_NOT_ACCEPTED");
    @(negedge clk);cfg_valid=0;cfg_tag='1;cfg_tokens='1;cfg_feature_words='1;cfg_dense_rows='1;
    cfg_count='1;cfg_channels='1;cfg_keep=0;cfg_activation_base='1;cfg_weight_base='1;cfg_activation_stride='1;
  endtask

  always_comb begin: bus_word
    logic [63:0] current;
    int offset;
    current=address+64'(beat*8);
    rsp_data=0;
    if(current>=ACTIVATION_BASE && current<ACTIVATION_BASE+64'(TOKENS*HIDDEN))begin
      offset=int'(current-ACTIVATION_BASE);
      for(int b=0;b<8;b++)rsp_data[b*8+:8]=activations[offset+b];
    end else if(current>=WEIGHT_BASE && current<WEIGHT_BASE+64'(ROWS*HIDDEN))begin
      offset=int'(current-WEIGHT_BASE);
      for(int b=0;b<8;b++)rsp_data[b*8+:8]=weights[offset+b];
    end
  end
  always @(posedge clk)begin: bus_and_scoreboard
    logic [63:0] current;
    int offset,row;
    if(rst_n)begin
      cycle<=cycle+1;
      if(active && bubble)bubble<=0;
      if(req_valid && req_ready)begin
        if(active || req_length==0 || req_length>16 || req_address[2:0]!=0)
          $fatal(1,"BATCH373_REQUEST_PROTOCOL");
        if(req_address>=ACTIVATION_BASE && req_address<ACTIVATION_BASE+64'(TOKENS*HIDDEN))begin
          offset=int'(req_address-ACTIVATION_BASE);
          if(offset%HIDDEN+8*int'(req_length)>HIDDEN)$fatal(1,"BATCH373_ACTIVATION_CROSSED_TOKEN");
        end else if(req_address>=WEIGHT_BASE && req_address<WEIGHT_BASE+64'(ROWS*HIDDEN))begin
          offset=int'(req_address-WEIGHT_BASE);row=offset/HIDDEN;
          if(!union_keep[row] || offset%HIDDEN+8*int'(req_length)>HIDDEN)
            $fatal(1,"BATCH373_WEIGHT_ADDRESS_OR_MASK");
        end else $fatal(1,"BATCH373_UNEXPECTED_ORIGINAL_ADDRESS %h",req_address);
        active<=1;address<=req_address;length<=int'(req_length);beat<=0;bubble<=0;requests++;
      end
      if(rsp_valid && rsp_ready)begin
        current=address+64'(beat*8);
        if(current>=ACTIVATION_BASE && current<ACTIVATION_BASE+64'(TOKENS*HIDDEN))begin
          activation_reads[int'(current-ACTIVATION_BASE)/8]++;activation_beats++;
        end else if(current>=WEIGHT_BASE && current<WEIGHT_BASE+64'(ROWS*HIDDEN))begin
          weight_reads[int'(current-WEIGHT_BASE)/8]++;weight_beats++;
        end else $fatal(1,"BATCH373_RESPONSE_ADDRESS");
        if(rsp_last)active<=0;
        else begin beat<=beat+1;bubble<=cycle%5==0;end
      end
      if(held_request && (!req_valid || {req_address,req_length}!==previous_request))
        $fatal(1,"BATCH373_REQUEST_CHANGED_UNDER_STALL");
      held_request=req_valid && !req_ready;
      if(held_request)previous_request={req_address,req_length};
      if(out_valid && !first_hold_done)begin
        first_hold_cycles<=first_hold_cycles+1;
        if(first_hold_cycles==3)first_hold_done<=1;
      end
      if(held_output && (!out_valid || {out_tag,out_token,out_last,out_count,out_channels,out_data}!==previous_output))
        $fatal(1,"BATCH373_OUTPUT_CHANGED_UNDER_STALL");
      held_output=out_valid && !out_ready;
      if(held_output)begin previous_output={out_tag,out_token,out_last,out_count,out_channels,out_data};output_stalls++;end
      if(out_valid && out_ready)begin
        if(seen>=TOKENS || out_tag!==32'h36600001 || out_token!==4'(seen) || out_last!==(seen==TOKENS-1) || out_count!==8'(ROWS))
          $fatal(1,"BATCH373_OUTPUT_METADATA");
        for(int column=0;column<ROWS;column++)begin
          row=ROWS-1-column;
          if(out_channels[column*16+:16]!==16'(row))$fatal(1,"BATCH373_ORIGINAL_CHANNEL_ID");
          if(out_data[column*32+:32]!==expected[seen*ROWS+row])
            $fatal(1,"BATCH373_INTEGER_OUTPUT token=%0d row=%0d got=%0d expected=%0d",seen,row,$signed(out_data[column*32+:32]),$signed(expected[seen*ROWS+row]));
        end
        seen++;
      end
      if($isunknown({cfg_ready,req_valid,rsp_ready,out_valid,done_valid}))$fatal(1,"BATCH373_UNKNOWN_PROTOCOL");
    end
  end
  initial begin: stimulus
    int rows_kept,expected_requests;
    if(!$value$plusargs("FIXTURE=%s",fixture))$fatal(1,"BATCH373_FIXTURE_REQUIRED");
    $readmemh({fixture,"/activation.hex"},activations);
    $readmemh({fixture,"/gate.hex"},weights);
    $readmemh({fixture,"/keep.hex"},keep);
    $readmemh({fixture,"/expected.hex"},expected);
    rows_kept=0;
    for(int row=0;row<ROWS;row++)begin
      union_keep[row]=0;
      for(int token=0;token<TOKENS;token++)union_keep[row]|=keep[token*ROWS+row]!=0;
      if(union_keep[row])rows_kept++;
    end
    foreach(activation_reads[i])activation_reads[i]=0;
    foreach(weight_reads[i])weight_reads[i]=0;
    repeat(3)@(negedge clk);rst_n=1;
    configure();
    if(FAULT!=0)begin
      wait(done_valid);
      repeat(4)begin
        @(negedge clk);
        if(!done_valid || !done_error || done_tag!==32'h36600001 || active || rsp_valid || seen!=0)
          $fatal(1,"BATCH373_FAULT_NOT_DRAINED active=%0d rsp_valid=%0d accepted_beats=%0d",active,rsp_valid,activation_beats);
      end
      if(requests!=((FAULT<=3 || FAULT==6 || FAULT==7 || FAULT==8) ? 1 : 0) || weight_beats!=0 ||
         activation_beats!=((FAULT==1 || FAULT==6 || FAULT==7 || FAULT==8) ? 16 : FAULT==2 ? 1 : FAULT==3 ? 17 : 0))
        $fatal(1,"BATCH373_FAULT_TRANSFER_OWNERSHIP");
      $display("BATCH373_FAULT_DRAINED fault=%0d requests=%0d beats=%0d",FAULT,requests,activation_beats);
      done_ready=1;@(posedge clk);@(negedge clk);done_ready=0;
      if(!cfg_ready)$fatal(1,"BATCH373_ERROR_DID_NOT_RELEASE_OWNER");
      inject_fault=0;requests=0;activation_beats=0;weight_beats=0;
      foreach(activation_reads[i])activation_reads[i]=0;
      foreach(weight_reads[i])weight_reads[i]=0;
      configure();
    end
    wait(done_valid);
    repeat(4)begin
      @(negedge clk);
      if(!done_valid || done_error || done_tag!==32'h36600001)$fatal(1,"BATCH373_DONE_METADATA");
    end
    if(active || rsp_valid || seen!=TOKENS || first_hold_cycles!=4 || output_stalls<4)
      $fatal(1,"BATCH373_FINAL_PROTOCOL");
    foreach(activation_reads[i])if(activation_reads[i]!=1)$fatal(1,"BATCH373_ACTIVATION_REUSE word=%0d reads=%0d",i,activation_reads[i]);
    foreach(weight_reads[i])if(weight_reads[i]!=int'(union_keep[i/(HIDDEN/8)]))
      $fatal(1,"BATCH373_WEIGHT_REUSE word=%0d reads=%0d",i,weight_reads[i]);
    expected_requests=TOKENS*(HIDDEN/8/16)+rows_kept*(HIDDEN/8/16);
    if(requests!=expected_requests || activation_beats!=TOKENS*HIDDEN/8 || weight_beats!=rows_kept*HIDDEN/8)
      $fatal(1,"BATCH373_TRANSFER_INVENTORY requests=%0d expected=%0d",requests,expected_requests);
    done_ready=1;@(posedge clk);@(negedge clk);done_ready=0;
    if(!cfg_ready)$fatal(1,"BATCH373_DID_NOT_RELEASE_OWNER");
    $display("BATCH373_PASS tokens=%0d hidden=2048 rows=160 exact_outputs=%0d requests=%0d activation_beats=%0d weight_beats=%0d stalls=%0d fault=%0d",TOKENS,160*TOKENS,requests,activation_beats,weight_beats,output_stalls,FAULT);
    $finish;
  end
  initial begin #10000000;$fatal(1,"BATCH373_WATCHDOG");end
endmodule
