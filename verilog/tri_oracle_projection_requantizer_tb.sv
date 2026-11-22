`timescale 1ns/1ps
// Literal signed boundaries and independently prepared trained projection sums.
// The source packet remains owned by the producer until its last word retires.
module tri_oracle_projection_requantizer_tb;
    logic clk = 0, rst_n = 0, cancel = 0, in_valid = 0, in_ready;
    logic [31:0] in_tag = 0, out_tag;
    logic [3:0] in_token = 0, out_token;
    logic in_last = 0, out_last, out_packet_last;
    logic [7:0] in_count = 0;
    logic [2559:0] in_channels = 0;
    logic [5119:0] in_data = 0;
    logic signed [8:0] context_exponent = 0;
    logic [255:0] weight_exponents = 0, output_exponents = 0;
    logic out_valid, out_ready = 0, idle, fault;
    logic [3:0] out_count;
    logic [127:0] out_channels;
    logic [63:0] out_data;
    logic [5119:0] raw_packets [13];
    logic [2559:0] channel_packets [13];
    logic [63:0] expected_words [256];
    logic [1279:0] expected_codes;
    logic [255:0] trained_weight_units, trained_output_units;
    string raw_file, channel_file, expected_file;
    int packets = 0, values = 0, stalls = 0, rejected = 0;

`ifdef QUANTIZER_ABSENT
    // Test-only absence witness: a missing converter produces no output.
    always_comb begin
        in_ready = 0; out_valid = 0; out_tag = 0; out_token = 0;
        out_last = 0; out_packet_last = 0; out_count = 0;
        out_channels = 0; out_data = 0; idle = !in_valid; fault = 0;
    end
`else
    tri_oracle_projection_requantizer dut (.*);
`endif
    always #5 clk = ~clk;

    task automatic reset_converter;
        @(negedge clk);
        rst_n = 0; in_valid = 0; cancel = 0; out_ready = 0;
        repeat (2) @(negedge clk);
        rst_n = 1;
        #1;
        if (!idle || out_valid || fault) $fatal(1, "REQUANT_RESET_FAILED");
    endtask

    // Catches early source retirement, lane/channel reordering, missing stalls,
    // incorrect partial masks, and arithmetic errors, using independent codes.
    task automatic consume_packet(input logic [1279:0] codes);
        int offset, count_here, tick;
        logic [2559:0] saved_channels;
        logic [31:0] saved_tag;
        logic [3:0] saved_token;
        logic saved_last;
        saved_channels = in_channels; saved_tag = in_tag;
        saved_token = in_token; saved_last = in_last;
        offset = 0; tick = 0;
        in_valid = 1;
        while (offset < int'(in_count)) begin
            out_ready = tick % 4 == 3;
            #1;
            count_here = int'(in_count) - offset;
            if (count_here > 8) count_here = 8;
            if (!out_valid || fault || idle)
                $fatal(1, "REQUANT_OUTPUT_MISSING packet=%0d offset=%0d", packets, offset);
            if (out_tag !== saved_tag || out_token !== saved_token || out_last !== saved_last ||
                out_count !== 4'(count_here) || out_packet_last !== (offset + count_here == int'(in_count)))
                $fatal(1, "REQUANT_METADATA_WRONG packet=%0d offset=%0d", packets, offset);
            if (in_ready !== (out_ready && out_packet_last))
                $fatal(1, "REQUANT_SOURCE_RETIRED_EARLY offset=%0d", offset);
            for (int lane = 0; lane < 8; lane++) begin
                if (lane < count_here) begin
                    if (out_channels[lane*16+:16] !== saved_channels[(offset+lane)*16+:16] ||
                        out_data[lane*8+:8] !== codes[(offset+lane)*8+:8])
                        $fatal(1, "REQUANT_CODE_WRONG packet=%0d row=%0d got=%0d expected=%0d",
                            packets, offset+lane, $signed(out_data[lane*8+:8]), $signed(codes[(offset+lane)*8+:8]));
                end else if (out_channels[lane*16+:16] !== 0 || out_data[lane*8+:8] !== 0)
                    $fatal(1, "REQUANT_INACTIVE_LANE_NOT_ZERO");
            end
            if (out_ready) begin offset += count_here; values += count_here; end
            else stalls++;
            @(posedge clk);
            @(negedge clk);
            tick++;
        end
        packets++;
        in_valid = 0; in_data = 'x; in_channels = 'x;
        in_count = 'x; in_tag = 'x; in_token = 'x; in_last = 'x;
        context_exponent = 'x; weight_exponents = 'x; output_exponents = 'x;
        #1;
        if (out_valid || !idle || fault) $fatal(1, "REQUANT_NOT_RETIRED");
        @(negedge clk);
    endtask

    task automatic scalar_case(input logic signed [31:0] raw,
                               input int shift, input logic signed [7:0] expected_code);
        in_count = 1; in_channels = 'x; in_channels[15:0] = 16'd63;
        in_data = 'x; in_data[31:0] = raw;
        in_tag = 32'hba001234; in_token = 4'd9; in_last = 0;
        context_exponent = 0; weight_exponents = 0; output_exponents = 'x;
        output_exponents[7:0] = 8'(shift);
        consume_packet({1272'b0, expected_code});
    endtask

    task automatic reject_packet;
        in_valid = 1; out_ready = 1;
        #1;
        if (out_valid || !in_ready) $fatal(1, "REQUANT_BAD_PACKET_EXPOSED");
        @(posedge clk); @(negedge clk); in_valid = 0;
        #1;
        if (!fault || out_valid) $fatal(1, "REQUANT_FAULT_NOT_STICKY");
        // A later valid descriptor is drained, never returned as valid output.
        in_count = 1; in_channels = 0; in_data = 0;
        context_exponent = 0; weight_exponents = 0; output_exponents = {32{8'd1}};
        in_valid = 1;
        #1;
        if (out_valid || !in_ready || !fault) $fatal(1, "REQUANT_FAULT_RECOVERY_WITHOUT_RESET");
        @(posedge clk); @(negedge clk);
        rejected++;
        reset_converter();
    endtask

    initial begin
        reset_converter();
        scalar_case(32'sd0, 1, 8'sd0);
        scalar_case(32'sd1, 1, 8'sd1);
        scalar_case(-32'sd1, 1, -8'sd1);
        scalar_case(32'sd255, 1, 8'sd127);
        scalar_case(-32'sd255, 1, -8'sd128);
        scalar_case(32'sd256, 1, 8'sd127);
        scalar_case(-32'sd256, 1, -8'sd128);
        scalar_case(32'sh7fffffff, 1, 8'sd127);
        scalar_case(32'sh80000000, 1, -8'sd128);
        scalar_case(32'sh7fffffff, 31, 8'sd1);
        scalar_case(32'sh80000000, 31, -8'sd1);
        scalar_case(32'sh7fffffff, 32, 8'sd0);
        scalar_case(32'sh80000000, 32, -8'sd1);
        scalar_case(32'sh80000000, 33, 8'sd0);
        scalar_case(32'sh7fffffff, 48, 8'sd0);
        scalar_case(32'sh80000000, 48, 8'sd0);
        scalar_case(32'sd511, 10, 8'sd0);
        scalar_case(32'sd512, 10, 8'sd1);
        scalar_case(32'sd513, 10, 8'sd1);
        scalar_case(32'sd1536, 10, 8'sd2);
        scalar_case(-32'sd512, 10, -8'sd1);
        scalar_case(-32'sd1536, 10, -8'sd2);

        // Non-contiguous channel groups have different units in the same word.
        in_count = 17; in_channels = 'x; in_data = 'x; expected_codes = 0;
        in_tag = 32'h174ab98e; in_token = 3; in_last = 1;
        context_exponent = -9'sd7; weight_exponents = {32{8'hf6}};
        output_exponents = 'x;
        output_exponents[7:0] = 8'hf9; output_exponents[15:8] = 8'hfa;
        for (int row = 0; row < 17; row++) begin
            in_channels[row*16+:16] = row%2 == 0 ? 16'd63 : 16'd64;
            in_data[row*32+:32] = row%2 == 0 ? 32'd512 : -32'sd1024;
            expected_codes[row*8+:8] = row%2 == 0 ? 8'd1 : -8'sd1;
        end
        consume_packet(expected_codes);
        in_count = 7; in_channels = 'x; in_data = 'x; expected_codes = 0;
        in_tag = 32'hffaab123; in_token = 15; in_last = 0;
        context_exponent = 0; weight_exponents = 0; output_exponents = {32{8'd1}};
        for (int row = 0; row < 7; row++) begin
            in_channels[row*16+:16] = 16'(2047-row);
            in_data[row*32+:32] = 32'(2*row);
            expected_codes[row*8+:8] = 8'(row);
        end
        consume_packet(expected_codes);

        for (int kind = 0; kind < 8; kind++) begin
            in_count = 9; in_channels = 0; in_data = 0;
            context_exponent = 0; weight_exponents = 0; output_exponents = {32{8'd1}};
            case (kind)
                0: in_count = 0;
                1: in_count = 161;
                2: in_channels[8*16+:16] = 16'd2048;
                3: in_channels[8*16+:16] = 16'hffff;
                4: output_exponents[7:0] = 8'd0;
                5: output_exponents[7:0] = 8'd49;
                6: begin context_exponent = 9'sd255; weight_exponents = {32{8'd127}};
                         output_exponents = {32{8'h80}}; end
                7: begin context_exponent = -9'sd256; weight_exponents = {32{8'h80}};
                         output_exponents = {32{8'd127}}; end
            endcase
            reject_packet();
        end

        // Cancellation and reset after one word must restart at row zero.
        for (int use_reset = 0; use_reset < 2; use_reset++) begin
            in_count = 17; in_channels = 0; in_data = 0;
            context_exponent = 0; weight_exponents = 0; output_exponents = {32{8'd1}};
            in_tag = 5; in_token = 6; in_last = 0; in_valid = 1; out_ready = 1;
            #1;
            if (!out_valid || in_ready || out_packet_last) $fatal(1, "REQUANT_CANCEL_SETUP");
            @(posedge clk); @(negedge clk); out_ready = 0;
            #1;
            if (!out_valid || in_ready) $fatal(1, "REQUANT_CANCEL_STALL_SETUP");
            if (use_reset) begin rst_n = 0; #1; end
            else begin cancel = 1; #1; end
            if (out_valid || (!use_reset && !in_ready)) $fatal(1, "REQUANT_CANCEL_DID_NOT_DISCARD");
            @(posedge clk); @(negedge clk); in_valid = 0; cancel = 0; rst_n = 1;
            #1;
            if (!idle || fault) $fatal(1, "REQUANT_CANCEL_NOT_IDLE");
            scalar_case(32'sd512, 10, 8'sd1);
        end

        if (!$value$plusargs("RAW_PACKETS=%s", raw_file) ||
            !$value$plusargs("CHANNEL_PACKETS=%s", channel_file) ||
            !$value$plusargs("EXPECTED_WORDS=%s", expected_file) ||
            !$value$plusargs("WEIGHT_EXPONENTS=%h", trained_weight_units) ||
            !$value$plusargs("OUTPUT_EXPONENTS=%h", trained_output_units))
            $fatal(1, "REQUANT_TRAINED_INPUTS_MISSING");
        $readmemh(raw_file, raw_packets);
        $readmemh(channel_file, channel_packets);
        $readmemh(expected_file, expected_words);
        for (int group_index = 0; group_index < 13; group_index++) begin
            in_count = group_index == 12 ? 8'd128 : 8'd160;
            in_channels = channel_packets[group_index]; in_data = raw_packets[group_index];
            in_tag = 32'h80000000+32'(group_index); in_token = 0; in_last = 1;
            context_exponent = -9'sd7;
            weight_exponents = trained_weight_units; output_exponents = trained_output_units;
            expected_codes = 0;
            for (int row = 0; row < int'(in_count); row++)
                expected_codes[row*8+:8] = expected_words[(group_index*160+row)/8][((group_index*160+row)%8)*8+:8];
            consume_packet(expected_codes);
        end
        if (packets != 39 || values != 2096 || rejected != 8 || stalls == 0)
            $fatal(1, "REQUANT_COVERAGE_WRONG packets=%0d values=%0d rejected=%0d", packets, values, rejected);
        $display("PROJECTION_REQUANTIZER_PASS packets=%0d values=%0d trained_codes=2048 rejected=%0d stalls=%0d", packets, values, rejected, stalls);
        $finish;
    end
    initial begin #100000; $fatal(1, "REQUANT_TIMEOUT"); end
endmodule
