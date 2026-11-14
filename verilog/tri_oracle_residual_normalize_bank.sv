`timescale 1ns/1ps

// The frame scheduler owns the bank lease until the terminal activation
// and any later residual read response have retired. One token has 256 strips.
module tri_oracle_residual_normalize_bank (
    input logic clk, rst_n, lease_granted,
    input logic cfg_valid, cfg_token,
    output logic cfg_ready,
    input logic [31:0] cfg_tag, cfg_epsilon_q16,
    input logic [5:0] cfg_shift,
    input logic in_valid,
    output logic in_ready,
    input logic [279:0] residual_q32,
    input logic [63:0] projection_codes,
    input logic [4:0] projection_shift,
    input logic gamma_valid,
    output logic gamma_ready,
    output logic [7:0] gamma_strip,
    input logic [127:0] gamma_data,
    output logic out_valid,
    input logic out_ready,
    output logic out_last, out_error,
    output logic [31:0] out_tag,
    output logic [9:0] out_index,
    output logic [3:0] out_count,
    output logic [127:0] out_norm_q8,
    output logic [7:0] out_outlier_mask,
    output logic [63:0] out_activation,
    input logic read_valid,
    output logic read_ready,
    input logic [8:0] read_row,
    output logic response_valid,
    input logic response_ready,
    output logic [231:0] response_data,
    output logic bank_ce_n, bank_we_n,
    output logic [8:0] bank_addr,
    output logic [255:0] bank_d,
    input logic [255:0] bank_q
);
    typedef enum logic [1:0] {Idle, Collect, Replay, Finish} state_t;
    state_t state;
    logic token;
    logic [8:0] inputs;
    logic [7:0] replay_strip;
    logic write_valid, write_ready, norm_valid, norm_ready, producer_ready;
    logic stats_finished, writes_finished, last_stats, last_write;
    logic [8:0] write_row, norm_row, req_row;
    logic [231:0] write_data, rsp_data;
    logic [127:0] norm_data, replay_data;
    logic [23:0] write_padding;
    logic [255:0] bypass_only;
    logic norm_cfg_ready, stats_ready, replay_ready;
    logic req_valid, req_ready, rsp_valid, rsp_ready;

    // The last statistics strip can retire before or after its bank write.
    // Start reading only after both consumers have accepted it.
    assign cfg_ready = rst_n && lease_granted && state == Idle && norm_cfg_ready && !rsp_valid;
    assign in_ready = state == Collect && inputs < 9'd256 && producer_ready;
    assign norm_ready = state == Collect && stats_ready;
    assign last_stats = norm_valid && norm_ready && (&norm_row[7:0]);
    assign last_write = write_valid && write_ready && (&write_row[7:0]);
    assign read_ready = state == Idle && !cfg_valid && req_ready;
    assign response_valid = state == Idle && rsp_valid;
    assign response_data = response_valid ? rsp_data : '0;
    assign gamma_strip = replay_strip;
    assign gamma_ready = state == Replay && rsp_valid && replay_ready;

    assign req_valid = (state == Collect && write_valid) ||
                       (state == Replay && replay_ready) ||
                       (state == Idle && !cfg_valid && read_valid);
    assign req_row = state == Collect ? write_row : state == Replay ? {token, replay_strip} : read_row;
    assign rsp_ready = state == Idle ? response_ready : gamma_valid && gamma_ready;
    assign write_ready = state == Collect && req_ready;
    assign bank_d = {write_padding, bypass_only[231:0]};

    tri_oracle_attention_residual_store producer (
        .clk, .rst_n, .in_valid(in_valid && state == Collect && inputs < 9'd256),
        .in_ready(producer_ready), .in_row({token, inputs[7:0]}),
        .residual_q32, .projection_codes, .projection_shift,
        .write_valid, .write_ready, .write_row, .write_data, .norm_valid, .norm_ready, .norm_row, .norm_data
    );
    tri_oracle_residual_bank_adapter banks (
        .clk, .rst_n, .lease_granted, .req_valid, .req_ready, .req_write(state == Collect),
        .req_token(req_row[8]), .req_strip(req_row[7:0]), .req_data(write_data),
        .rsp_valid, .rsp_ready, .rsp_data, .bank_ce_n, .bank_we_n, .bank_addr,
        .bank_d(bypass_only), .bank_q
    );
    tri_oracle_residual_replay_row codec (
        .write_bypass(write_data), .write_normalization(norm_data), .write_padding,
        .read_bypass(rsp_data), .read_padding(bank_q[255:232]), .read_normalization(replay_data)
    );
    tri_oracle_rms_activation activation (
        .clk, .rst_n, .cfg_valid(cfg_valid && cfg_ready), .cfg_ready(norm_cfg_ready),
        .cfg_tag, .cfg_epsilon_q16, .cfg_strips(10'd256), .cfg_shift,
        .stats_valid(state == Collect && norm_valid), .stats_ready,
        .stats_last(&norm_row[7:0]), .stats_data(norm_data),
        .replay_valid(state == Replay && rsp_valid && gamma_valid), .replay_ready,
        .replay_last(&replay_strip), .replay_data, .replay_gamma(gamma_data),
        .out_valid, .out_ready, .out_last, .out_error, .out_tag, .out_index,
        .out_count, .out_norm_q8, .out_outlier_mask, .out_activation
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= Idle;
            token <= 0;
            inputs <= 0;
            replay_strip <= 0;
            stats_finished <= 0;
            writes_finished <= 0;
        end else if (out_valid && out_ready && out_last) begin
            state <= Idle;
        end else case (state)
            Idle: if (cfg_valid && cfg_ready) begin
                state <= Collect;
                token <= cfg_token;
                inputs <= 0;
                replay_strip <= 0;
                stats_finished <= 0;
                writes_finished <= 0;
            end
            Collect: begin
                if (in_valid && in_ready) inputs <= inputs + 9'd1;
                if (last_stats) stats_finished <= 1;
                if (last_write) writes_finished <= 1;
                if ((stats_finished || last_stats) && (writes_finished || last_write)) state <= Replay;
            end
            Replay: if (gamma_valid && gamma_ready) begin
                if (&replay_strip) state <= Finish;
                else replay_strip <= replay_strip + 8'd1;
            end
            default: ;
        endcase
    end
endmodule
