`timescale 1ns/1ps
// Store projected vectors in head-major memory with 1,024 slots per head.
// Each destination slot must be outside the visible cache until completion
// succeeds. Retrying the same descriptor rewrites all of its provisional slots.
module tri_oracle_qkv_store430 (
    input logic clk, rst_n,
    input logic cfg_valid,
    output logic cfg_ready,
    input logic [31:0] cfg_tag,
    input logic [4:0] cfg_tokens,
    input logic [5:0] cfg_first_head, cfg_heads,
    input logic [9:0] cfg_slot,
    input logic [63:0] cfg_base,
    input logic source_valid, source_last,
    output logic source_ready,
    input logic [31:0] source_tag,
    input logic [5:0] source_head,
    input logic [3:0] source_token,
    input logic [511:0] source_data,
    input logic source_done_valid, source_done_error,
    output logic source_done_ready,
    input logic [31:0] source_done_tag,
    output logic write_valid,
    input logic write_ready,
    output logic [63:0] write_address,
    output logic [511:0] write_data,
    input logic write_rsp_valid, write_rsp_error,
    output logic write_rsp_ready,
    output logic done_valid, done_error,
    input logic done_ready,
    output logic [31:0] done_tag
);
    typedef enum logic [2:0] {Idle, Receive, Issue, AwaitWrite, AwaitDone, Drain, Done} state_t;
    state_t state;
    logic [63:0] base;
    logic [9:0] start_slot;
    logic [4:0] tokens;
    logic [5:0] tile_base, head_limit, expected_head;
    logic [3:0] expected_token;
    logic second_head, two_heads, final_head, final_token, final_tile, expected_last;
    logic [9:0] slot;

    assign cfg_ready = state==Idle;
    assign source_ready = state==Receive || state==AwaitDone || state==Drain;
    assign source_done_ready = source_ready;
    assign write_valid = state==Issue;
    assign write_rsp_ready = state==AwaitWrite;
    assign done_valid = state==Done;
    assign expected_head = tile_base+6'(second_head);
    assign slot = start_slot+10'(expected_token);
    assign two_heads = tile_base+6'd1<head_limit;
    assign final_head = !two_heads || second_head;
    assign final_token = 5'(expected_token)+5'd1==tokens;
    assign final_tile = tile_base+(two_heads ? 6'd2 : 6'd1)==head_limit;
    assign expected_last = final_head && final_token && final_tile;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=Idle;
            base<=0;
            start_slot<=0;
            tokens<=0;
            tile_base<=0;
            head_limit<=0;
            expected_token<=0;
            second_head<=0;
            write_address<=0;
            write_data<=0;
            done_tag<=0;
            done_error<=0;
        end else case (state)
            Idle: if (cfg_valid) begin
                base<=cfg_base;
                start_slot<=cfg_slot;
                tokens<=cfg_tokens;
                tile_base<=cfg_first_head;
                head_limit<=cfg_first_head+cfg_heads;
                expected_token<=0;
                second_head<=0;
                done_tag<=cfg_tag;
                done_error<=0;
                state<=Receive;
            end
            Receive: begin
                if (source_done_valid) begin
                    done_error<=1;
                    state<=Done;
                end else if (source_valid) begin
                    if ({source_tag,source_head,source_token,source_last} !==
                        {done_tag,expected_head,expected_token,expected_last}) begin
                        done_error<=1;
                        state<=Drain;
                    end else begin
                        write_address<=base+64'({expected_head,slot,6'b0});
                        write_data<=source_data;
                        state<=Issue;
                    end
                end
            end
            Issue: if (write_ready) state<=AwaitWrite;
            AwaitWrite: if (write_rsp_valid) begin
                if (write_rsp_error!==1'b0) begin
                    done_error<=1;
                    state<=Drain;
                end else if (expected_last) state<=AwaitDone;
                else begin
                    state<=Receive;
                    if (!final_head) second_head<=1;
                    else begin
                        second_head<=0;
                        if (final_token) begin
                            tile_base<=tile_base+6'd2;
                            expected_token<=0;
                        end else expected_token<=expected_token+1'b1;
                    end
                end
            end
            AwaitDone: begin
                if (source_valid) done_error<=1;
                if (source_done_valid) begin
                    done_error<=done_error || source_valid || source_done_error!==1'b0 ||
                                source_done_tag!==done_tag;
                    state<=Done;
                end
            end
            Drain: if (source_done_valid) state<=Done;
            Done: if (done_ready) state<=Idle;
            default: state<=Idle;
        endcase
    end
endmodule
