`timescale 1ns/1ps
// Fused root-mean-square normalization and learned-scale activation encoding.
// Raw signed32, coefficient signed16, epsilon unsigned64/raw-square Q16.
// Both passes require caller-stable input/coefficients. Output is provisional
// until the terminal non-error handshake; aggregate replay checks are not a hash.
module tri_oracle_fused_input_normalizer (
 input logic clk,rst_n,cfg_valid,
 output logic cfg_ready,
 input logic[31:0]cfg_tag,
 input logic[9:0]cfg_strips,
 input logic[63:0]cfg_epsilon_q16,
 input logic signed[7:0]cfg_gamma_exponent,
 input logic stats_valid,
 output logic stats_ready,
 input logic stats_last,
 input logic[255:0]stats_data,
 input logic[127:0]stats_gamma,
 input logic replay_valid,
 output logic replay_ready,
 input logic replay_last,
 input logic[255:0]replay_data,
 input logic[127:0]replay_gamma,
 output logic out_valid,
 input logic out_ready,
 output logic out_last,out_error,
 output logic[31:0]out_tag,
 output logic[9:0]out_index,
 output logic[3:0]out_count,
 output logic[63:0]out_activation,
 output logic signed[8:0]out_exponent,
 output logic[7:0]out_outlier_mask,out_outlier_negative
);
 localparam int ENERGY_WIDTH=75,DENOMINATOR_WIDTH=92,COMPARE_WIDTH=160;
 typedef enum logic[3:0]{Idle,Stats,Scale,Replay,Search,Output,DrainStats,DrainReplay,Error}state_t;
 state_t state;
 logic[31:0]tag;
 logic[9:0]strips,stats_seen,replay_seen,saved_index;
 logic[12:0]features;
 logic[63:0]epsilon_q16;
 logic signed[7:0]gamma_exponent;
 logic signed[8:0]activation_exponent;
 logic[ENERGY_WIDTH-1:0]stats_energy,replay_energy,stats_total,replay_total;
 logic[47:0]stats_max,replay_max,stats_max_total,replay_max_total;
 logic[47:0]replay_magnitude[8];
 logic[DENOMINATOR_WIDTH-1:0]denominator,denominator_total;
 logic[COMPARE_WIDTH-1:0]scale_numerator,scale_budget,unit_denominator;
 logic[3:0]unit_shift;
 logic[COMPARE_WIDTH-1:0]trial_delta,remainder[8],root_term[8],trial[8];
 logic[COMPARE_WIDTH:0]trial_remainder[8];
 logic[7:0]root_code[8],root_next[8];
 logic[8:0]rounded_code[8];
 logic[7:0]accept_bit,negative,saved_outliers,saved_outlier_negative;
 logic[63:0]activation_data;
 logic[2:0]iteration;
 logic saved_last;

 function automatic logic[63:0]square32(input logic signed[31:0]value);
  logic signed[63:0]wide;
  wide={{32{value[31]}},value};return $unsigned(wide*wide);
 endfunction
 function automatic logic[47:0]product_magnitude(input logic signed[31:0]value,input logic signed[15:0]gamma);
  logic signed[47:0]product;
  product=$signed(value)*$signed(gamma);return product<0?$unsigned(-product):$unsigned(product);
 endfunction
 always_comb begin
  stats_total=stats_energy;replay_total=replay_energy;
  stats_max_total=stats_max;replay_max_total=replay_max;
  for(int lane=0;lane<8;lane++)begin
   stats_total=stats_total+ENERGY_WIDTH'(square32($signed(stats_data[lane*32+:32])));
   replay_total=replay_total+ENERGY_WIDTH'(square32($signed(replay_data[lane*32+:32])));
   if(product_magnitude($signed(stats_data[lane*32+:32]),$signed(stats_gamma[lane*16+:16]))>stats_max_total)
    stats_max_total=product_magnitude($signed(stats_data[lane*32+:32]),$signed(stats_gamma[lane*16+:16]));
   replay_magnitude[lane]=product_magnitude($signed(replay_data[lane*32+:32]),$signed(replay_gamma[lane*16+:16]));
   if(replay_magnitude[lane]>replay_max_total)replay_max_total=replay_magnitude[lane];
   trial[lane]=root_term[lane]+trial_delta;
   trial_remainder[lane]={1'b0,remainder[lane]}-{1'b0,trial[lane]};
   accept_bit[lane]=!trial_remainder[lane][COMPARE_WIDTH];
   root_next[lane]={root_code[lane][6:0],accept_bit[lane]};
   rounded_code[lane]=({1'b0,root_next[lane]}+9'd1)>>1;
  end
  denominator_total=(DENOMINATOR_WIDTH'(stats_total)<<16)
   +DENOMINATOR_WIDTH'(features)*DENOMINATOR_WIDTH'(epsilon_q16);
  cfg_ready=state==Idle;
  stats_ready=state==Stats||state==DrainStats;
  replay_ready=state==Replay||state==DrainReplay;
  out_valid=state==Output||state==Error;out_error=state==Error;
  out_last=state==Error||saved_last;out_tag=tag;
  out_index=state==Error?'0:saved_index;out_count=state==Error?'0:4'd8;
  out_activation=state==Error?'0:activation_data;
  out_exponent=state==Error?'0:activation_exponent;
  out_outlier_mask=state==Error?'0:saved_outliers;
  out_outlier_negative=state==Error?'0:saved_outlier_negative;
 end
 always_ff @(posedge clk or negedge rst_n)begin
  if(!rst_n)begin
   state<=Idle;tag<='0;strips<='0;stats_seen<='0;replay_seen<='0;saved_index<='0;
   features<='0;epsilon_q16<='0;gamma_exponent<='0;activation_exponent<='0;
   stats_energy<='0;replay_energy<='0;stats_max<='0;replay_max<='0;denominator<='0;
   scale_numerator<='0;scale_budget<='0;unit_denominator<='0;unit_shift<='0;
   trial_delta<='0;negative<='0;saved_outliers<='0;saved_outlier_negative<='0;
   activation_data<='0;iteration<='0;saved_last<=0;
   for(int lane=0;lane<8;lane++)begin remainder[lane]<='0;root_term[lane]<='0;root_code[lane]<='0;end
  end else case(state)
   Idle:if(cfg_valid)begin
    tag<=cfg_tag;strips<=cfg_strips;features<=13'(cfg_strips)<<3;
    epsilon_q16<=cfg_epsilon_q16;gamma_exponent<=cfg_gamma_exponent;
    stats_seen<='0;replay_seen<='0;stats_energy<='0;replay_energy<='0;
    stats_max<='0;replay_max<='0;saved_index<='0;saved_last<=0;
    if(cfg_strips==0||cfg_strips>512)state<=Error;else state<=Stats;
   end
   Stats:if(stats_valid)begin
    if(stats_last)begin
     if(stats_seen+10'd1!=strips||denominator_total==0)state<=Error;
     else begin
      stats_energy<=stats_total;stats_max<=stats_max_total;denominator<=denominator_total;
      scale_numerator<=(COMPARE_WIDTH'(stats_max_total)*COMPARE_WIDTH'(stats_max_total)*COMPARE_WIDTH'(features))<<16;
      scale_budget<=COMPARE_WIDTH'(denominator_total)*160'd16129;unit_shift<='0;
      replay_energy<='0;replay_max<='0;replay_seen<='0;state<=Scale;
     end
    end else if(stats_seen+10'd1==strips)state<=DrainStats;
    else begin stats_seen<=stats_seen+10'd1;stats_energy<=stats_total;stats_max<=stats_max_total;end
   end
   DrainStats:if(stats_valid&&stats_last)state<=Error;
   Scale:begin
    if(scale_numerator>scale_budget)begin
     if(unit_shift==15)state<=Error;
     else begin unit_shift<=unit_shift+4'd1;scale_budget<=scale_budget<<2;end
    end else begin
     unit_denominator<=COMPARE_WIDTH'(denominator)<<(2*unit_shift);
     activation_exponent<=stats_max==0?9'sd0:
      $signed({gamma_exponent[7],gamma_exponent})+$signed({5'b0,unit_shift});
     state<=Replay;
    end
   end
   Replay:if(replay_valid)begin
    if(replay_last&&replay_seen+10'd1!=strips)state<=Error;
    else if(!replay_last&&replay_seen+10'd1==strips)state<=DrainReplay;
    else if(replay_last&&(replay_total!=stats_energy||replay_max_total!=stats_max))state<=Error;
    else begin
     replay_energy<=replay_total;replay_max<=replay_max_total;
     saved_index<=replay_seen;replay_seen<=replay_seen+10'd1;saved_last<=replay_last;
     iteration<='0;trial_delta<=unit_denominator<<14;
     for(int lane=0;lane<8;lane++)begin
      remainder[lane]<=(COMPARE_WIDTH'(replay_magnitude[lane])*COMPARE_WIDTH'(replay_magnitude[lane])*COMPARE_WIDTH'(features))<<18;
      root_term[lane]<='0;root_code[lane]<='0;
      negative[lane]<=replay_data[lane*32+31]^replay_gamma[lane*16+15];
      saved_outliers[lane]<=((COMPARE_WIDTH'(square32($signed(replay_data[lane*32+:32])))*COMPARE_WIDTH'(features))<<16)>COMPARE_WIDTH'(denominator)*160'd9;
      saved_outlier_negative[lane]<=replay_data[lane*32+31]&&
       (((COMPARE_WIDTH'(square32($signed(replay_data[lane*32+:32])))*COMPARE_WIDTH'(features))<<16)>COMPARE_WIDTH'(denominator)*160'd9);
     end
     state<=Search;
    end
   end
   DrainReplay:if(replay_valid&&replay_last)state<=Error;
   Search:begin
    trial_delta<=trial_delta>>2;
    for(int lane=0;lane<8;lane++)begin
     root_code[lane]<=root_next[lane];
     root_term[lane]<=(root_term[lane]>>1)+(accept_bit[lane]?trial_delta:'0);
     if(accept_bit[lane])remainder[lane]<=trial_remainder[lane][COMPARE_WIDTH-1:0];
     if(iteration==7)begin
      if(negative[lane])activation_data[lane*8+:8]<=rounded_code[lane]>128?8'h80:8'(-$signed({1'b0,rounded_code[lane]}));
      else activation_data[lane*8+:8]<=rounded_code[lane]>127?8'h7f:rounded_code[lane][7:0];
     end
    end
    if(iteration==7)state<=Output;else iteration<=iteration+3'd1;
   end
   Output:if(out_ready)begin if(saved_last)state<=Idle;else state<=Replay;end
   Error:if(out_ready)state<=Idle;
   default:state<=Idle;
  endcase
 end
endmodule
