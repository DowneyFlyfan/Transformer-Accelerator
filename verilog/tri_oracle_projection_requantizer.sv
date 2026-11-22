// Serialize a held tensor390 raw packet into eight signed eight-bit codes.
// Unit: code * 2**output_exponent. Shift = output - context - weight.
// The producer owns and holds the packet AND its unit metadata until in_ready;
// no tensor payload is copied here. Only active channel groups are validated.
// Invalid packets are drained without output and latch fault until reset.
// The outer frame owner must cancel/drain the command when fault is asserted.
module tri_oracle_projection_requantizer (
    input logic clk, rst_n, cancel, in_valid,
    output logic in_ready,
    input logic [31:0] in_tag,
    input logic [3:0] in_token,
    input logic in_last,
    input logic [7:0] in_count,
    input logic [2559:0] in_channels,
    input logic [5119:0] in_data,
    input logic signed [8:0] context_exponent,
    input logic [255:0] weight_exponents, output_exponents,
    output logic out_valid,
    input logic out_ready,
    output logic [31:0] out_tag,
    output logic [3:0] out_token,
    output logic out_last, out_packet_last,
    output logic [3:0] out_count,
    output logic [127:0] out_channels,
    output logic [63:0] out_data,
    output logic idle, fault
);
    logic [7:0] offset;
    logic [31:0] used_groups;
    logic signed [10:0] shifts [32];
    logic bad_packet;

    function automatic logic [7:0] requantize (
        input logic signed [31:0] value, input logic [5:0] right_shift
    );
        logic signed [33:0] extended, rounded;
        extended = {{2{value[31]}}, value};
        // For a signed32 input, every shift above32 rounds to zero.
        // Widen before abs/half-add: abs(-2**31) + 2**31 needs33 magnitude bits.
        if (right_shift > 6'd32) rounded = 0;
        else if (extended < 0)
            rounded = -((-extended + (34'sd1 << (right_shift - 6'd1))) >>> right_shift);
        else rounded = (extended + (34'sd1 << (right_shift - 6'd1))) >>> right_shift;
        if (rounded > 34'sd127) return 8'h7f;
        if (rounded < -34'sd128) return 8'h80;
        return rounded[7:0];
    endfunction

    always_comb begin
        used_groups = 0;
        bad_packet = in_count == 0 || in_count > 8'd160;
        for (int row = 0; row < 160; row++) begin
            if (row < int'(in_count)) begin
                if (in_channels[row*16+:16] >= 16'd2048) bad_packet = 1;
                else used_groups[in_channels[row*16+6+:5]] = 1;
            end
        end
        for (int group_index = 0; group_index < 32; group_index++) begin
            shifts[group_index] = $signed({{3{output_exponents[group_index*8+7]}}, output_exponents[group_index*8+:8]}) -
                $signed({{2{context_exponent[8]}}, context_exponent}) -
                $signed({{3{weight_exponents[group_index*8+7]}}, weight_exponents[group_index*8+:8]});
            if (used_groups[group_index] && (shifts[group_index] < 11'sd1 || shifts[group_index] > 11'sd48))
                bad_packet = 1;
        end

        out_valid = rst_n && !cancel && !fault && in_valid && !bad_packet;
        out_tag = 0; out_token = 0; out_last = 0; out_packet_last = 0;
        out_count = 0; out_channels = 0; out_data = 0;
        if (out_valid) begin
            out_tag = in_tag; out_token = in_token; out_last = in_last;
            if (in_count - offset > 8'd8) out_count = 4'd8;
            else out_count = 4'(in_count - offset);
            out_packet_last = {1'b0, offset} + {5'b0, out_count} == {1'b0, in_count};
            for (int lane = 0; lane < 8; lane++) begin
                if (lane < int'(out_count)) begin
                    out_channels[lane*16+:16] = in_channels[(int'(offset)+lane)*16+:16];
                    out_data[lane*8+:8] = requantize($signed(in_data[(int'(offset)+lane)*32+:32]),
                        shifts[in_channels[(int'(offset)+lane)*16+6+:5]][5:0]);
                end
            end
        end
        in_ready = rst_n && (cancel || fault || (in_valid && bad_packet) ||
            (out_valid && out_ready && out_packet_last));
        idle = offset == 0 && (!in_valid || cancel || fault);
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin offset <= 0; fault <= 0; end
        else begin
            if (!cancel && in_valid && bad_packet) fault <= 1;
            if (cancel || fault || (in_valid && bad_packet)) offset <= 0;
            else if (out_valid && out_ready) begin
                if (out_packet_last) offset <= 0;
                else offset <= offset + 8'd8;
            end
        end
    end
endmodule
