`timescale 1ns/1ps
// Project normalized signed-eight-bit activations into query, key and value heads.
// Bind the tensor owner in ordinary mode with 256 feature words and a 2048-byte
// activation stride. Weight rows are Q[0:2047], K[2048:2303], V[2304:2559].
// The caller provides angles at each original position with 14 fractional bits.
// Shifts include the angle fraction for Q/K and a nonnegative per-token bias.
// Commit vectors only after done success.
module tri_oracle_qkv429 (
    input logic clk, rst_n,
    input logic cfg_valid,
    output logic cfg_ready,
    input logic [4:0] cfg_tokens,
    input logic [5:0] cfg_start_head, cfg_heads,
    input logic [31:0] cfg_tag,
    input logic [63:0] cfg_activation_base, cfg_weight_base,
    input logic [239:0] cfg_shifts,
    input logic [95:0] cfg_shift_biases,

    input logic angle_valid, angle_last,
    output logic angle_ready,
    input logic [511:0] angle_cos, angle_sin,

    output logic out_valid, out_last,
    input logic out_ready,
    output logic [31:0] out_tag,
    output logic [5:0] out_head,
    output logic [3:0] out_token,
    output logic [511:0] out_data,
    output logic done_valid, done_error,
    input logic done_ready,
    output logic [31:0] done_tag,

    output logic tensor_cfg_valid,
    input logic tensor_cfg_ready,
    output logic [31:0] tensor_cfg_tag,
    output logic [4:0] tensor_cfg_tokens,
    output logic [7:0] tensor_cfg_count,
    output logic [2559:0] tensor_cfg_channels, tensor_cfg_keep,
    output logic [63:0] tensor_cfg_activation_base, tensor_cfg_weight_base,
    input logic tensor_out_valid, tensor_out_last,
    output logic tensor_out_ready,
    input logic [31:0] tensor_out_tag,
    input logic [3:0] tensor_out_token,
    input logic [7:0] tensor_out_count,
    input logic [2559:0] tensor_out_channels,
    input logic [4095:0] tensor_out_data,
    input logic tensor_done_valid, tensor_done_error,
    output logic tensor_done_ready,
    input logic [31:0] tensor_done_tag
);
    typedef enum logic [3:0] {Idle, LoadAngles, DrainAngles, Submit, WaitPacket, FormatPair,
                              Emit, WaitDone, DrainTensor, Done} state_t;
    state_t state;
    logic [5:0] tile_base, head_limit;
    logic head_offset, two_heads, last_token, last_in_tile, last_tile, rotate, malformed_packet;
    logic [3:0] token;
    logic [4:0] feature;
    logic [239:0] shifts;
    logic [95:0] shift_biases;
    logic [511:0] cosines[16], sines[16];
    logic [4095:0] packet;
    logic activation_wrap, weight_wrap;
    logic signed [31:0] raw_lower, raw_upper;
    logic signed [15:0] cosine, sine;
    logic signed [47:0] lower_cos, upper_cos, lower_sin, upper_sin;
    logic signed [48:0] lower_rotated, upper_rotated;
    logic [6:0] shift;

    function automatic logic [7:0] encode(input logic signed [48:0] value, input logic [6:0] right_shift);
        logic [48:0] magnitude;
        logic [63:0] rounded, half;
        if (right_shift>=64) return 0;
        magnitude = value[48] ? (~$unsigned(value)+49'd1) : $unsigned(value);
        half = right_shift==0 ? 64'd0 : 64'd1<<(right_shift-1'b1);
        rounded = (64'(magnitude)+half)>>right_shift;
        if (value[48]) return rounded>=128 ? 8'h80 : (~8'(rounded)+8'd1);
        return rounded>=127 ? 8'h7f : 8'(rounded);
    endfunction

    assign activation_wrap = cfg_activation_base > 64'hffffffffffffffff-((64'(cfg_tokens)<<11)-64'd1);
    assign weight_wrap = cfg_weight_base > 64'hffffffffffffffff-64'd5242879;
    assign cfg_ready = state==Idle;
    assign angle_ready = state==LoadAngles || state==DrainAngles;
    assign out_valid = state==Emit;
    assign done_valid = state==Done;
    assign out_tag = tensor_cfg_tag;
    assign done_tag = tensor_cfg_tag;
    assign out_token = token;
    assign out_head = tile_base+6'(head_offset);
    assign out_last = out_valid && last_token && last_in_tile && last_tile;
    assign two_heads = tile_base+6'd1<head_limit;
    assign last_in_tile = !two_heads || head_offset;
    assign last_tile = tile_base+(two_heads ? 6'd2 : 6'd1)==head_limit;
    assign last_token = 5'(token)+5'd1==tensor_cfg_tokens;
    assign tensor_cfg_valid = state==Submit;
    assign tensor_cfg_count = two_heads ? 8'd128 : 8'd64;
    assign tensor_cfg_keep = '1;
    assign tensor_out_ready = state==WaitPacket || state==WaitDone || state==DrainTensor;
    assign tensor_done_ready = tensor_out_ready;
    assign malformed_packet = tensor_out_tag!=tensor_cfg_tag || tensor_out_token!=token ||
                              tensor_out_last!=last_token || tensor_out_count!=tensor_cfg_count ||
                              tensor_out_channels!=tensor_cfg_channels;
    for (genvar lane=0;lane<160;lane++) begin : channels
        assign tensor_cfg_channels[lane*16+:16] = lane<64 || (lane<128 && two_heads) ?
            16'({tile_base,6'b0})+16'(lane) : 16'd0;
    end

    assign rotate = out_head<36;
    assign shift = 7'(shifts[int'(out_head)*6+:6])+7'(shift_biases[int'(token)*6+:6]);
    assign raw_lower = $signed(packet[int'({head_offset,1'b0,feature})*32+:32]);
    assign raw_upper = $signed(packet[int'({head_offset,1'b1,feature})*32+:32]);
    assign cosine = $signed(cosines[token][int'(feature)*16+:16]);
    assign sine = $signed(sines[token][int'(feature)*16+:16]);
    assign lower_cos = raw_lower*cosine;
    assign upper_cos = raw_upper*cosine;
    assign lower_sin = raw_lower*sine;
    assign upper_sin = raw_upper*sine;
    assign lower_rotated = 49'(lower_cos)-49'(upper_sin);
    assign upper_rotated = 49'(upper_cos)+49'(lower_sin);

    always_ff @(posedge clk) begin
        if (state==LoadAngles && angle_valid) begin
            cosines[token] <= angle_cos;
            sines[token] <= angle_sin;
        end
        if (state==WaitPacket && tensor_out_valid) packet <= tensor_out_data;
        if (state==FormatPair) begin
            out_data[int'({1'b0,feature})*8+:8] <= encode(rotate ? lower_rotated : 49'(raw_lower),shift);
            out_data[int'({1'b1,feature})*8+:8] <= encode(rotate ? upper_rotated : 49'(raw_upper),shift);
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= Idle;
            tensor_cfg_tag <= 0;
            tensor_cfg_tokens <= 0;
            tensor_cfg_activation_base <= 0;
            tensor_cfg_weight_base <= 0;
            shifts <= 0;
            shift_biases <= 0;
            tile_base <= 0;
            head_limit <= 0;
            head_offset <= 0;
            token <= 0;
            feature <= 0;
            done_error <= 0;
        end else case (state)
            Idle: if (cfg_valid) begin
                tensor_cfg_tag <= cfg_tag;
                tensor_cfg_tokens <= cfg_tokens;
                tensor_cfg_activation_base <= cfg_activation_base;
                tensor_cfg_weight_base <= cfg_weight_base;
                shifts <= cfg_shifts;
                shift_biases <= cfg_shift_biases;
                tile_base <= cfg_start_head;
                head_limit <= cfg_start_head+cfg_heads;
                head_offset <= 0;
                token <= 0;
                feature <= 0;
                done_error <= 0;
                if (cfg_tokens==0 || cfg_tokens>16 || cfg_heads==0 || 7'(cfg_start_head)+7'(cfg_heads)>40 ||
                    cfg_activation_base[2:0]!=0 || cfg_weight_base[2:0]!=0 || activation_wrap || weight_wrap) begin
                    done_error <= 1;
                    state <= Done;
                end else if (cfg_start_head<36) state <= LoadAngles;
                else state <= Submit;
            end
            LoadAngles: if (angle_valid) begin
                if (angle_last!=last_token) begin
                    done_error <= 1;
                    if (angle_last) state <= Done;
                    else state <= DrainAngles;
                end else if (last_token) begin
                    token <= 0;
                    state <= Submit;
                end else token <= token+1'b1;
            end
            DrainAngles: if (angle_valid && angle_last) state <= Done;
            Submit: if (tensor_cfg_ready) state <= WaitPacket;
            WaitPacket: begin
                if (tensor_done_valid) begin
                    done_error <= 1;
                    state <= Done;
                end else if (tensor_out_valid) begin
                    if (malformed_packet) begin
                        done_error <= 1;
                        state <= DrainTensor;
                    end else state <= FormatPair;
                end
            end
            FormatPair: begin
                feature <= feature+1'b1;
                if (feature==31) state <= Emit;
            end
            Emit: if (out_ready) begin
                if (!last_in_tile) begin
                    head_offset <= 1;
                    state <= FormatPair;
                end else begin
                    head_offset <= 0;
                    token <= token+1'b1;
                    if (last_token) state <= WaitDone;
                    else state <= WaitPacket;
                end
            end
            WaitDone: begin
                if (tensor_out_valid) done_error <= 1;
                if (tensor_done_valid) begin
                    if (done_error || tensor_out_valid || tensor_done_error || tensor_done_tag!=tensor_cfg_tag) begin
                        done_error <= 1;
                        state <= Done;
                    end else if (last_tile) state <= Done;
                    else begin
                        tile_base <= tile_base+6'd2;
                        token <= 0;
                        state <= Submit;
                    end
                end
            end
            DrainTensor: if (tensor_done_valid) state <= Done;
            Done: if (done_ready) state <= Idle;
            default: state <= Idle;
        endcase
    end
endmodule
