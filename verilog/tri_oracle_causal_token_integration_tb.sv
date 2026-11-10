`timescale 1ns/1ps
// Figure31.6.3 regression: a future merge must not reweight an earlier row.
// BASELINE_GLOBAL selects the existing final-frame size stream, unchanged.
module tri_oracle_causal_token_integration_tb;
  logic clk=0;
  always #5 clk=~clk;
  logic rst_n=0, in_valid=0;
  logic [3:0] in_sign=0;
  wire in_ready, merged_valid, merged_ready, legacy_size_valid, legacy_done;
  wire [2:0] merged_index, merged_origin, legacy_origin, legacy_count;
  wire [1:0] merged_kind;
  logic [3:0] sizes[4];
  integer mappings=0;
  integer wanted_origin[4]='{0,1,0,3};
  logic norm_valid=0;
  wire norm_ready,norm_out_valid;
  logic [15:0] norm_sizes=0;
  logic [3:0] mask=0;
  wire [31:0] probabilities;
  tri_oracle_token_merger #(.IMG_W(2),.IMG_H(2),.SIGN_W(4),.MATCH_THRESHOLD(4)) merger (
    .clk,.rst_n,.in_valid,.in_ready,.in_sign,.out_valid(merged_valid),
    .out_ready(merged_ready),.out_index(merged_index),.out_origin(merged_origin),
    .out_merge(merged_kind),.size_valid(legacy_size_valid),.size_ready(1'b1),
    .size_origin(legacy_origin),.size_count(legacy_count),.done(legacy_done)
  );
  tri_oracle_proportional_normalizer #(.N(4)) normalizer (
    .clk,.rst_n,.in_valid(norm_valid),.in_ready(norm_ready),
    .exp_scores(32'h01010101),.token_sizes(norm_sizes),.causal_mask(mask),
    .out_valid(norm_out_valid),.out_ready(1'b1),.probabilities
  );
`ifdef BASELINE_GLOBAL
  assign merged_ready=1'b1;
  always @(posedge clk)
    if(rst_n && legacy_size_valid) sizes[legacy_origin]=4'(legacy_count);
`else
  logic frame_valid=0,query_valid=0,row_ready=0;
  logic [1:0] query_position=0;
  wire frame_ready,map_ready,query_ready,row_valid,row_last,error;
  wire [1:0] row_origin;
  wire [2:0] row_count;
  assign merged_ready=map_ready;
  tri_oracle_causal_token_size #(.MAX_TOKENS(4)) causal_sizes (
    .clk,.rst_n,.frame_valid,.frame_ready,
    .map_valid(merged_valid),.map_ready,.map_origin(merged_origin[1:0]),
    .map_last(merged_index==3),.query_valid,.query_ready,.query_position,
    .out_valid(row_valid),.out_ready(row_ready),.out_origin(row_origin),
    .out_count(row_count),.out_last(row_last),.error
  );
`endif
  always @(posedge clk) begin
    if(rst_n && merged_valid && merged_ready) begin
      if(mappings>=4 || merged_index!==3'(mappings) ||
         merged_origin!==3'(wanted_origin[mappings]))
        $fatal(1,"CAUSAL_MERGER_MAP index=%0d origin=%0d",merged_index,merged_origin);
      mappings++;
    end
  end
  task automatic send_sign(input logic [3:0] value);
    @(negedge clk);in_valid=1;in_sign=value;
    do @(posedge clk); while(!in_ready);
    @(negedge clk);in_valid=0;
  endtask
  task automatic check_row(input int position,input logic [31:0] expected);
`ifndef BASELINE_GLOBAL
    bit finished;
    int cycle;
`endif
    begin
`ifndef BASELINE_GLOBAL
      for(int i=0;i<4;i++) sizes[i]=0;
      @(negedge clk);query_valid=1;query_position=2'(position);
      do @(posedge clk);while(!query_ready);
      @(negedge clk);query_valid=0;row_ready=0;
      finished=0;cycle=0;
      while(!finished) begin
        row_ready=(cycle%3)!=0;
        @(posedge clk);
        if(error) $fatal(1,"CAUSAL_SIZE_UNEXPECTED_ERROR");
        if(row_valid && row_ready) begin
          sizes[row_origin]=4'(row_count);
          finished=row_last;
        end
        @(negedge clk);cycle++;
        if(cycle>50) $fatal(1,"CAUSAL_ROW_TIMEOUT");
      end
      row_ready=0;
`endif
      for(int i=0;i<4;i++) begin
        norm_sizes[4*i+:4]=sizes[i];
        mask[i]=(i<=position && wanted_origin[i]==i);
      end
      @(negedge clk);norm_valid=1;
      @(posedge clk);#1;
      if(!norm_out_valid || probabilities!==expected)
        $fatal(1,"CAUSAL_PREFIX_REQUIRED query=%0d got=%h expected=%h",position,probabilities,expected);
      @(negedge clk);norm_valid=0;
    end
  endtask
  initial begin
    for(int i=0;i<4;i++) sizes[i]=0;
    repeat(2) @(negedge clk);rst_n=1;
`ifndef BASELINE_GLOBAL
    frame_valid=1;
    do @(posedge clk);while(!frame_ready);
    @(negedge clk);frame_valid=0;
`endif
    send_sign(4'b0000);
    send_sign(4'b1111);
    send_sign(4'b0000);
    send_sign(4'b0011);
    wait(legacy_done);
    if(mappings!=4) $fatal(1,"CAUSAL_MAPPING_INVENTORY");
    check_row(1,32'h00008080); // Prefix counts [1,1]: [128,128].
    check_row(3,32'h40004080); // Full counts [2,1,0,1]: [128,64,0,64].
    check_row(2,32'h000055aa); // Move cursor backward: [170,85].
    check_row(0,32'h000000ff); // First original token only.
    check_row(3,32'h40004080); // Revisit the complete frame.
    $display("CAUSAL_INTEGRATION_PASS mappings=4 rows=5 backward_queries=2");
    $finish;
  end
  initial begin #20000;$fatal(1,"CAUSAL_INTEGRATION_WATCHDOG");end
endmodule
