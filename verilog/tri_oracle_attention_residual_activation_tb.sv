`timescale 1ns/1ps
module tri_oracle_attention_residual_activation_tb;
    logic clk = 0, rst_n = 0;
    always #5 clk = ~clk;

    logic in_valid = 0, in_ready;
    logic [8:0] in_row, write_row, norm_row;
    logic [279:0] residual_q32;
    logic [63:0] projection_codes;
    logic [4:0] projection_shift;
    logic write_valid, write_ready;
    logic [231:0] write_data;
    logic norm_valid, norm_ready;
    logic [127:0] norm_data;

    logic cfg_valid = 0, cfg_ready, replay = 0;
    logic [31:0] cfg_tag;
    logic stats_ready, replay_ready, out_valid, out_ready = 0;
    logic out_last, out_error;
    logic [31:0] out_tag;
    logic [9:0] out_index;
    logic [3:0] out_count;
    logic [127:0] out_norm_q8;
    logic [7:0] out_outlier_mask;
    logic [63:0] out_activation;

    logic readback = 0, read_offer = 0, read_ready = 0;
    logic bank_ready, bank_valid, bank_ce_n, bank_we_n;
    logic [8:0] read_row, bank_address;
    logic [231:0] bank_result;
    logic [255:0] bank_input, bank_output;
    logic [708:0] vectors [576];
    logic [255:0] normalization_inputs [512];
    logic [247:0] expected [512];
    string fixture, gamma_path, expected_path;
    int cycle, outputs, writes, stats_rows, replay_rows, output_stalls;

    tri_oracle_attention_residual_store producer (.*);
    wire allow_write = !replay && !readback && cycle%7 >= 3;
    wire [8:0] request_row = readback ? read_row : write_row;
    assign write_ready = replay || (allow_write && bank_ready);
    assign norm_ready = replay ? replay_ready : stats_ready;
    wire [8:0] gamma_row = norm_row;
`ifdef WRONG_GAMMA_ROW
    wire [127:0] replay_gamma = normalization_inputs[gamma_row ^ 9'd1][255:128];
`else
    wire [127:0] replay_gamma = normalization_inputs[gamma_row][255:128];
`endif
    tri_oracle_rms_activation activation (
        .clk, .rst_n, .cfg_valid, .cfg_ready, .cfg_tag,
        .cfg_epsilon_q16(32'd43980465), .cfg_strips(10'd256), .cfg_shift(6'd17),
        .stats_valid(norm_valid && !replay), .stats_ready,
        .stats_last(norm_row[7:0]==8'hff), .stats_data(norm_data),
        .replay_valid(norm_valid && replay), .replay_ready,
        .replay_last(norm_row[7:0]==8'hff), .replay_data(norm_data), .replay_gamma,
        .out_valid, .out_ready, .out_last, .out_error, .out_tag, .out_index,
        .out_count, .out_norm_q8, .out_outlier_mask, .out_activation
    );
    tri_oracle_residual_bank_adapter bank_port (
        .clk, .rst_n, .lease_granted(1'b1),
        .req_valid(readback ? read_offer : allow_write && write_valid),
        .req_ready(bank_ready), .req_write(!readback), .req_token(request_row[8]),
        .req_strip(request_row[7:0]), .req_data(write_data),
        .rsp_valid(bank_valid), .rsp_ready(read_ready), .rsp_data(bank_result),
        .bank_ce_n, .bank_we_n, .bank_addr(bank_address), .bank_d(bank_input), .bank_q(bank_output)
    );
    for (genvar bank=0; bank<4; bank++) begin : residual_banks
        TS5N28HPCPSVTA512X64M4F memory (
            .CLK(clk), .CEB(bank_ce_n), .WEB(bank_we_n), .A(bank_address),
            .D(bank_input[64*bank +: 64]), .Q(bank_output[64*bank +: 64])
        );
    end

    always @(negedge clk) begin
        cycle++;
        out_ready = cycle%17 < 5;
    end

    always @(posedge clk) if (rst_n) begin
        if (write_valid && write_ready && !replay) begin
            if (write_row !== 9'(writes) || write_data !== vectors[writes][580:349])
                $fatal(1, "ATTENTION_RESIDUAL_ACTIVATION_WRITE index=%0d", writes);
            writes++;
        end
        if (norm_valid && norm_ready) begin
            if (norm_row !== 9'(replay ? replay_rows : stats_rows))
                $fatal(1, "ATTENTION_RESIDUAL_ACTIVATION_NORM_ROW row=%0d", norm_row);
            if (replay) replay_rows++;
            else stats_rows++;
        end
        if (out_valid && !out_ready) output_stalls++;
        if (out_valid && out_ready) begin
            if (outputs>=512 || {out_tag, out_index, out_count, out_last, out_error, out_norm_q8,
                                out_outlier_mask, out_activation} !== expected[outputs])
                $fatal(1, "ATTENTION_RESIDUAL_ACTIVATION_MISMATCH row=%0d", outputs);
            outputs++;
        end
    end

    task automatic supply_token(input int token);
        for (int strip=0; strip<256; strip++) begin
            in_row = {1'(token), 8'(strip)};
            {projection_shift, projection_codes, residual_q32} = vectors[in_row][348:0];
            in_valid = 1;
            do @(posedge clk); while (in_ready !== 1'b1);
            @(negedge clk);
        end
        in_valid = 0;
    endtask

    initial begin
        if (!$value$plusargs("VECTORS=%s", fixture) ||
            !$value$plusargs("NORM_INPUTS=%s", gamma_path) ||
            !$value$plusargs("NORM_EXPECTED=%s", expected_path))
            $fatal(1, "Missing trained residual and normalization vectors");
        $readmemh(fixture, vectors);
        $readmemh(gamma_path, normalization_inputs);
        $readmemh(expected_path, expected);
        repeat (3) @(negedge clk);
        rst_n = 1;
        for (int token=0; token<2; token++) begin
            cfg_tag = 32'ha4010000 + 32'(token);
            cfg_valid = 1;
            do @(posedge clk); while (cfg_ready !== 1'b1);
            @(negedge clk);
            cfg_valid = 0;
            replay = 0;
            supply_token(token);
            wait (stats_rows==(token+1)*256 && writes==(token+1)*256);
            @(negedge clk);
            replay = 1;
            supply_token(token);
            wait (outputs==(token+1)*256 && cfg_ready);
            @(negedge clk);
        end
        if (replay_rows!=512 || output_stalls==0) $fatal(1, "ATTENTION_RESIDUAL_ACTIVATION_CENSUS");
        readback = 1;
        for (int row=0; row<512; row++) begin
            read_row = 9'(row);
            read_offer = 1;
            @(posedge clk);
            if (!bank_ready || bank_ce_n || !bank_we_n)
                $fatal(1, "ATTENTION_RESIDUAL_ACTIVATION_READ_REQUEST row=%0d", row);
            @(negedge clk);
            read_offer = 0;
            if (!bank_valid || bank_result !== vectors[row][580:349])
                $fatal(1, "ATTENTION_RESIDUAL_ACTIVATION_READBACK row=%0d", row);
            read_ready = 1;
            @(negedge clk);
            read_ready = 0;
        end
        $display("ATTENTION_RESIDUAL_ACTIVATION_PASS activation_values=4096 residual_values=4096 banks=4 stalls=%0d",
                 output_stalls);
        $finish;
    end
    initial begin #200000; $fatal(1, "ATTENTION_RESIDUAL_ACTIVATION_TIMEOUT"); end
endmodule
