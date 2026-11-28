`timescale 1ns/1ps
// Standalone combinational COMPONENT fixture; no parent/row-frame/C owner.
// Expectations were authored/generated before reading the helper implementation.
// Correction=1 exercises only this new lane interface's declared A2 domain;
// it does not enable or qualify correction in any existing frame consumer.
module scaled_lane_tb_v1;
  localparam integer EXPECTED_VECTORS = 93376;
  localparam integer INPUT_BITS = 91;
  logic signed [31:0] raw_value,down_value;
  logic signed [7:0] raw_unit;
  logic signed [11:0] base_down_unit;
  logic [2:0] maximum_decrement,lane_decrement;
  logic correction_enable;
  logic bad;
  logic signed [8:0] common_unit;
  logic signed [11:0] lane_unit;
  logic signed [154:0] exact_sum;
  logic [154:0] magnitude;
  logic expected_bad;
  logic signed [8:0] expected_common;
  logic signed [11:0] expected_lane;
  logic signed [154:0] expected_sum;
  logic [154:0] expected_magnitude;
  logic [INPUT_BITS-1:0] known_bundle,mutated_bundle;
  integer file,scanned,rows,unknown_tests,bit_index;
  string vector_path;

  tri_oracle_calibrated_raw32_lane_v1 dut(
    .raw_value(raw_value),.down_value(down_value),.raw_unit(raw_unit),
    .base_down_unit(base_down_unit),.maximum_decrement(maximum_decrement),
    .lane_decrement(lane_decrement),.correction_enable(correction_enable),
    .bad(bad),.common_unit(common_unit),.lane_unit(lane_unit),
    .exact_sum(exact_sum),.magnitude(magnitude)
  );

  task automatic compare_expected(input integer vector_index);
    if(bad !== expected_bad || common_unit !== expected_common ||
       lane_unit !== expected_lane || exact_sum !== expected_sum ||
       magnitude !== expected_magnitude)
      $fatal(1,"SCALED_LANE_VECTOR_MISMATCH index=%0d bad=%b/%b common=%0d/%0d lane=%0d/%0d sum=%039h/%039h magnitude=%039h/%039h",
             vector_index,bad,expected_bad,common_unit,expected_common,
             lane_unit,expected_lane,exact_sum,expected_sum,magnitude,expected_magnitude);
  endtask

  task automatic compare_rejection(input integer input_bit,input bit is_Z);
    #1ns;
    if(bad !== 1'b1 || common_unit !== 9'sd0 || lane_unit !== 12'sd0 ||
       exact_sum !== 155'sd0 || magnitude !== 155'd0)
      $fatal(1,"SCALED_LANE_UNKNOWN_REJECTION bit=%0d Z=%0d",input_bit,is_Z);
    // Same rejected offer is held for a second observation, with known outputs.
    #1ns;
    if(bad !== 1'b1 || common_unit !== 9'sd0 || lane_unit !== 12'sd0 ||
       exact_sum !== 155'sd0 || magnitude !== 155'd0)
      $fatal(1,"SCALED_LANE_UNKNOWN_HELD_REJECTION bit=%0d Z=%0d",input_bit,is_Z);
    unknown_tests = unknown_tests+1;
  endtask

  initial begin
    raw_value=0;down_value=0;raw_unit=0;base_down_unit=-12'sd19;
    maximum_decrement=0;lane_decrement=0;correction_enable=0;
    rows=0;unknown_tests=0;
    if(!$value$plusargs("vectors=%s",vector_path))
      $fatal(1,"SCALED_LANE_REQUIRED_VECTOR_PATH");
    file=$fopen(vector_path,"r");
    if(file==0)$fatal(1,"SCALED_LANE_VECTOR_OPEN_FAILED");
    while(!$feof(file))begin
      scanned=$fscanf(file,"%h %h %h %h %h %h %h %h %h %h %h %h",
        raw_value,down_value,raw_unit,base_down_unit,maximum_decrement,
        lane_decrement,correction_enable,expected_bad,expected_common,
        expected_lane,expected_sum,expected_magnitude);
      if(scanned==-1)break;
      if(scanned!=12)$fatal(1,"SCALED_LANE_VECTOR_PARSE index=%0d fields=%0d",rows,scanned);
      if($isunknown({raw_value,down_value,raw_unit,base_down_unit,
         maximum_decrement,lane_decrement,correction_enable,expected_bad,
         expected_common,expected_lane,expected_sum,expected_magnitude}))
        $fatal(1,"SCALED_LANE_HEX_VECTOR_MUST_BE_KNOWN index=%0d",rows);
      #1ns;
      compare_expected(rows);
      if(expected_bad)begin
        if(expected_common!==0 || expected_lane!==0 || expected_sum!==0 || expected_magnitude!==0)
          $fatal(1,"SCALED_LANE_BAD_EXPECTATION_MUST_BE_ZERO index=%0d",rows);
        #1ns;
        compare_expected(rows);
      end
      rows=rows+1;
      if(rows>EXPECTED_VECTORS)$fatal(1,"SCALED_LANE_TOO_MANY_VECTORS");
    end
    $fclose(file);
    if(rows!=EXPECTED_VECTORS)$fatal(1,"SCALED_LANE_VECTOR_CENSUS got=%0d expected=%0d",rows,EXPECTED_VECTORS);

    // One X and one Z is injected at EVERY public input bit, including
    // signed raw/unit bits, delta selectors and correction_enable. No private
    // signal, force/release, hierarchical assignment or simulated state exists.
    raw_value=32'sd7;down_value=-32'sd9;raw_unit=8'sd97;
    base_down_unit=-12'sd19;maximum_decrement=3'd7;
    lane_decrement=3'd5;correction_enable=1'b1;
    #1ns;
    if(bad!==1'b0)$fatal(1,"SCALED_LANE_UNKNOWN_BASELINE_MUST_BE_VALID");
    known_bundle={raw_value,down_value,raw_unit,base_down_unit,
                  maximum_decrement,lane_decrement,correction_enable};
    for(bit_index=0;bit_index<INPUT_BITS;bit_index=bit_index+1)begin
      mutated_bundle=known_bundle;
      mutated_bundle[bit_index]=1'bx;
      {raw_value,down_value,raw_unit,base_down_unit,
       maximum_decrement,lane_decrement,correction_enable}=mutated_bundle;
      compare_rejection(bit_index,1'b0);
      mutated_bundle=known_bundle;
      mutated_bundle[bit_index]=1'bz;
      {raw_value,down_value,raw_unit,base_down_unit,
       maximum_decrement,lane_decrement,correction_enable}=mutated_bundle;
      compare_rejection(bit_index,1'b1);
    end
    if(unknown_tests!=182)$fatal(1,"SCALED_LANE_UNKNOWN_CENSUS");
    $display("CALIBRATED_DOWN_LANE_SYNTHETIC_COMPONENT_PASS vectors=%0d unknown_X_Z=%0d",rows,unknown_tests);
    $finish;
  end

  initial begin
    #200000ns;
    $fatal(1,"SCALED_LANE_COMPONENT_DEADLINE");
  end
endmodule
