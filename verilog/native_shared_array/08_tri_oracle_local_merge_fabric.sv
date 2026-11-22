`timescale 1ns/1ps

package tri_oracle_merge_range_types;
    typedef struct packed {
        logic cfg_valid, cfg_new_image;
        logic [11:0] threshold;
        logic sign_valid, map_ready, done_ready;
    } request_t;
    typedef struct packed {
        logic cfg_ready, sign_ready, map_valid;
        logic [9:0] map_index, map_origin;
        logic map_last, done_valid, done_error;
    } response_t;

    typedef struct packed {
        logic cfg_valid, cfg_new_image;
        logic [11:0] threshold;
        logic sign_valid, map_ready, done_ready;
        logic [359:0] frontier;
    } range_command_t;

    typedef struct packed {
        logic cfg_ready, sign_ready, map_valid, map_last, done_valid, done_error;
        logic [9:0] map_index, map_origin;
        logic [12:0] sign_control;
        logic [21:0] table_request;
        logic [359:0] frontier;
    } range_result_t;
endpackage

// A range owns its token decisions and table writes. Raster seams transfer
// only the live frontier; similarity counts keep their feature-bank layout.
module tri_oracle_merge_range_relay (
    input logic clk, rst_n,
    input logic cfg_valid, cfg_new_image,
    output logic cfg_ready,
    input logic [11:0] cfg_minimum_matches,
    input logic sign_valid,
    output logic sign_ready,
    output logic map_valid,
    input logic map_ready,
    output logic [9:0] map_index, map_origin,
    output logic map_last, done_valid, done_error,
    input logic done_ready,
    output logic [12:0] sign_control,
    output logic [21:0] table_request,
    output tri_oracle_merge_range_types::range_command_t [4:0] commands,
    input tri_oracle_merge_range_types::range_result_t [4:0] results
);
    typedef enum logic [1:0] {Idle, Run, Handoff, Result} state_t;
    state_t state;
    logic [2:0] active_bank;
    logic has_map, new_image, bad_configuration, finish_range;
    logic [11:0] threshold;
    tri_oracle_merge_range_types::range_result_t active_result, first_result;

    assign first_result=results[0];
    assign active_result=results[active_bank];
    assign bad_configuration=cfg_minimum_matches>12'd2048 || (!cfg_new_image && !has_map);
    assign cfg_ready=state==Idle && first_result.cfg_ready;
    assign sign_ready=state==Run && active_result.sign_ready;
    assign map_valid=state==Run && active_result.map_valid;
    assign map_index=active_result.map_index;
    assign map_origin=active_result.map_origin;
    assign map_last=map_valid && active_result.map_last;
    assign sign_control=state==Run ? active_result.sign_control : '0;
    assign table_request=state==Run ? active_result.table_request : '0;
    assign finish_range=state==Run && active_result.done_valid;
    assign done_valid=state==Result;

    for (genvar bank=0;bank<5;bank++) begin : route
        tri_oracle_merge_range_types::range_command_t command;
        assign commands[bank]=command;
        if (bank==0) begin : first
            assign command.cfg_valid=cfg_valid && cfg_ready && !bad_configuration;
            assign command.cfg_new_image=cfg_new_image;
            assign command.threshold=cfg_minimum_matches;
            assign command.frontier='0;
        end else begin : next
            tri_oracle_merge_range_types::range_result_t predecessor;
            assign predecessor=results[bank-1];
            assign command.cfg_valid=state==Handoff && active_bank==3'(bank);
            assign command.cfg_new_image=new_image;
            assign command.threshold=threshold;
            assign command.frontier=predecessor.frontier;
        end
        assign command.sign_valid=state==Run && active_bank==3'(bank) && sign_valid;
        assign command.map_ready=state==Run && active_bank==3'(bank) && map_ready;
        assign command.done_ready=state==Run && active_bank==3'(bank);
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=Idle;
            active_bank<='0;
            has_map<=0;
            new_image<=1;
            threshold<='0;
            done_error<=0;
        end else case (state)
            Idle: if (cfg_valid && cfg_ready) begin
                new_image<=cfg_new_image;
                threshold<=cfg_minimum_matches;
                active_bank<='0;
                done_error<=bad_configuration;
                if (bad_configuration) state<=Result;
                else state<=Run;
            end
            Run: if (finish_range) begin
                if (active_result.done_error || active_bank==3'd4) begin
                    done_error<=active_result.done_error;
                    has_map<=!active_result.done_error;
                    state<=Result;
                end else begin
                    active_bank<=active_bank+1'b1;
                    state<=Handoff;
                end
            end
            Handoff: if (active_result.cfg_ready) state<=Run;
            Result: if (done_ready) state<=Idle;
            default: begin
                state<=Result;
                has_map<=0;
                done_error<=1;
            end
        endcase
    end
endmodule

module tri_oracle_aggregator_token_merge_unit #(
    parameter int BANK_START=0, ENTRIES=128, FEATURES=512
) (
    input logic clk, rst_n,
    input tri_oracle_merge_range_types::range_command_t command,
    output tri_oracle_merge_range_types::range_result_t result,
    input logic [FEATURES-1:0] sign_data,
    input logic [12:0] sign_control,
    input logic [119:0] all_sign_counts,
    output logic [23:0] sign_counts,
    input logic [79:0] table_word,
    input tri_oracle_token_size_types::bank_command_t size_command,
    output tri_oracle_token_size_types::bank_result_t size_result
);
    tri_oracle_cumulative_merge447 #(
        .COMPILED_SIGN_BANK(1), .AGGREGATOR_SIGN_BANK(1), .AGGREGATOR_MERGE_TABLE(1),
        .RANGE_START(BANK_START), .RANGE_END(BANK_START+ENTRIES)
    ) merge_controller (
        .clk, .rst_n, .cfg_valid(command.cfg_valid), .cfg_new_image(command.cfg_new_image),
        .cfg_ready(result.cfg_ready), .cfg_minimum_matches(command.threshold),
        .sign_valid(command.sign_valid), .sign_ready(result.sign_ready), .sign_data(2048'd0),
        .map_valid(result.map_valid), .map_ready(command.map_ready),
        .map_index(result.map_index), .map_origin(result.map_origin), .map_last(result.map_last),
        .done_valid(result.done_valid), .done_error(result.done_error), .done_ready(command.done_ready),
        .merge_sign_control(result.sign_control), .merge_sign_counts(all_sign_counts),
        .merge_table_request(result.table_request), .merge_table_word(table_word),
        .frontier_in(command.frontier), .frontier_out(result.frontier)
    );
    tri_oracle_aggregator_sign447 #(
        .FEATURES(FEATURES), .COMPILED_SIGN_BANK(1), .COMPACT_SIGN_DEPTH(1)
    ) similarity (.clk, .sign_data, .control(sign_control), .counts(sign_counts));
    tri_oracle_token_size_bank #(.BANK_START(BANK_START), .ENTRIES(ENTRIES)) sizes (
        .clk, .rst_n, .command(size_command), .result(size_result)
    );
endmodule

// Standalone composition of the five physical token-merging units and their
// shared raster and causal-query interfaces. The compute clusters can use
// these same aggregator units and relay ports directly.
module tri_oracle_local_merge_fabric (
    input logic clk, rst_n,
    input logic cfg_valid, cfg_new_image,
    output logic cfg_ready,
    input logic [11:0] cfg_minimum_matches,
    input logic sign_valid,
    output logic sign_ready,
    input logic [2047:0] sign_data,
    output logic map_valid,
    input logic map_ready,
    output logic [9:0] map_index, map_origin,
    output logic map_last, done_valid, done_error,
    input logic done_ready,
    input logic size_frame_valid,
    output logic size_frame_ready,
    input logic size_map_valid,
    output logic size_map_ready,
    input logic query_valid,
    output logic query_ready,
    input logic [9:0] query_position,
    output logic out_valid,
    input logic out_ready,
    output logic [9:0] out_origin, out_count,
    output logic out_last, size_error
);
    tri_oracle_merge_range_types::range_command_t [4:0] commands;
    tri_oracle_merge_range_types::range_result_t [4:0] results;
    tri_oracle_token_size_types::bank_command_t [4:0] size_command;
    tri_oracle_token_size_types::bank_result_t [4:0] size_result;
    logic [12:0] sign_control;
    logic [119:0] sign_counts;
    logic [21:0] table_request;
    logic [79:0] table_word;

    tri_oracle_merge_range_relay relay (
        .clk, .rst_n, .cfg_valid, .cfg_new_image, .cfg_ready, .cfg_minimum_matches,
        .sign_valid, .sign_ready, .map_valid, .map_ready, .map_index, .map_origin, .map_last,
        .done_valid, .done_error, .done_ready, .sign_control, .table_request, .commands, .results
    );
    tri_oracle_token_size_control token_sizes (
        .clk, .rst_n, .frame_valid(size_frame_valid), .frame_ready(size_frame_ready),
        .map_valid(size_map_valid), .map_ready(size_map_ready), .map_origin, .map_last,
        .query_valid, .query_ready, .query_position, .out_valid, .out_ready, .out_origin, .out_count,
        .out_last, .error(size_error), .table_request, .table_word,
        .bank_command(size_command), .bank_result(size_result)
    );
    for (genvar bank=0;bank<5;bank++) begin : aggregator
        localparam int FIRST=bank==0 ? 0 : 512+(bank-1)*384;
        localparam int FEATURES=bank==0 ? 512 : 384;
        tri_oracle_aggregator_token_merge_unit #(
            .BANK_START(bank*128), .ENTRIES(bank==4 ? 64 : 128), .FEATURES(FEATURES)
        ) unit (
            .clk, .rst_n, .command(commands[bank]), .result(results[bank]),
            .sign_data(sign_data[FIRST+:FEATURES]), .sign_control,
            .all_sign_counts(sign_counts), .sign_counts(sign_counts[bank*24+:24]),
            .table_word, .size_command(size_command[bank]), .size_result(size_result[bank])
        );
    end
endmodule
