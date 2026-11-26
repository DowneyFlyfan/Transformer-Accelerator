`timescale 1ns/1ps
// Verification-only: two units compare default16 channel/cycle behavior.
// This bench does not qualify24 arithmetic or a physical two-unit design.
module tri_oracle_fused_input_default16_conformance_tb;
  typedef struct packed {
    logic cfg_ready, stats_ready, replay_ready;
    logic out_valid, out_last, out_error;
    logic [31:0] out_tag;
    logic [9:0] out_index;
    logic [3:0] out_count;
    logic [63:0] out_activation;
    logic signed [8:0] out_exponent;
    logic [7:0] out_outlier_mask, out_outlier_negative, out_normalized_negative;
  } outputs_t;
  outputs_t old_o, new_o, held_o;
  logic clk=0, rst_n=0, cfg_valid=0;
  logic [31:0] cfg_tag=0;
  logic [9:0] cfg_strips=0;
  logic [63:0] cfg_epsilon_q16=0;
  logic signed [7:0] cfg_gamma_exponent=0;
  logic stats_valid=0, stats_last=0, replay_valid=0, replay_last=0, out_ready=0;
  logic [255:0] stats_data=0, replay_data=0;
  logic [127:0] stats_gamma=0, replay_gamma=0;
  bit auto_backpressure=0, stalled=0;
  int cycles=0, checks=0, cases=0, configs=0, outputs=0, errors=0;
  int stats_fires=0, replay_fires=0;

  tri_oracle_fused_input_sign_normalizer legacy (
    .clk(clk),.rst_n(rst_n),.cfg_valid(cfg_valid),.cfg_ready(old_o.cfg_ready),
    .cfg_tag(cfg_tag),.cfg_strips(cfg_strips),.cfg_epsilon_q16(cfg_epsilon_q16),
    .cfg_gamma_exponent(cfg_gamma_exponent),.stats_valid(stats_valid),
    .stats_ready(old_o.stats_ready),.stats_last(stats_last),.stats_data(stats_data),
    .stats_gamma(stats_gamma),.replay_valid(replay_valid),.replay_ready(old_o.replay_ready),
    .replay_last(replay_last),.replay_data(replay_data),.replay_gamma(replay_gamma),
    .out_valid(old_o.out_valid),.out_ready(out_ready),.out_last(old_o.out_last),
    .out_error(old_o.out_error),.out_tag(old_o.out_tag),.out_index(old_o.out_index),
    .out_count(old_o.out_count),.out_activation(old_o.out_activation),
    .out_exponent(old_o.out_exponent),.out_outlier_mask(old_o.out_outlier_mask),
    .out_outlier_negative(old_o.out_outlier_negative),
    .out_normalized_negative(old_o.out_normalized_negative)
  );
  // Deliberately no parameter override: this tests the public default16.
  tri_oracle_fused_input_sign_normalizer_wide_v1 candidate (
    .clk(clk),.rst_n(rst_n),.cfg_valid(cfg_valid),.cfg_ready(new_o.cfg_ready),
    .cfg_tag(cfg_tag),.cfg_strips(cfg_strips),.cfg_epsilon_q16(cfg_epsilon_q16),
    .cfg_gamma_exponent(cfg_gamma_exponent),.stats_valid(stats_valid),
    .stats_ready(new_o.stats_ready),.stats_last(stats_last),.stats_data(stats_data),
    .stats_gamma(stats_gamma),.replay_valid(replay_valid),.replay_ready(new_o.replay_ready),
    .replay_last(replay_last),.replay_data(replay_data),.replay_gamma(replay_gamma),
    .out_valid(new_o.out_valid),.out_ready(out_ready),.out_last(new_o.out_last),
    .out_error(new_o.out_error),.out_tag(new_o.out_tag),.out_index(new_o.out_index),
    .out_count(new_o.out_count),.out_activation(new_o.out_activation),
    .out_exponent(new_o.out_exponent),.out_outlier_mask(new_o.out_outlier_mask),
    .out_outlier_negative(new_o.out_outlier_negative),
    .out_normalized_negative(new_o.out_normalized_negative)
  );

  always #5 clk=~clk;
  always @(negedge clk) begin
    if(auto_backpressure) out_ready=(cycles%7!=1 && cycles%7!=2 && cycles%7!=3);
  end
  always @(posedge clk) begin
    cycles=cycles+1;
    if(old_o!==new_o) $fatal(1,"DEFAULT16_CHANNEL_MISMATCH pre cycle=%0d",cycles);
    if(rst_n) begin
      if($isunknown(old_o)) $fatal(1,"DEFAULT16_UNKNOWN_CHANNEL");
      if(stalled && old_o!==held_o) $fatal(1,"DEFAULT16_STALLED_OUTPUT_CHANGED");
      held_o=old_o;
      stalled=old_o.out_valid&&!out_ready;
      if(cfg_valid&&old_o.cfg_ready) configs=configs+1;
      if(stats_valid&&old_o.stats_ready) stats_fires=stats_fires+1;
      if(replay_valid&&old_o.replay_ready) replay_fires=replay_fires+1;
      if(old_o.out_valid&&out_ready) begin
        outputs=outputs+1;
        if(old_o.out_error) errors=errors+1;
      end
    end else stalled=0;
    checks=checks+1;
    #1;
    if(old_o!==new_o) $fatal(1,"DEFAULT16_CHANNEL_MISMATCH post cycle=%0d",cycles);
    checks=checks+1;
  end
  initial begin
    #2000000;
    $fatal(1,"DEFAULT16_WATCHDOG");
  end

  task automatic row_word(input int kind,word_index,
                           output logic [255:0] raw,output logic [127:0] gain);
    logic signed [31:0] x;
    logic signed [15:0] g;
    raw=0;gain=0;
    for(int lane=0;lane<8;lane++) begin
      case(kind)
        0:begin x=0;g=0;end
        1:case((word_index*8+lane)%4)
          0:begin x=32'sh80000000;g=16'sh8000;end
          1:begin x=32'sh7fffffff;g=16'sh7fff;end
          2:begin x=-1;g=1;end
          default:begin x=1;g=-1;end
        endcase
        2:begin x=32'(word_index*7919+lane*257+1);g=16'(word_index*19-lane*31);end
        3:begin x=1;g=(lane%2==0)?-1:1;end
        4:begin x=(word_index==0&&lane==0)?1:0;g=16'sh8000;end
        5:begin x=1;g=1;end
        6:begin x=1;g=2;end
        7:begin x=(lane==0)?0:1;g=1;end
        default:$fatal(1,"DEFAULT16_UNKNOWN_PATTERN");
      endcase
      raw[lane*32+:32]=x;gain[lane*16+:16]=g;
    end
  endtask
  task automatic config_row(input int strips,input logic [63:0] eps,
                            input logic signed [7:0] exponent);
    @(negedge clk);
    cfg_tag=32'h16000000+32'(configs);cfg_strips=10'(strips);
    cfg_epsilon_q16=eps;cfg_gamma_exponent=exponent;cfg_valid=1;
    do @(posedge clk);while(!old_o.cfg_ready);
    @(negedge clk);cfg_valid=0;
  endtask
  task automatic stats_word(input int kind,word_index,input bit last,input int gap=0);
    repeat(gap) @(negedge clk);
    @(negedge clk);row_word(kind,word_index,stats_data,stats_gamma);
    stats_last=last;stats_valid=1;
    do @(posedge clk);while(!old_o.stats_ready);
    @(negedge clk);stats_valid=0;
  endtask
  task automatic replay_word(input int kind,word_index,input bit last,input int gap=0);
    repeat(gap) @(negedge clk);
    @(negedge clk);row_word(kind,word_index,replay_data,replay_gamma);
    replay_last=last;replay_valid=1;
    do @(posedge clk);while(!old_o.replay_ready);
    @(negedge clk);replay_valid=0;
  endtask
  task automatic pass_case(input string name);
    cases=cases+1;
    $display("DEFAULT16_CASE name=%s ordinal=%0d cycle=%0d",name,cases,cycles);
  endtask
  task automatic healthy(input string name,input int strips,kind,
                         input logic [63:0] eps,input logic signed [7:0] exponent);
    int errors_before;
    errors_before=errors;auto_backpressure=1;
    config_row(strips,eps,exponent);
    for(int i=0;i<strips;i++) stats_word(kind,i,i==strips-1,i%3);
    for(int i=0;i<strips;i++) replay_word(kind,i,i==strips-1,(i+1)%3);
    while(!old_o.cfg_ready) @(negedge clk);
    if(errors!=errors_before) $fatal(1,"DEFAULT16_HEALTHY_ERROR name=%s",name);
    pass_case(name);
  endtask
  task automatic begin_error;
    @(negedge clk);auto_backpressure=0;out_ready=0;
  endtask
  task automatic finish_error(input string name);
    while(!old_o.out_valid) @(negedge clk);
    if(!old_o.out_error||!old_o.out_last||old_o.out_count!=0||
       old_o.out_activation!=0||old_o.out_exponent!=0||
       old_o.out_outlier_mask!=0||old_o.out_outlier_negative!=0||
       old_o.out_normalized_negative!=0) $fatal(1,"DEFAULT16_EXPECTED_ERROR name=%s",name);
    repeat(3) @(negedge clk);
    out_ready=1;@(posedge clk);@(negedge clk);out_ready=0;
    if(!old_o.cfg_ready) $fatal(1,"DEFAULT16_ERROR_DID_NOT_RETIRE");
    pass_case(name);
  endtask
  task automatic coupled_reset;
    @(negedge clk);rst_n=0;cfg_valid=0;stats_valid=0;replay_valid=0;
    auto_backpressure=0;out_ready=0;
    repeat(2) @(negedge clk);
    rst_n=1;@(negedge clk);
    if(!old_o.cfg_ready||old_o.out_valid||old_o.out_normalized_negative!=0)
      $fatal(1,"DEFAULT16_RESET_DID_NOT_CLEAR");
  endtask

  initial begin
    repeat(3) @(negedge clk);rst_n=1;
    healthy("zero_positive_epsilon",1,0,1,8'sd127);
    healthy("extreme_epsilon_zero",1,1,0,-8'sd128);
    healthy("tiny_signed_products",1,3,64'hffffffffffffffff,8'sd127);
    healthy("provided_shape256_with_gaps",256,2,64'hffffffffffffffff,-8'sd128);
    healthy("maximum512_extremes",512,1,0,8'sd127);
    healthy("maximum512_shift15",512,4,0,-8'sd128);

    begin_error();config_row(0,1,0);finish_error("invalid_zero_strips");
    begin_error();config_row(513,1,0);finish_error("invalid_over512_strips");
    begin_error();config_row(1,0,0);stats_word(0,0,1);finish_error("zero_denominator");
    begin_error();config_row(2,1,0);stats_word(5,0,1);finish_error("early_stats_last");
    begin_error();config_row(1,1,0);stats_word(5,0,0);
    if(!old_o.stats_ready||old_o.replay_ready||old_o.out_valid)
      $fatal(1,"DEFAULT16_EXPECTED_DRAIN_STATS");
    repeat(3) @(negedge clk);stats_word(5,1,1);finish_error("missing_stats_last_drain");

    begin_error();config_row(2,1,0);stats_word(5,0,0);stats_word(5,1,1);
    replay_word(5,0,1);finish_error("early_replay_last");
    begin_error();config_row(1,1,0);stats_word(5,0,1);replay_word(5,0,0);
    if(!old_o.replay_ready||old_o.stats_ready||old_o.out_valid)
      $fatal(1,"DEFAULT16_EXPECTED_DRAIN_REPLAY");
    repeat(3) @(negedge clk);replay_word(5,1,1);finish_error("missing_replay_last_drain");
    begin_error();config_row(1,1,0);stats_word(5,0,1);
    replay_word(6,0,1);finish_error("replay_max_mismatch");
    begin_error();config_row(1,1,0);stats_word(5,0,1);
    replay_word(7,0,1);finish_error("replay_energy_mismatch");

    // A nonterminal output may be provisional before a terminal aggregate error.
    begin_error();config_row(2,1,-8'sd128);stats_word(5,0,0);stats_word(5,1,1);
    replay_word(5,0,0);
    while(!old_o.out_valid) @(negedge clk);
    if(old_o.out_error||old_o.out_last) $fatal(1,"DEFAULT16_EXPECTED_PROVISIONAL_OUTPUT");
    repeat(4) @(negedge clk);out_ready=1;@(posedge clk);@(negedge clk);out_ready=0;
    replay_word(6,1,1);finish_error("late_replay_aggregate_error");

    begin_error();config_row(1,1,0);stats_word(1,0,1);replay_word(1,0,1);
    repeat(2) @(negedge clk);
    if(old_o.out_valid||old_o.replay_ready||old_o.cfg_ready)
      $fatal(1,"DEFAULT16_EXPECTED_SEARCH_BEFORE_RESET");
    coupled_reset();pass_case("reset_mid_search");
    begin_error();config_row(1,1,0);stats_word(1,0,1);replay_word(1,0,1);
    while(!old_o.out_valid) @(negedge clk);
    repeat(4) @(negedge clk);coupled_reset();pass_case("reset_held_output");
    healthy("recovery_after_reset",1,1,1,0);
    if(cases!=19) $fatal(1,"DEFAULT16_MISSING_CASES count=%0d",cases);
    if(configs!=19||stats_fires!=1297||replay_fires!=1293||outputs!=1295||errors!=10)
      $fatal(1,"DEFAULT16_HANDSHAKE_CENSUS");
    $display("DEFAULT16_CONFORMANCE_PASS cases=%0d checks=%0d cycles=%0d configs=%0d stats=%0d replay=%0d outputs=%0d errors=%0d",cases,checks,cycles,configs,stats_fires,replay_fires,outputs,errors);
    $finish;
  end
endmodule
