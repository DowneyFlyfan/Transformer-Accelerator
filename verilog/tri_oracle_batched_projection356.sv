`timescale 1ns/1ps
// Resident batched matrix-vector issue for the unchanged five-cluster fabric.
// Iterate tokens inside feature strips: each resident weight word is reused
// across1..16 tokens; each token owns one existing accumulator slot. At most32
// weight words,1024 activation words and32 mask words are addressed per core.
// The caller exclusively owns/preloads the fabric and waits for done before
// changing resident weights. A later DMA owner must enforce that contract.
// Nonpublishing feature tiles retain one tagged token/mask/stride context.
// Append requires that live context; reset/error/final publication invalidates
// it even though the underlying memory macros retain their stored bits.
// Local scheduling/interface choices; not the authors' unpublished controller.
// A terminal error invalidates every earlier output bearing this descriptor tag.
module tri_oracle_batched_projection356 (
  input logic clk,rst_n,in_valid,
  output logic in_ready,
  input logic [31:0] in_tag,
  input logic [4:0] in_tokens,in_weight_base,in_mask_base,
  input logic [5:0] in_strips,
  input logic [9:0] in_activation_base,
  input logic [10:0] in_activation_stride,
  input logic in_accumulate,in_publish,
  output logic out_valid,
  input logic out_ready,
  output logic [31:0] out_tag,
  output logic [3:0] out_token,
  output logic out_last,
  output logic [5119:0] out_data,
  output logic done_valid,
  input logic done_ready,
  output logic done_error,
  output logic [31:0] done_tag,
  output logic backend_rst_n,
  output logic backend_cmd_valid,
  input logic backend_cmd_ready,
  output logic [4:0] backend_cmd_weight,backend_cmd_mask,
  output logic [9:0] backend_cmd_activation,
  output logic [3:0] backend_cmd_output,
  output logic backend_cmd_accumulate,
  input logic [4:0] backend_out_valid,
  output logic [4:0] backend_out_ready,
  input logic [19:0] backend_out_output,
  input logic [5119:0] backend_out_data
);
  typedef enum logic [1:0] {IDLE,RUN,FLUSH,DONE} state_t;
  state_t state;
  logic [31:0] tag;
  logic [4:0] tokens,weight_base,mask_base;
  logic [5:0] strips;
  logic [9:0] activation_base,issued,retired,total_commands;
  logic [10:0] activation_stride;
  logic [3:0] issue_token,retire_token;
  logic [4:0] issue_strip,retire_strip;
  logic accumulate,publish,flush_second;
  logic context_valid;
  logic [31:0] context_tag;
  logic [4:0] context_tokens,context_mask_base;
  logic [10:0] context_stride;
  logic [26:0] last_activation;
  logic invalid_config,all_results,bad_result,final_strip,accept_command,accept_result;

  always_comb begin
    last_activation=27'(in_activation_base)+(27'(in_tokens)-27'd1)*27'(in_activation_stride)
                    +27'(in_strips)-27'd1;
    invalid_config=in_tokens==0 || in_tokens>16 || in_strips==0 || in_strips>32 ||
      7'(in_weight_base)+7'(in_strips)>32 || 6'(in_mask_base)+6'(in_tokens)>32 ||
      (in_tokens>1 && in_activation_stride<11'(in_strips)) || last_activation>=1024;
    if(in_accumulate && (!context_valid || in_tag!=context_tag || in_tokens!=context_tokens ||
       in_mask_base!=context_mask_base || in_activation_stride!=context_stride))invalid_config=1;
    all_results=&backend_out_valid;
    bad_result=state==RUN && all_results && retired>=issued;
    for(int cluster=0;cluster<5;cluster++)
      if(state==RUN && all_results && backend_out_output[cluster*4+:4]!=retire_token)bad_result=1;
    final_strip=6'(retire_strip)+6'd1==strips;
    in_ready=state==IDLE;
    backend_rst_n=rst_n && state!=FLUSH;
    backend_cmd_valid=state==RUN && issued<total_commands && !bad_result;
    backend_cmd_weight=weight_base+issue_strip;
    backend_cmd_mask=mask_base+5'(issue_token);
    backend_cmd_activation=10'(27'(activation_base)+27'(issue_token)*27'(activation_stride)+27'(issue_strip));
    backend_cmd_output=issue_token;
    backend_cmd_accumulate=accumulate || issue_strip!=0;
    out_valid=state==RUN && all_results && !bad_result && final_strip && publish;
    out_tag=tag;out_token=retire_token;out_last=5'(retire_token)+5'd1==tokens;
    out_data=backend_out_data;
    backend_out_ready={5{state==RUN && all_results && !bad_result && (!final_strip || !publish || out_ready)}};
    accept_command=backend_cmd_valid && backend_cmd_ready;
    accept_result=all_results && (&backend_out_ready);
    done_valid=state==DONE;done_tag=tag;
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if(!rst_n)begin
      state<=IDLE;tag<=0;tokens<=0;weight_base<=0;mask_base<=0;strips<=0;
      activation_base<=0;activation_stride<=0;issued<=0;retired<=0;total_commands<=0;
      issue_token<=0;retire_token<=0;issue_strip<=0;retire_strip<=0;
      accumulate<=0;publish<=0;done_error<=0;flush_second<=0;
      context_valid<=0;context_tag<=0;context_tokens<=0;context_mask_base<=0;context_stride<=0;
    end else case(state)
      IDLE:if(in_valid)begin
        tag<=in_tag;tokens<=in_tokens;strips<=in_strips;weight_base<=in_weight_base;mask_base<=in_mask_base;
        activation_base<=in_activation_base;activation_stride<=in_activation_stride;
        accumulate<=in_accumulate;publish<=in_publish;total_commands<=10'(in_tokens)*10'(in_strips);
        issued<=0;retired<=0;issue_token<=0;retire_token<=0;issue_strip<=0;retire_strip<=0;
        done_error<=invalid_config;
        if(invalid_config)begin context_valid<=0;flush_second<=0;state<=FLUSH;end
        else begin
          if(!in_accumulate)begin
            context_valid<=1;context_tag<=in_tag;context_tokens<=in_tokens;
            context_mask_base<=in_mask_base;context_stride<=in_activation_stride;
          end
          state<=RUN;
        end
      end
      RUN:begin
        if(bad_result)begin context_valid<=0;done_error<=1;flush_second<=0;state<=FLUSH;end
        else begin
          if(accept_command)begin
            issued<=issued+1'b1;
            if(5'(issue_token)+5'd1==tokens)begin issue_token<=0;issue_strip<=issue_strip+1'b1;end
            else issue_token<=issue_token+1'b1;
          end
          if(accept_result)begin
            retired<=retired+1'b1;
            if(5'(retire_token)+5'd1==tokens)begin retire_token<=0;retire_strip<=retire_strip+1'b1;end
            else retire_token<=retire_token+1'b1;
            if(retired+10'd1==total_commands)begin
              if(publish)context_valid<=0;
              state<=DONE;
            end
          end
        end
      end
      FLUSH:if(flush_second)state<=DONE;else flush_second<=1;
      DONE:if(done_ready)state<=IDLE;
      default:begin context_valid<=0;done_error<=1;flush_second<=0;state<=FLUSH;end
    endcase
  end
endmodule
