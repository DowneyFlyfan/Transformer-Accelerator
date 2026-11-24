`timescale 1ns/1ps
// Publish a complete set of successful head predictions atomically. The caller
// assigns a fresh, 32-aligned tag per frame and tag+head to each prediction.
module tri_oracle_head_mask_commit (
    input logic clk,rst_n,cancel,
    input logic cfg_valid,
    output logic cfg_ready,
    input logic [31:0] cfg_heads,cfg_tag,
    input logic [15:0] cfg_epoch,
    input logic result_valid,
    output logic result_ready,
    input logic [4:0] result_head,
    input logic [31:0] result_tag,
    input logic result_error,result_streaming,
    output logic mask_valid,
    input logic mask_ready,
    output logic [31:0] mask_heads,mask_streaming,mask_tag,
    output logic [15:0] mask_epoch,
    output logic mask_error
);
    typedef enum logic [1:0] {Idle,Collect,Complete} state_t;
    state_t state;
    logic [31:0] requested,seen,provisional,tag,one_head;
    logic [15:0] epoch;
    logic failed;

    always_comb begin
        one_head=32'd1<<result_head;
        cfg_ready=state==Idle && !cancel;
        result_ready=state==Collect && !cancel;
        mask_valid=state==Complete;
        mask_heads=mask_valid && !failed ? requested:32'd0;
        mask_streaming=mask_valid && !failed ? provisional:32'd0;
        mask_tag=tag;mask_epoch=epoch;mask_error=failed;
    end
    always_ff @(posedge clk or negedge rst_n) begin
        if(!rst_n)begin
            state<=Idle;requested<=0;seen<=0;provisional<=0;
            tag<=0;epoch<=0;failed<=0;
        end else begin
            case(state)
                Idle:if(cfg_valid && cfg_ready)begin
                    requested<=cfg_heads;tag<=cfg_tag;epoch<=cfg_epoch;
                    seen<=0;provisional<=0;
                    failed<=cfg_heads==0 || cfg_tag[4:0]!=0;
                    state<=cfg_heads==0 || cfg_tag[4:0]!=0 ? Complete:Collect;
                end
                Collect:begin
                    if(cancel)begin failed<=1;state<=Complete;end
                    else if(result_valid && result_ready)begin
                        if(result_error || result_tag!={tag[31:5],result_head} ||
                           (requested&one_head)==0 || (seen&one_head)!=0)begin
                            failed<=1;state<=Complete;
                        end else begin
                            seen<=seen|one_head;
                            provisional[result_head]<=result_streaming;
                            if((seen|one_head)==requested)state<=Complete;
                        end
                    end
                end
                Complete:if(mask_ready)begin
                    state<=Idle;requested<=0;seen<=0;provisional<=0;
                    failed<=0;tag<=0;epoch<=0;
                end
                default:begin state<=Idle;failed<=0;end
            endcase
        end
    end
endmodule
