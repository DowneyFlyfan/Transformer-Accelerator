`timescale 1ns/1ps
module tri_oracle_decoder_writeback_bridge_tb;
    logic clk = 0, rst_n = 0;
    always #5 clk = ~clk;
    logic in_valid = 0, in_ready, in_last;
    logic [31:0] in_tag;
    logic [3:0] in_token;
    logic [15:0] in_start;
    logic [7:0] in_count;
    logic [5119:0] in_data;
    logic [4:0] down_shift = 5'd11;
    logic bypass_valid = 0, bypass_ready;
    logic [231:0] bypass_data;
    logic out_valid, out_ready = 0, out_last;
    logic [31:0] out_tag;
    logic [3:0] out_token;
    logic [15:0] out_start;
    logic [3:0] out_count;
    logic [127:0] out_data;
    int accepted = 0, packets = 0, stalls = 0;
    logic held = 0;
    logic [184:0] held_packet;
    logic [620:0] trained [512];
    string fixture;

    tri_oracle_decoder_writeback_bridge dut (.*);

    always @(posedge clk) if (rst_n) begin
        if (held && (!out_valid || {out_tag, out_token, out_start, out_count, out_last, out_data} !== held_packet))
            $fatal(1, "WRITEBACK_BRIDGE_CHANGED_DURING_STALL");
        held = out_valid && !out_ready;
        held_packet = {out_tag, out_token, out_start, out_count, out_last, out_data};
        if (held) stalls++;
        if (out_valid && out_ready) accepted++;
        if (in_valid && in_ready) packets++;
    end

    task automatic tile(input int token, start, count, input bit last);
        int lanes, row;
        logic [127:0] expected;
        @(negedge clk);
        in_tag = 32'habcd0010;
        in_token = 4'(token);
        in_start = 16'(start);
        in_count = 8'(count);
        in_last = last;
        in_data = '0;
        for (int k = 0; k < count; k++) begin
            row = token * 256 + (start + k) / 8;
            in_data[32*k +: 32] = trained[row][232+32*(k%8) +: 32];
        end
        in_valid = 1;
        for (int offset = 0; offset < count; offset += 8) begin
            row = token * 256 + (start + offset) / 8;
            lanes = count-offset > 8 ? 8 : count-offset;
            bypass_valid = 0;
            out_ready = 1;
            @(posedge clk);
            if (out_valid || in_ready || bypass_ready !== 1'b1)
                $fatal(1, "WRITEBACK_BRIDGE_MISSING_BYPASS");
            @(negedge clk);
            bypass_valid = 1;
            bypass_data = trained[row][231:0];
            down_shift = trained[row][492:488];
            expected = trained[row][620:493];
            for (int j = lanes; j < 8; j++) expected[16*j +: 16] = '0;
            out_ready = 0;
            repeat (2) begin
                @(posedge clk);
                if (!out_valid || in_ready || bypass_ready)
                    $fatal(1, "WRITEBACK_BRIDGE_LOST_STALL");
            end
            @(negedge clk);
            out_ready = 1;
            @(posedge clk);
            if (!out_valid || !bypass_ready || in_ready !== (offset + lanes == count) ||
                {out_tag, out_token, out_start, out_count, out_last, out_data} !==
                {32'habcd0010, 4'(token), 16'(start+offset), 4'(lanes),
                 1'(last && offset+lanes==count), expected})
                $fatal(1, "WRITEBACK_BRIDGE_WRONG_STRIP start=%0d offset=%0d count=%0d data=%h expected=%h",
                       start, offset, count, out_data, expected);
            @(negedge clk);
        end
        out_ready = 0;
        in_valid = 0;
        bypass_valid = 0;
    endtask

    initial begin
        if (!$value$plusargs("TRAINED=%s", fixture)) $fatal(1, "Missing trained vectors");
        $readmemh(fixture, trained);
        repeat (3) @(negedge clk);
        rst_n = 1;
        for (int k = 0; k < 2048; k += 160)
            for (int token = 0; token < 2; token++)
                tile(token, k, k < 1920 ? 160 : 128, token == 1 && k == 1920);
        tile(0, 0, 1, 1);
        tile(1, 0, 157, 1);
        if (accepted != 533 || packets != 28 || stalls != 1066)
            $fatal(1, "WRITEBACK_BRIDGE_CENSUS accepted=%0d packets=%0d stalls=%0d", accepted, packets, stalls);
        $display("DECODER_WRITEBACK_BRIDGE_PASS strips=%0d packets=%0d stalls=%0d", accepted, packets, stalls);
        $finish;
    end
    initial begin
        #60000;
        $fatal(1, "WRITEBACK_BRIDGE_TIMEOUT");
    end
endmodule
