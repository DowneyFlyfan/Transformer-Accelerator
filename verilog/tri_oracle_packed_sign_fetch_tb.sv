`timescale 1ns/1ps

module tri_oracle_packed_sign_fetch_tb;
    localparam int GROUPS = 176, STRIPS = 256, PAIRS = 4;
    localparam logic [63:0] BASE = 64'h0000_000b_ffff_ff00;
    logic clk = 0, rst_n = 0;
    always #5 clk = ~clk;

    logic in_valid = 0, in_ready, in_last, in_error;
    logic [31:0] in_tag;
    logic [10:0] in_group;
    logic [9:0] in_strips, in_index;
    logic [127:0] in_norm_q8;
    logic [63:0] in_sign_base;
    logic out_valid, out_ready = 0, out_last, out_error;
    logic [31:0] out_tag;
    logic [10:0] out_group;
    logic [9:0] out_index;
    logic [127:0] out_norm_q8;
    logic [255:0] out_gate_signs, out_up_signs;
    logic req_valid, req_ready = 0;
    logic [63:0] req_address;
    logic [5:0] req_length;
    logic rsp_valid = 0, rsp_ready, rsp_last, rsp_error;
    logic [511:0] rsp_data;
    logic [511:0] packed_lines [GROUPS*STRIPS];
    logic [63:0] gate_words [GROUPS*STRIPS*PAIRS], up_words [GROUPS*STRIPS*PAIRS];
    int requests = 0, trained_lines = 0;

    tri_oracle_packed_sign_fetch dut (.*);

    task automatic submit(input logic [63:0] base, input int group, strips, index,
                          input logic [127:0] norms, input bit last = 0, error = 0);
        in_sign_base = base;
        in_tag = 32'habc00000 + 32'(group);
        in_group = 11'(group);
        in_strips = 10'(strips);
        in_index = 10'(index);
        in_norm_q8 = norms;
        in_last = last;
        in_error = error;
        in_valid = 1;
        do @(posedge clk); while (!in_ready);
        @(negedge clk);
        in_valid = 0;
        in_sign_base = 'x;
        in_norm_q8 = 'x;
    endtask

    task automatic accept_line(input logic [63:0] address, input int stalls = 0);
        wait (req_valid || out_valid);
        repeat (stalls) begin
            if (!req_valid || req_address !== address || req_length !== 6'd1 || rsp_ready)
                $fatal(1, "PACKED_SIGN_REQUEST_STALL");
            @(negedge clk);
        end
        if (!req_valid || req_address !== address || req_length !== 6'd1)
            $fatal(1, "PACKED_SIGN_REQUEST got=%h expected=%h", req_address, address);
        req_ready = 1;
        @(negedge clk);
        req_ready = 0;
        requests++;
    endtask

    task automatic respond(input logic [511:0] data, input bit last = 1, error = 0);
        if (!rsp_ready || req_valid) $fatal(1, "PACKED_SIGN_RESPONSE_OWNERSHIP");
        rsp_data = data;
        rsp_last = last;
        rsp_error = error;
        rsp_valid = 1;
        @(negedge clk);
        rsp_valid = 0;
    endtask

    task automatic check_result(input int group, index, input logic [127:0] norms,
                                input logic [255:0] gate, up, input bit last = 0, error = 0,
                                input int stalls = 0);
        wait (out_valid || req_valid);
        if (req_valid) $fatal(1, "PACKED_SIGN_REDUNDANT_REQUEST");
        for (int step = 0; step <= stalls; step++) begin
            if (!out_valid || in_ready || out_error !== error || out_last !== last ||
                out_tag !== 32'habc00000 + 32'(group) || out_group !== 11'(group) || out_index !== 10'(index) ||
                out_norm_q8 !== norms || out_gate_signs !== gate || out_up_signs !== up)
                $fatal(1, "PACKED_SIGN_RESULT group=%0d index=%0d", group, index);
            if (step != stalls) @(negedge clk);
        end
        out_ready = 1;
        @(negedge clk);
        out_ready = 0;
    endtask

    initial begin : exercise
        string fixture, image;
        logic [127:0] norms;
        logic [255:0] expected_gate, expected_up;
        int before_trained;
        repeat (2) @(negedge clk);
        rst_n = 1;

        // Both branches from one response, signed threshold and backpressure.
        norms = {16'sd0, 16'h8000, -16'sd16, 16'sd10000, -16'sd769, 16'sd769, -16'sd768, 16'sd768};
        for (int channel = 0; channel < 32; channel++) begin
            expected_gate[channel*8+:8] = 8'b01011100;
            expected_up[channel*8+:8] = 8'b01011100;
        end
        submit(BASE, 2, 3, 1, norms, 1);
        accept_line(BASE + 7 * 64, 2);
        respond('1);
        check_result(2, 1, norms, expected_gate, expected_up, 1, 0, 3);

        submit(BASE, 0, 1, 0, {4{16'sd768, -16'sd768}});
        check_result(0, 0, {4{16'sd768, -16'sd768}}, '0, '0);
        submit(BASE + 8, 0, 1, 0, norms);
        check_result(0, 0, '0, '0, '0, 0, 1);
        submit(64'hffff_ffff_ffff_ffc0, 0, 2, 1, norms);
        check_result(0, 1, '0, '0, '0, 0, 1);
        submit(BASE, 1, 0, 0, norms);
        check_result(1, 0, '0, '0, '0, 0, 1);
        submit(BASE, 1, 513, 0, norms);
        check_result(1, 0, '0, '0, '0, 0, 1);
        submit(BASE, 1, 1, 1, norms);
        check_result(1, 1, '0, '0, '0, 0, 1);
        submit(BASE, 0, 1, 0, norms, 0, 1);
        check_result(0, 0, '0, '0, '0, 0, 1);

        submit(BASE, 0, 1, 0, norms);
        accept_line(BASE);
        respond('1, 1, 1);
        check_result(0, 0, '0, '0, '0, 0, 1);
        submit(BASE, 0, 1, 0, norms);
        accept_line(BASE);
        respond('1, 0);
        if (out_valid || in_ready) $fatal(1, "PACKED_SIGN_EARLY_DRAIN_COMPLETION");
        respond('1, 1);
        check_result(0, 0, '0, '0, '0, 0, 1);

        if (!$value$plusargs("FIXTURE=%s", fixture) || !$value$plusargs("PACKED=%s", image))
            $fatal(1, "PACKED_SIGN_FIXTURES");
        $readmemh({fixture, "/gate_sign.hex"}, gate_words);
        $readmemh({fixture, "/up_sign.hex"}, up_words);
        $readmemh(image, packed_lines);
        before_trained = requests;
        norms = {8{16'sd769}};
        for (int group = 0; group < GROUPS; group++) begin
            for (int strip = 0; strip < STRIPS; strip++) begin
                int line;
                line = group * STRIPS + strip;
                for (int lane = 0; lane < 8; lane++) begin
                    for (int channel = 0; channel < 32; channel++) begin
                        expected_gate[channel*8+lane] = gate_words[line*PAIRS+lane/2][(lane%2)*32+channel];
                        expected_up[channel*8+lane] = up_words[line*PAIRS+lane/2][(lane%2)*32+channel];
                    end
                end
                submit(BASE, group, STRIPS, strip, norms, strip == STRIPS - 1);
                accept_line(BASE + 64'(line)*64);
                respond(packed_lines[line]);
                check_result(group, strip, norms, expected_gate, expected_up, strip == STRIPS - 1);
                trained_lines++;
            end
        end
        if (trained_lines != GROUPS*STRIPS || requests - before_trained != trained_lines)
            $fatal(1, "PACKED_SIGN_TRAINED_INVENTORY");
        $display("PACKED_SIGN_FETCH_PASS trained_lines=%0d sign_words=%0d request_stall=2 output_stall=3", trained_lines, trained_lines*8);
        $finish;
    end

    initial begin
        #5000000;
        $fatal(1, "PACKED_SIGN_FETCH_TIMEOUT");
    end
endmodule
