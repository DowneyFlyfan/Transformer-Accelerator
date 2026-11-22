`timescale 1ns/1ps
// The legacy run must pass the zero-offset case, then fail a nonzero-offset
// comparison. The row-enabled run must pass every frozen scalar comparison.
module tri_oracle_row_weight_consumer_tb;
  localparam int CASES=6,PACKETS=29;
  logic clk=0; always #5 clk=~clk;
  logic rst_n=0,cfg_valid=0,cfg_ready;
  logic [31:0] cfg_tag=0;
  logic [4:0] cfg_tokens=0;
  logic [6:0] cfg_count=0;
  logic [1279:0] cfg_channels=0;
  logic [95:0] cfg_gate_shifts=0,cfg_up_shifts=0,cfg_down_shifts=0;
  logic [479:0] cfg_row_units=0;
  logic out_valid,out_ready,out_last,done_valid,done_ready=0,done_error;
  logic [31:0] out_tag,done_tag;
  logic [3:0] out_token;
  logic [6:0] out_count;
  logic [1279:0] out_channels,out_gated;
  logic [639:0] out_down_input;
  logic [1279:0] out_down_wide;
  logic [639:0] out_correction;
  logic projection_ready=1,projection_valid=0,projection_last=0;
  logic [31:0] projection_tag=0,projection_done_tag=0;
  logic [3:0] projection_token=0;
  logic [6:0] projection_count=0;
  logic [1279:0] projection_channels=0;
  logic [5119:0] projection_data=0;
  logic projection_done_valid=0,projection_done_error=0;
  logic projection_out_ready,projection_done_ready;
  logic [5119:0] raw_words[PACKETS];
  logic [1279:0] gated_words[PACKETS],wide_words[PACKETS];
  logic [639:0] coarse_words[PACKETS],correction_words[PACKETS];
  logic [479:0] units[CASES];
  logic [95:0] gate_shifts[CASES],up_shifts[CASES],down_shifts[CASES];
  int counts[CASES]='{80,80,32,80,80,32};
  int tokens[CASES]='{3,3,1,16,3,3};
  int starts[CASES]='{0,3,6,7,23,26};
  int cycle=0,case_index=0,seen=0,case_seen=0;
  bit stalled=0;
  logic [3243:0] held_output;
  wire [3243:0] output_bundle={out_tag,out_token,out_last,out_count,out_channels,out_gated,out_down_input};
`ifdef ROW_UNIT_CONSUMER
  logic [1919:0] held_row_output;
`endif
  string fixture;

`ifdef ROW_UNIT_CONSUMER
  tri_oracle_row_nonlinear dut(.cfg_row_units,.out_down_wide,.out_correction,.*);
`else
  tri_oracle_batched_nonlinear391 dut(.*);
`endif
  assign out_ready=cycle%11>=5;

  always @(posedge clk) begin
    cycle<=cycle+1;
    if(cycle>100000)$fatal(1,"ROW_UNIT_TIMEOUT");
    if(rst_n)begin
      if(stalled && (out_valid!==1'b1 || output_bundle!==held_output))
        $fatal(1,"ROW_UNIT_OUTPUT_CHANGED_UNDER_STALL");
`ifdef ROW_UNIT_CONSUMER
      if(stalled && {out_down_wide,out_correction}!==held_row_output)
        $fatal(1,"ROW_UNIT_WIDE_OUTPUT_CHANGED_UNDER_STALL");
      held_row_output<={out_down_wide,out_correction};
`endif
      stalled<=out_valid && !out_ready;
      held_output<=output_bundle;
      if(out_valid && out_ready)begin
        if(out_tag!==cfg_tag || out_token!==4'(case_seen) || out_count!==cfg_count ||
           out_channels!==cfg_channels || out_last!==(case_seen+1==int'(cfg_tokens)))
          $fatal(1,"ROW_UNIT_WRONG_OUTPUT_METADATA case=%0d token=%0d",case_index,case_seen);
        if(out_gated!==gated_words[seen] || out_down_input!==coarse_words[seen])
          $fatal(1,"ROW_UNIT_WRONG_NUMERICAL_OUTPUT case=%0d token=%0d packet=%0d actual=%0d expected=%0d",case_index,case_seen,seen,$signed(out_gated[15:0]),$signed(gated_words[seen][15:0]));
`ifdef ROW_UNIT_CONSUMER
        if(out_down_wide!==wide_words[seen] || out_correction!==correction_words[seen])
          $fatal(1,"ROW_UNIT_WRONG_WIDE_OR_CORRECTION case=%0d token=%0d",case_index,case_seen);
`endif
        seen<=seen+1;case_seen<=case_seen+1;
      end
    end
  end

  initial begin
    if(!$value$plusargs("FIXTURE=%s",fixture))$fatal(1,"ROW_UNIT_MISSING_FIXTURE");
    $readmemh({fixture,"/raw.hex"},raw_words);
    $readmemh({fixture,"/gated.hex"},gated_words);
    $readmemh({fixture,"/coarse.hex"},coarse_words);
    $readmemh({fixture,"/wide.hex"},wide_words);
    $readmemh({fixture,"/correction.hex"},correction_words);
    $readmemh({fixture,"/row_units.hex"},units);
    $readmemh({fixture,"/gate_shifts.hex"},gate_shifts);
    $readmemh({fixture,"/up_shifts.hex"},up_shifts);
    $readmemh({fixture,"/down_shifts.hex"},down_shifts);
    repeat(4)@(negedge clk);rst_n=1;
    for(case_index=0;case_index<CASES;case_index++)begin
      @(negedge clk);while(!cfg_ready)@(negedge clk);
      cfg_tag=32'hc0de0000+32'(case_index);cfg_tokens=5'(tokens[case_index]);
      cfg_count=7'(counts[case_index]);cfg_channels=0;case_seen=0;
      for(int lane=0;lane<counts[case_index];lane++)cfg_channels[lane*16+:16]=16'(257+lane);
      cfg_gate_shifts=gate_shifts[case_index];cfg_up_shifts=up_shifts[case_index];
      cfg_down_shifts=down_shifts[case_index];cfg_row_units=units[case_index];
      cfg_valid=1;@(negedge clk);cfg_valid=0;
      for(int token=0;token<tokens[case_index];token++)begin
        while(!projection_out_ready)@(negedge clk);
        projection_tag=cfg_tag;projection_token=4'(token);projection_count=cfg_count;
        projection_channels=cfg_channels;projection_last=token+1==tokens[case_index];
        projection_data=raw_words[starts[case_index]+token];projection_valid=1;
        @(negedge clk);projection_valid=0;
        while(case_seen<token+1)@(negedge clk);
      end
      while(!projection_done_ready)@(negedge clk);
      projection_done_tag=cfg_tag;projection_done_valid=1;
      @(negedge clk);projection_done_valid=0;
      while(done_valid!==1'b1)@(negedge clk);
      repeat(4)begin
        if(done_valid!==1'b1 || done_error!==1'b0 || done_tag!==cfg_tag)
          $fatal(1,"ROW_UNIT_INVALID_COMPLETION");
        @(negedge clk);
      end
      done_ready=1;@(negedge clk);done_ready=0;
      if(case_seen!=tokens[case_index])$fatal(1,"ROW_UNIT_WRONG_PACKET_COUNT");
      $display("ROW_UNIT_CASE_PASS case=%0d tokens=%0d count=%0d",case_index,tokens[case_index],counts[case_index]);
    end
    if(seen!=PACKETS)$fatal(1,"ROW_UNIT_WRONG_TOTAL");
    $display("ROW_UNIT_ALL_CASES_PASS cases=6 packets=29");$finish;
  end
endmodule
