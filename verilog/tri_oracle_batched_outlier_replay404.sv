`timescale 1ns/1ps
// Store the flags and signs from a shared normalization pass, then replay
// them across original 32-channel groups. Commit requires acknowledged
// activation writes. An abort during fill or commit invalidates the table.
module tri_oracle_batched_outlier_replay404 (
    input logic clk, rst_n,
    input logic cfg_valid,
    output logic cfg_ready,
    input logic [31:0] cfg_tag,
    input logic [4:0] cfg_tokens,
    input logic [9:0] cfg_strips,
    input logic [7:0] cfg_groups,
    input logic [63:0] cfg_gate_sign_base, cfg_up_sign_base,
    input logic meta_valid, meta_last,
    output logic meta_ready,
    input logic [31:0] meta_tag,
    input logic [3:0] meta_token,
    input logic [9:0] meta_index,
    input logic [7:0] meta_outliers, meta_negative,
    input logic commit_valid, abort_fill,
    output logic commit_ready,
    output logic out_valid,
    input logic out_ready,
    output logic out_last,
    output logic [31:0] out_tag,
    output logic [7:0] out_group,
    output logic [3:0] out_token,
    output logic [31:0] gate_nearzero_mask, up_nearzero_mask, skip_mask,
    output logic [12:0] outlier_count,
    output logic done_valid,
    input logic done_ready,
    output logic done_error,
    output logic [31:0] done_tag,
    output logic req_valid,
    input logic req_ready,
    output logic [63:0] req_address,
    output logic [4:0] req_length,
    input logic rsp_valid,
    output logic rsp_ready,
    input logic rsp_last, rsp_error,
    input logic [63:0] rsp_data
);
    typedef enum logic [3:0] {
        Idle, Fill, Commit, ReadWord, SelectStrip, OfferStrip,
        WaitFetch, CheckGroup, HoldGroup, Done
    } state_t;
    state_t state;
    logic [31:0] tag;
    logic [4:0] tokens;
    logic [9:0] strips;
    logic [7:0] groups, group_index, strip_index;
    logic [3:0] token_index;
    logic [63:0] gate_base, up_base;
    logic [64:0] sign_span, unused_cfg_gate_end, unused_cfg_up_end;
    logic invalid_config, last_token, last_group, last_strip;

    logic invalid_metadata;
    logic [63:0] packed_word, next_word;
    logic mem_write, mem_read;
    logic [8:0] word_address;
    logic [63:0] lower_q, upper_q, selected_word;
    logic [15:0] metadata;
    logic [127:0] sign_proxy;

    logic sign_fault, fetch_in_ready, fetch_valid, fetch_last, fetch_error;
    logic [31:0] unused_fetch_tag;
    logic [10:0] unused_fetch_group;
    logic [9:0] unused_fetch_index;
    logic [127:0] fetch_data;
    logic [255:0] gate_signs, up_signs;
    logic pred_in_ready, pred_valid, pred_ready, pred_error;

    assign meta_ready = state == Fill && !abort_fill;

    always_comb begin
        sign_span = (65'(cfg_groups) * 65'(cfg_strips)) << 5;
        unused_cfg_gate_end = {1'b0, cfg_gate_sign_base} + sign_span - 65'd1;
        unused_cfg_up_end = {1'b0, cfg_up_sign_base} + sign_span - 65'd1;
        invalid_config = cfg_tokens == 0 || cfg_tokens > 16 || cfg_strips == 0 ||
            cfg_strips > 256 || cfg_groups == 0 || cfg_gate_sign_base[2:0] != 0 ||
            cfg_up_sign_base[2:0] != 0 || unused_cfg_gate_end[64] || unused_cfg_up_end[64];
        last_token = {1'b0, token_index} + 5'd1 == tokens;
        last_group = group_index == groups - 8'd1;
        last_strip = {2'b00, strip_index} + 10'd1 == strips;

        invalid_metadata = meta_tag != tag || meta_token != token_index ||
            meta_index != {2'b00, strip_index} || meta_last != last_strip;
        next_word = strip_index[1:0] == 0 ? '0 : packed_word;
        next_word[16*strip_index[1:0] +: 16] = {meta_negative & meta_outliers, meta_outliers};
        mem_write = rst_n && meta_valid && meta_ready && !invalid_metadata &&
            (last_strip || strip_index[1:0] == 3);
        mem_read = rst_n && state == ReadWord;
        word_address = {token_index[2:0], strip_index[7:2]};
        selected_word = token_index[3] ? upper_q : lower_q;
        metadata = selected_word[16*strip_index[1:0] +: 16];
        for (int lane = 0; lane < 8; lane++) begin
            if (!metadata[lane]) sign_proxy[16*lane +: 16] = '0;
            else if (metadata[8+lane]) sign_proxy[16*lane +: 16] = -16'sd769;
            else sign_proxy[16*lane +: 16] = 16'sd769;
        end

        cfg_ready = state == Idle;
        commit_ready = state == Commit && !abort_fill;
        out_valid = state == HoldGroup && pred_valid;
        out_last = out_valid && last_group && last_token;
        out_tag = tag;
        out_group = group_index;
        out_token = token_index;
        done_valid = state == Done;
        done_tag = tag;
        pred_ready = (state == HoldGroup && out_ready) ||
            (state == CheckGroup && (sign_fault || pred_error));
    end

    TS5N28HPCPSVTA512X64M4F lower_metadata (
        .CLK(clk), .CEB(!(mem_write || mem_read) || token_index[3]),
        .WEB(!mem_write), .A(word_address), .D(next_word), .Q(lower_q)
    );
    TS5N28HPCPSVTA512X64M4F upper_metadata (
        .CLK(clk), .CEB(!(mem_write || mem_read) || !token_index[3]),
        .WEB(!mem_write), .A(word_address), .D(next_word), .Q(upper_q)
    );

    tri_oracle_sign_fetch sign_memory (
        .clk(clk), .rst_n(rst_n), .in_valid(state == OfferStrip), .in_ready(fetch_in_ready),
        .in_tag(tag), .in_group({3'b000, group_index}), .in_strips(strips),
        .in_index({2'b00, strip_index}), .in_last(last_strip), .in_error(sign_fault),
        .in_norm_q8(sign_proxy), .in_gate_base(gate_base), .in_up_base(up_base),
        .out_valid(fetch_valid), .out_ready(state == WaitFetch && pred_in_ready),
        .out_last(fetch_last), .out_error(fetch_error), .out_tag(unused_fetch_tag),
        .out_group(unused_fetch_group), .out_index(unused_fetch_index),
        .out_norm_q8(fetch_data), .out_gate_signs(gate_signs), .out_up_signs(up_signs),
        .req_valid(req_valid), .req_ready(req_ready), .req_address(req_address),
        .req_length(req_length), .rsp_valid(rsp_valid), .rsp_ready(rsp_ready),
        .rsp_last(rsp_last), .rsp_error(rsp_error), .rsp_data(rsp_data)
    );

    tri_oracle_strip_predictor predictor (
        .clk(clk), .rst_n(rst_n), .in_valid(state == WaitFetch && fetch_valid),
        .in_ready(pred_in_ready), .in_last(fetch_last), .out_ready(pred_ready),
        .norm_activations(fetch_data), .gate_weight_signs(gate_signs), .up_weight_signs(up_signs),
        .out_valid(pred_valid), .out_error(pred_error), .gate_nearzero_mask(gate_nearzero_mask),
        .up_nearzero_mask(up_nearzero_mask), .skip_mask(skip_mask), .outlier_count(outlier_count)
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= Idle;
            tag <= '0;
            tokens <= '0; strips <= '0; groups <= '0;
            gate_base <= '0; up_base <= '0;
            token_index <= '0; group_index <= '0; strip_index <= '0;
            packed_word <= '0;
            sign_fault <= 0;
            done_error <= 0;
        end else case (state)
            Idle: if (cfg_valid) begin
                tag <= cfg_tag;
                tokens <= cfg_tokens; strips <= cfg_strips; groups <= cfg_groups;
                gate_base <= cfg_gate_sign_base; up_base <= cfg_up_sign_base;
                token_index <= '0; group_index <= '0; strip_index <= '0;
                sign_fault <= 0;
                done_error <= invalid_config;
                if (invalid_config) state <= Done;
                else state <= Fill;
            end
            Fill: begin
                if (abort_fill || (meta_valid && invalid_metadata)) begin
                    done_error <= 1;
                    state <= Done;
                end else if (meta_valid) begin
                    packed_word <= next_word;
                    if (last_strip) begin
                        strip_index <= '0;
                        token_index <= last_token ? '0 : token_index + 4'd1;
                        if (last_token) state <= Commit;
                    end else strip_index <= strip_index + 8'd1;
                end
            end
            Commit: begin
                if (abort_fill) begin
                    done_error <= 1;
                    state <= Done;
                end else if (commit_valid) state <= ReadWord;
            end
            ReadWord: state <= SelectStrip;
            SelectStrip: begin
                // Empty strips have zero contribution. A final empty strip still
                // terminates the predictor's ready/valid frame.
                if (metadata[7:0] != 0 || last_strip) state <= OfferStrip;
                else begin
                    strip_index <= strip_index + 8'd1;
                    if (strip_index[1:0] == 3) state <= ReadWord;
                end
            end
            OfferStrip: if (fetch_in_ready) state <= WaitFetch;
            WaitFetch: if (fetch_valid && pred_in_ready) begin
                sign_fault <= sign_fault || fetch_error;
                if (fetch_last) state <= CheckGroup;
                else if (fetch_error) begin
                    // The memory engine already drained the failed response.
                    // End the predictor frame without any further sign reads.
                    strip_index <= 8'(strips - 10'd1);
                    state <= OfferStrip;
                end else begin
                    strip_index <= strip_index + 8'd1;
                    state <= strip_index[1:0] == 3 ? ReadWord : SelectStrip;
                end
            end
            CheckGroup: if (pred_valid) begin
                done_error <= sign_fault || pred_error;
                state <= (sign_fault || pred_error) ? Done : HoldGroup;
            end
            HoldGroup: if (out_ready && pred_valid) begin
                strip_index <= '0;
                if (last_token) begin
                    token_index <= '0;
                    group_index <= group_index + 8'd1;
                end else token_index <= token_index + 4'd1;
                state <= last_token && last_group ? Done : ReadWord;
            end
            Done: if (done_ready) state <= Idle;
            default: begin done_error <= 1; state <= Done; end
        endcase
    end
endmodule
