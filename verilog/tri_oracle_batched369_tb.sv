`timescale 1ns/1ps
// Full hidden-width batched affine tile. Testbench preloads the actual resident
// memories; transfer latency and complete-model throughput are outside scope.
module tri_oracle_batched369_tb;
  parameter int TOKENS=16;
  parameter bit DIRECTED_STALL=1;
  int first_hold_cycles=0;
  bit first_hold_done=0;
  localparam int HIDDEN=2048;
  logic clk=0;always #5 clk=~clk;
  logic rst_n=0,in_valid=0,in_accumulate=0,in_publish=0;
  logic [31:0] in_tag=0;
  logic [4:0] in_tokens=0,in_weight_base=0,in_mask_base=0;
  logic [5:0] in_strips=0;
  logic [9:0] in_activation_base=0;
  logic [10:0] in_activation_stride=0;
  wire in_ready,out_valid,out_last,done_valid,done_error,backend_rst_n;
  wire [31:0] out_tag,done_tag;
  wire [3:0] out_token;
  wire [5119:0] out_data;
  logic done_ready=0;
  int cycle=0,seen=0,commands=0,stalls=0;
  wire out_ready=(!DIRECTED_STALL || first_hold_done) && cycle%11>=5;
  wire backend_cmd_valid,backend_cmd_ready,backend_cmd_accumulate;
  wire [4:0] backend_cmd_weight,backend_cmd_mask;
  wire [9:0] backend_cmd_activation;
  wire [3:0] backend_cmd_output;
  wire [4:0] backend_out_valid,backend_out_ready;
  wire [19:0] backend_out_output;
  wire [5119:0] backend_out_data;
  logic load_valid=0;
  logic [4:0] load_core=0;
  logic [1:0] load_kind=0;
  logic [9:0] load_addr=0;
  logic [2047:0] load_data=0;
  wire load_error;
  int expected[TOKENS][160];
  logic held=0;
  logic [5156:0] held_output=0;
  tri_oracle_batched_projection356 sequencer(.*);
  tri_oracle_compute_fabric fabric (
    .clk(clk),.rst_n(backend_rst_n),.load_valid(load_valid),.load_core(load_core),.load_kind(load_kind),
    .load_addr(load_addr),.load_data(load_data),.load_row_enable(32'hffffffff),.load_error(load_error),
    .cmd_valid(backend_cmd_valid),.cmd_ready(backend_cmd_ready),.cmd_clusters(5'b11111),
    .cmd_weight(backend_cmd_weight),.cmd_mask(backend_cmd_mask),.cmd_activation(backend_cmd_activation),
    .cmd_output(backend_cmd_output),.cmd_accumulate(backend_cmd_accumulate),.cmd_reduce(2'b0),
    .out_valid(backend_out_valid),.out_ready(backend_out_ready),.out_output(backend_out_output),.out_data(backend_out_data));

  byte unsigned fixture_activations[16*HIDDEN],fixture_weights[160*HIDDEN],fixture_keep[16*160];
  logic [31:0] fixture_expected[16*160];
  string fixture;
  function automatic int weight(input int row,input int feature);
    return int'($signed(fixture_weights[row*HIDDEN+feature]));
  endfunction
  function automatic int activation(input int token,input int feature);
    return int'($signed(fixture_activations[token*HIDDEN+feature]));
  endfunction
  function automatic bit kept(input int token,input int row);
    return fixture_keep[token*160+row]!=0;
  endfunction
  task automatic load(input int kind,input int address,input logic [2047:0] data);
    @(negedge clk);load_valid=1;load_kind=2'(kind);load_addr=10'(address);load_data=data;
    @(posedge clk);#1;if(load_error!==0)$fatal(1,"BATCH369_LOAD_REJECTED");
    @(negedge clk);load_valid=0;
  endtask
  task automatic configure(input int tokens,input int strips,input int start,input int stride,
                           input bit accumulate,input bit publish,input int tag);
    @(negedge clk);while(!in_ready)@(negedge clk);
    in_tokens=5'(tokens);in_strips=6'(strips);in_activation_base=10'(start);in_activation_stride=11'(stride);
    in_weight_base=0;in_mask_base=0;in_accumulate=accumulate;in_publish=publish;in_tag=32'(tag);in_valid=1;
    @(posedge clk);if(!in_ready)$fatal(1,"BATCH369_CONFIG_NOT_ACCEPTED");
    @(negedge clk);in_valid=0;in_tokens=0;in_strips=0;in_activation_base='1;in_activation_stride='1;
    in_weight_base='1;in_mask_base='1;in_accumulate=0;in_publish=0;in_tag='1;
  endtask
  task automatic acknowledge(input bit error,input int tag);
    wait(done_valid);
    repeat(3)begin
      @(negedge clk);
      if(!done_valid || done_error!==error || done_tag!==32'(tag))$fatal(1,"BATCH369_DONE_METADATA");
    end
    done_ready=1;@(posedge clk);@(negedge clk);done_ready=0;
  endtask
  always @(posedge clk)if(rst_n)begin
    cycle<=cycle+1;
    if(out_valid && !first_hold_done)begin
      first_hold_cycles<=first_hold_cycles+1;
      if(first_hold_cycles==3)first_hold_done<=1;
    end
    if($isunknown({in_ready,out_valid,done_valid,backend_cmd_valid,backend_cmd_ready,backend_out_valid}))
      $fatal(1,"BATCH369_UNKNOWN_PROTOCOL");
    if(backend_cmd_valid && backend_cmd_ready)commands++;
    if(held && (!out_valid || {out_tag,out_token,out_last,out_data}!==held_output))
      $fatal(1,"BATCH369_OUTPUT_CHANGED_UNDER_STALL");
    held=out_valid && !out_ready;
    if(held)begin held_output={out_tag,out_token,out_last,out_data};stalls++;end
    if(out_valid && out_ready)begin
      if(seen>=TOKENS || out_tag!==32'h35900002 || out_token!==4'(seen) || out_last!==(seen==TOKENS-1))
        $fatal(1,"BATCH369_OUTPUT_METADATA");
      for(int row=0;row<160;row++)
        if(out_data[row*32+:32]!==32'(expected[seen][row]))
          $fatal(1,"BATCH369_INTEGER_OUTPUT token=%0d row=%0d got=%0d expected=%0d",seen,row,$signed(out_data[row*32+:32]),expected[seen][row]);
      seen++;
    end
  end
  initial begin: stimulus
    logic [2047:0] word;
    if(!$value$plusargs("FIXTURE=%s",fixture))$fatal(1,"BATCH369_FIXTURE_REQUIRED");
    $readmemh({fixture,"/activation.hex"},fixture_activations);
    $readmemh({fixture,"/gate.hex"},fixture_weights);
    $readmemh({fixture,"/keep.hex"},fixture_keep);
    $readmemh({fixture,"/expected.hex"},fixture_expected);
    for(int token=0;token<TOKENS;token++)for(int row=0;row<160;row++)begin
      expected[token][row]=0;
      if(kept(token,row))for(int feature=0;feature<HIDDEN;feature++)
        expected[token][row]+=activation(token,feature)*weight(row,feature);
      if(fixture_keep[token*160+row]>1 || expected[token][row]!==fixture_expected[token*160+row])
        $fatal(1,"BATCH369_ARCHIVED_SCALAR_REFERENCE");
    end
    repeat(3)@(negedge clk);rst_n=1;
    // Invalid descriptors must complete as errors without issuing any command.
    configure(0,32,0,64,0,0,1);acknowledge(1,1);
    configure(17,32,0,64,0,0,2);acknowledge(1,2);
    configure(16,32,32,65,0,0,3);acknowledge(1,3);
    if(commands!=0)$fatal(1,"BATCH369_INVALID_CONFIG_ISSUED");
    for(int core=0;core<20;core++)begin
      load_core=5'(core);
      for(int token=0;token<TOKENS;token++)begin
        word=0;
        for(int row=0;row<32;row++)if(kept(token,(core/4)*32+row))word[row*8+:8]=8'hff;
        load(2,token,word);
        for(int strip=0;strip<64;strip++)begin
          word=0;
          for(int lane=0;lane<8;lane++)word[lane*8+:8]=8'(activation(token,(core%4)*512+strip*8+lane));
          load(1,token*64+strip,word);
        end
      end
    end
    for(int tile=0;tile<2;tile++)begin
      for(int core=0;core<20;core++)begin
        load_core=5'(core);
        for(int strip=0;strip<32;strip++)begin
          word=0;
          for(int row=0;row<32;row++)for(int lane=0;lane<8;lane++)
            word[(row*8+lane)*8+:8]=8'(weight((core/4)*32+row,(core%4)*512+tile*256+strip*8+lane));
          load(0,strip,word);
        end
      end
      configure(TOKENS,32,tile*32,64,tile!=0,tile==1,32'h35900002);
      acknowledge(0,32'h35900002);
      if(tile==0 && seen!=0)$fatal(1,"BATCH369_INTERMEDIATE_TILE_PUBLISHED");
    end
    $display("BATCH369_INVENTORY tokens=%0d seen=%0d commands=%0d stalls=%0d directed=%0d first_hold_cycles=%0d",TOKENS,seen,commands,stalls,DIRECTED_STALL,first_hold_cycles);
    if(seen!=TOKENS || commands!=64*TOKENS || stalls==0 || (DIRECTED_STALL && first_hold_cycles!=4))$fatal(1,"BATCH369_FINAL_INVENTORY");
    $display("BATCH369_PASS tokens=%0d hidden=2048 rows=160 exact_outputs=%0d commands=%0d stalls=%0d",TOKENS,160*TOKENS,64*TOKENS,stalls);$finish;
  end
  initial begin #5000000;$fatal(1,"BATCH369_WATCHDOG");end
endmodule
