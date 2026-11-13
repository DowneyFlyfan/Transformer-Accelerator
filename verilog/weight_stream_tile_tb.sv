`timescale 1ns/1ps

module weight_stream_tile_tb;
    localparam int TILE_BYTES = 4420;
    localparam int RESPONSE_BEATS = (TILE_BYTES + 63) / 64;

    logic clk = 0;
    logic rst_n = 0;
    logic cfg_valid = 0;
    logic cfg_ready;
    logic rsp_valid = 0;
    logic rsp_last = 0;
    logic rsp_ready;
    logic [511:0] rsp_data;
    logic write_valid;
    logic write_ready;
    logic [4:0] write_word;
    logic [2047:0] write_data;
    logic status_valid;
    logic status_error;
    logic status_ready = 0;
    byte unsigned stream_bytes[RESPONSE_BEATS * 64];
    logic [2047:0] expected[32];
    int cycle;
    int writes;

    always #5 clk = ~clk;
    always @(negedge clk) cycle <= cycle + 1;
    assign write_ready = cycle % 7 != 2;

    weight_stream_tile dut (
        .clk, .rst_n, .cfg_valid, .cfg_ready, .cfg_raw(1'b0), .cfg_short(1'b0),
        .cfg_bytes(14'(TILE_BYTES)), .rsp_valid, .rsp_last, .rsp_error(1'b0),
        .rsp_data, .rsp_ready, .write_valid, .write_ready, .write_word, .write_data,
        .status_valid, .status_error, .status_ready
    );

    task automatic encode_body(
        input int pair_index, body_index, start, width,
        input bit escape,
        output logic [511:0] decoded
    );
        int unsigned code;
        for (int lane = 0; lane < 64; lane++) begin
            if (width == 8) begin
                code = (lane + 29 * body_index) % 256;
                stream_bytes[start + lane] = 8'(code);
                decoded[511 - 8*lane -: 8] = 8'(code);
            end else begin
                code = 0;
                if (escape && lane == 0)
                    code = 15;
                // Leave a valid sequence of codes at byte 4160. The same
                // bank position holds the final header after it wraps.
                if (pair_index == 60 && body_index == 0 && lane inside {[16:23]})
                    code = int'((32'h75938667 >> (4 * (23 - lane))) & 32'hf);
                if (lane % 2 == 0)
                    stream_bytes[start + lane/2][7:4] = 4'(code);
                else
                    stream_bytes[start + lane/2][3:0] = 4'(code);
                decoded[511 - 8*lane -: 8] = escape && lane == 0 ? 8'h41 : 8'(int'(code) - 7);
            end
        end
        if (escape)
            stream_bytes[start + 32] = 8'h41;
    endtask

    task automatic build_tile;
        int position, width, first_bytes, second_bytes;
        logic [511:0] first, second;
        position = 0;
        for (int pair_index = 0; pair_index < 64; pair_index++) begin
            width = pair_index == 0 ? 8 : 4;
            first_bytes = 8 * width + int'(pair_index == 1);
            second_bytes = 8 * width;
            stream_bytes[position] = 8'(width);
            stream_bytes[position + 1] = 8'(first_bytes);
            stream_bytes[position + 2] = 8'(width);
            stream_bytes[position + 3] = 8'(second_bytes);
            position += 4;
            encode_body(pair_index, 0, position, width, pair_index == 1, first);
            position += ((first_bytes + 3) / 4) * 4;
            encode_body(pair_index, 1, position, width, 0, second);
            position += second_bytes;
            expected[pair_index/2][1024*(pair_index%2) +: 1024] = {second, first};
        end
        if (position != TILE_BYTES ||
            {stream_bytes[4160], stream_bytes[4161], stream_bytes[4162], stream_bytes[4163]} !== 32'h75938667 ||
            {stream_bytes[4352], stream_bytes[4353], stream_bytes[4354], stream_bytes[4355]} !== 32'h04200420)
            $fatal(1, "WEIGHT_TILE_FIXTURE");
    endtask

    always @(posedge clk) if (rst_n && write_valid && write_ready) begin
        if (writes >= 32 || write_word !== 5'(writes) || write_data !== expected[writes])
            $fatal(1, "WEIGHT_TILE_WRITE_MISMATCH word=%0d", writes);
        writes++;
    end

    initial begin
        build_tile();
        repeat (2) @(negedge clk);
        rst_n = 1;
        @(negedge clk);
        if (!cfg_ready) $fatal(1, "WEIGHT_TILE_CONFIG");
        cfg_valid = 1;
        @(negedge clk);
        cfg_valid = 0;
        for (int beat = 0; beat < RESPONSE_BEATS; beat++) begin
            // The 68-byte final pair starts on a fresh beat. Give the
            // parser time to drain all earlier bytes before sending it.
            if (beat == 68)
                repeat (12) @(negedge clk);
            for (int byte_index = 0; byte_index < 64; byte_index++)
                rsp_data[511 - 8*byte_index -: 8] = stream_bytes[beat*64 + byte_index];
            rsp_last = beat == RESPONSE_BEATS - 1;
            rsp_valid = 1;
            do @(posedge clk); while (!rsp_ready);
            @(negedge clk);
            rsp_valid = 0;
        end
        while (!status_valid) @(negedge clk);
        if (status_error) $fatal(1, "WEIGHT_TILE_VALID_STREAM_REJECTED");
        if (writes != 32) $fatal(1, "WEIGHT_TILE_WRITE_COUNT writes=%0d", writes);
        status_ready = 1;
        @(negedge clk);
        if (!cfg_ready) $fatal(1, "WEIGHT_TILE_RETIRE");
        $display("WEIGHT_TILE_STALLED_HEADER_PASS bytes=%0d writes=%0d", TILE_BYTES, writes);
        $finish;
    end

    initial begin
        #20us;
        $fatal(1, "WEIGHT_TILE_TIMEOUT");
    end
endmodule
