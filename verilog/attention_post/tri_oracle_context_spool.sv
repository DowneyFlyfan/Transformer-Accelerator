`timescale 1ns/1ps

// Collect one query from the attention broker into external scratch. Each head
// occupies 256 bytes. The following 32 words hold zero-padded 9-bit units.
// On broker success, reread the scratch and write 2,048 signed context codes.
// Only a successful done handshake publishes the codes and common unit.
// The caller owns both allocations until completion and resets bus peers together.
module tri_oracle_context_spool (
    input logic clk, rst_n, cfg_valid,
    output logic cfg_ready,
    input logic [31:0] cfg_tag,
    input logic [15:0] cfg_query, cfg_epoch,
    input logic [63:0] cfg_spool_base, cfg_code_base,
    input logic [287:0] cfg_weight_units, cfg_output_units,

    input logic context_valid,
    output logic context_ready,
    input logic [31:0] context_tag,
    input logic [15:0] context_query, context_epoch,
    input logic [4:0] context_head,
    input logic signed [8:0] context_unit,
    input logic [2047:0] context_data,
    input logic broker_done_valid, broker_done_error,
    output logic broker_done_ready,

    output logic done_valid, done_error,
    input logic done_ready,
    output logic [31:0] done_tag,
    output logic [15:0] done_query, done_epoch,
    output logic signed [9:0] done_unit,

    output logic wr_req_valid,
    input logic wr_req_ready,
    output logic [63:0] wr_address,
    output logic [4:0] wr_length,
    output logic wr_data_valid,
    input logic wr_data_ready,
    output logic [63:0] wr_data,
    output logic wr_last, wr_rsp_ready,
    input logic wr_rsp_valid, wr_error,

    output logic rd_req_valid,
    input logic rd_req_ready,
    output logic [63:0] rd_address,
    output logic [4:0] rd_length,
    input logic rd_rsp_valid, rd_last, rd_error,
    output logic rd_rsp_ready,
    input logic [63:0] rd_data
);
    typedef enum logic [3:0] {Idle, Collect, WriteHeader, WriteData, WriteAck,
                              SelectUnit, ReadHeader, ReadData, DrainRead, Done} state_t;
    typedef enum logic [1:0] {Raw, UnitWord, Code} write_kind_t;
    state_t state;
    write_kind_t write_kind;
    logic [31:0] present;
    logic broker_finished, broker_failed, failed, read_unit, half_row;
    logic [63:0] spool_base, code_base;
    logic [4:0] head;
    logic [3:0] beat;
    logic [2047:0] head_data;
    // During conversion the same packet register holds each 32-byte output tile.
    logic signed [8:0] value_unit, min_value_unit, max_value_unit;
    logic signed [9:0] nonzero_unit, min_difference, max_difference;
    logic has_nonzero, broker_error_fire;
    logic [31:0] peak;

    function automatic logic [31:0] magnitude(input logic [31:0] value);
        return value[31] ? -value : value;
    endfunction

    // Smallest dyadic unit that fits the unrounded absolute peak.
    function automatic logic signed [9:0] unit_for_peak(
        input logic [31:0] value_peak, input logic signed [8:0] exponent);
        logic [63:0] threshold;
        for (int power = -22; power <= 9; power++) begin
            threshold = power < 0 ? (64'd8322945 >> -power) : (64'd8322945 << power);
            if (64'(value_peak) <= threshold) return 10'(int'(exponent) + power);
        end
        return 10'(int'(exponent) + 9);  // The last threshold exceeds 2^31.
    endfunction

    logic [64:0] spool_last, code_last;
    logic signed [9:0] cfg_min_difference, cfg_max_difference, difference;
    logic cfg_bad;
    always_comb begin
        spool_last = {1'b0, cfg_spool_base} + 65'd8447;
        code_last = {1'b0, cfg_code_base} + 65'd2047;
        cfg_bad = $isunknown({cfg_spool_base,cfg_code_base,cfg_tag,cfg_query,cfg_epoch,
                              cfg_weight_units,cfg_output_units}) ||
                  cfg_spool_base[5:0] != 0 || cfg_code_base[5:0] != 0 ||
                  spool_last[64] || code_last[64] ||
                  !(spool_last < {1'b0,cfg_code_base} || code_last < {1'b0,cfg_spool_base});
        cfg_min_difference = 10'sd511;
        cfg_max_difference = 10'sh200;
        for (int i = 0; i < 32; i++) begin
            difference = 10'($signed(cfg_output_units[i*9+:9])) -
                         10'($signed(cfg_weight_units[i*9+:9]));
            if (difference < cfg_min_difference) cfg_min_difference = difference;
            if (difference > cfg_max_difference) cfg_max_difference = difference;
        end
    end

    function automatic integer maximum(input integer a, b);
        return a > b ? a : b;
    endfunction
    function automatic integer minimum(input integer a, b);
        return a < b ? a : b;
    endfunction
    integer lower, legacy_upper, expanded_upper, selected;
    always_comb begin
        lower = maximum(int'(max_value_unit) - 31, int'(max_difference) - 48);
        legacy_upper = minimum(int'(min_value_unit), int'(min_difference) - 1);
        expanded_upper = minimum(int'(min_value_unit) + 31, int'(min_difference) - 1);
        if (has_nonzero) selected = int'(nonzero_unit);
        else selected = lower <= legacy_upper ? legacy_upper : expanded_upper;
    end

    logic signed [10:0] transfer, stored_transfer;
    logic [4:0] shift;
    logic [15:0] code_pair;
    assign transfer = 11'(value_unit) - 11'(done_unit);
    assign stored_transfer = 11'($signed(rd_data[8:0])) - 11'(done_unit);
    assign shift = transfer < 0 ? 5'(-transfer) : 5'(transfer);
    for (genvar lane = 0; lane < 2; lane++) begin : convert
        tri_oracle_attention_projection_scale_quotient_first scale (
            .accumulator(rd_data[32*lane+:32]), .scale_right(transfer < 0),
            .scale_shift(shift), .projection_code(code_pair[8*lane+:8])
        );
    end

    assign cfg_ready = rst_n && state == Idle;
    assign context_ready = rst_n && state == Collect && !broker_finished;
    assign broker_done_ready = rst_n && state != Idle && state != Done && !broker_finished;
    assign broker_error_fire = broker_done_ready && broker_done_valid && broker_done_error !== 1'b0;
    assign done_valid = rst_n && state == Done;
    assign done_error = failed;
    assign wr_req_valid = rst_n && state == WriteHeader;
    assign wr_data_valid = rst_n && state == WriteData;
    assign wr_rsp_ready = rst_n && state == WriteAck;
    assign rd_req_valid = rst_n && state == ReadHeader;
    assign rd_rsp_ready = rst_n && (state == ReadData || state == DrainRead);

    logic [63:0] raw_address, unit_address;
    assign raw_address = spool_base + (64'(head) << 8) + (half_row ? 64'd128 : 0);
    assign unit_address = spool_base + 64'd8192 + (64'(head) << 3);
    always_comb begin
        case (write_kind)
            Raw: begin
                wr_address = raw_address;
                wr_length = 16;
                wr_data = head_data[64*{half_row,beat}+:64];
            end
            UnitWord: begin
                wr_address = unit_address;
                wr_length = 1;
                wr_data = {55'b0,value_unit};
            end
            default: begin
                wr_address = code_base + (64'(head) << 6) + (half_row ? 64'd32 : 0);
                wr_length = 4;
                wr_data = head_data[64*beat[1:0]+:64];
            end
        endcase
        wr_last = {1'b0,beat} == wr_length - 5'd1;
        rd_address = read_unit ? unit_address : raw_address;
        rd_length = read_unit ? 1 : 16;
    end

    logic [31:0] low_mag, high_mag, pair_peak;
    logic signed [9:0] head_candidate;
    assign low_mag = magnitude(wr_data[31:0]);
    assign high_mag = magnitude(wr_data[63:32]);
    assign pair_peak = low_mag > high_mag ? low_mag : high_mag;
    assign head_candidate = unit_for_peak(peak, value_unit);

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= Idle;
            failed <= 0;
            broker_finished <= 0;
            broker_failed <= 0;
            done_unit <= 0;
            done_tag <= 0;
            done_query <= 0;
            done_epoch <= 0;
        end else begin
            if (broker_done_valid && broker_done_ready) begin
                broker_finished <= 1;
                broker_failed <= broker_done_error !== 1'b0;
            end
            case (state)
                Idle: if (cfg_valid) begin
                    done_tag <= cfg_tag;
                    done_query <= cfg_query;
                    done_epoch <= cfg_epoch;
                    spool_base <= cfg_spool_base;
                    code_base <= cfg_code_base;
                    min_difference <= cfg_min_difference;
                    max_difference <= cfg_max_difference;
                    min_value_unit <= 9'sd255;
                    max_value_unit <= 9'sh100;
                    present <= 0;
                    has_nonzero <= 0;
                    nonzero_unit <= 0;
                    done_unit <= 0;
                    broker_finished <= 0;
                    broker_failed <= 0;
                    failed <= cfg_bad;
                    state <= cfg_bad ? Done : Collect;
                end
                Collect: if (broker_finished) begin
                    if (failed || broker_failed || present != '1) begin
                        failed <= 1;
                        state <= Done;
                    end else state <= SelectUnit;
                end else if (context_valid && !failed && !broker_error_fire) begin
                    if ($isunknown({context_head,context_unit,context_data}) ||
                        context_tag !== done_tag || context_query !== done_query ||
                        context_epoch !== done_epoch || present[context_head]) failed <= 1;
                    else begin
                        head <= context_head;
                        head_data <= context_data;
                        value_unit <= context_unit;
                        half_row <= 0;
                        beat <= 0;
                        peak <= 0;
                        write_kind <= Raw;
                        state <= WriteHeader;
                    end
                end
                WriteHeader: if (wr_req_ready) begin
                    beat <= 0;
                    state <= WriteData;
                end
                WriteData: if (wr_data_ready) begin
                    if (write_kind == Raw && pair_peak > peak) peak <= pair_peak;
                    if (wr_last) state <= WriteAck;
                    else beat <= beat + 1'b1;
                end
                WriteAck: if (wr_rsp_valid) begin
                    if (wr_error !== 1'b0 || broker_failed || broker_error_fire) begin
                        failed <= 1;
                        state <= broker_finished ? Done : Collect;
                    end else case (write_kind)
                        Raw: begin
                            if (half_row) write_kind <= UnitWord;
                            else half_row <= 1;
                            state <= WriteHeader;
                        end
                        UnitWord: begin
                            present[head] <= 1;
                            if (value_unit < min_value_unit) min_value_unit <= value_unit;
                            if (value_unit > max_value_unit) max_value_unit <= value_unit;
                            if (peak != 0) begin
                                has_nonzero <= 1;
                                if (!has_nonzero || head_candidate > nonzero_unit)
                                    nonzero_unit <= head_candidate;
                            end
                            state <= Collect;
                        end
                        Code: if (head == 31 && half_row) state <= Done;
                        else begin
                            if (half_row) head <= head + 1'b1;
                            read_unit <= half_row;
                            half_row <= !half_row;
                            state <= ReadHeader;
                        end
                    endcase
                end
                SelectUnit: begin
                    if (selected < lower || selected > expanded_upper) begin
                        failed <= 1;
                        state <= Done;
                    end else begin
                        done_unit <= 10'(selected);
                        head <= 0;
                        half_row <= 0;
                        read_unit <= 1;
                        state <= ReadHeader;
                    end
                end
                ReadHeader: if (rd_req_ready) begin
                    beat <= 0;
                    state <= ReadData;
                end
                ReadData: if (rd_rsp_valid) begin
                    if (rd_error !== 1'b0 || $isunknown(rd_data) ||
                        rd_last !== ({1'b0,beat} == rd_length - 5'd1) ||
                        (read_unit && (rd_data[63:9] != 0 ||
                         stored_transfer < -11'sd31 || stored_transfer > 11'sd31))) begin
                        failed <= 1;
                        state <= rd_last === 1'b1 ? Done : DrainRead;
                    end else if (read_unit) begin
                        value_unit <= $signed(rd_data[8:0]);
                        read_unit <= 0;
                        state <= ReadHeader;
                    end else begin
                        head_data[16*beat+:16] <= code_pair;
                        if (rd_last) begin
                            write_kind <= Code;
                            state <= WriteHeader;
                        end else beat <= beat + 1'b1;
                    end
                end
                DrainRead: if (rd_rsp_valid && rd_last === 1'b1) state <= Done;
                Done: if (done_ready) state <= Idle;
                default: begin failed <= 1; state <= Done; end
            endcase
        end
    end
endmodule
