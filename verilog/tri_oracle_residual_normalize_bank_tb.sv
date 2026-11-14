`timescale 1ns/1ps
module tri_oracle_residual_normalize_bank_tb;
    logic clk=0, rst_n=0;
    always #5 clk=~clk;
    logic lease_granted=0, cfg_valid=0, cfg_ready, cfg_token;
    logic [31:0] cfg_tag;
    logic in_valid=0, in_ready;
    logic [279:0] residual_q32;
    logic [63:0] projection_codes;
    logic [4:0] projection_shift;
    logic gamma_valid, gamma_ready;
    logic [7:0] gamma_strip;
    logic [127:0] gamma_data;
    logic out_valid, out_ready, out_last, out_error;
    logic [31:0] out_tag;
    logic [9:0] out_index;
    logic [3:0] out_count;
    logic [127:0] out_norm_q8;
    logic [7:0] out_outlier_mask;
    logic [63:0] out_activation;
    logic read_valid=0, read_ready, response_valid, response_ready=0;
    logic [8:0] read_row;
    logic [231:0] response_data;
    logic bank_ce_n, bank_we_n;
    logic [8:0] bank_addr;
    logic [255:0] bank_d, bank_q;

    logic [708:0] vectors[576];
    logic [255:0] normalization_inputs[512];
    logic [247:0] expected[512];
    string fixture, gamma_path, expected_path;
    int cycle, inputs, outputs, gamma_count, writes, reads, stalls;
    logic halfway_case=0;
    int halfway_outputs=0;

    tri_oracle_residual_normalize_bank dut (
        .*, .cfg_epsilon_q16(32'd43980465), .cfg_shift(6'd17)
    );
    for (genvar bank=0; bank<4; bank++) begin : banks
        wire [8:0] address;
`ifdef SWAP_REPLAY_ADDRESS
        assign address = bank_we_n ? bank_addr ^ 9'd1 : bank_addr;
`else
        assign address = bank_addr;
`endif
        wire [63:0] data_in;
`ifdef OMIT_REPLAY_CORRECTION
        if (bank == 3) assign data_in = {24'd0, bank_d[231:192]};
        else assign data_in = bank_d[64*bank +: 64];
`else
        assign data_in = bank_d[64*bank +: 64];
`endif
        TS5N28HPCPSVTA512X64M4F memory (
            .CLK(clk), .CEB(bank_ce_n), .WEB(bank_we_n), .A(address),
            .D(data_in), .Q(bank_q[64*bank +: 64])
        );
    end
    assign out_ready = cycle%17<5;
    assign gamma_valid = cycle%7>=3;
    assign gamma_data = normalization_inputs[{cfg_token, gamma_strip}][255:128];

    always @(negedge clk) cycle++;
    always @(posedge clk) if (rst_n && halfway_case) begin
        if (!bank_ce_n && !bank_we_n && bank_addr == 0 &&
            (bank_d[247:232] !== 16'h0007 || bank_d[57:0] !== {-29'sd4096, 29'sd4096}))
            $fatal(1, "RESIDUAL_BANK_REPLAY_HALFWAY_ENCODING");
        if (out_valid && out_ready) begin
            if (out_error || out_tag !== 32'ha4010010 || out_index !== 10'(halfway_outputs) ||
                out_count !== 4'd8 || out_last !== (halfway_outputs == 255) ||
                {out_norm_q8, out_outlier_mask, out_activation} !== '0)
                $fatal(1, "RESIDUAL_BANK_REPLAY_HALFWAY_OUTPUT row=%0d", halfway_outputs);
            halfway_outputs++;
        end
    end else if (rst_n) begin
        if (in_valid && in_ready) inputs++;
        if (gamma_valid && gamma_ready) begin
            if (gamma_strip !== 8'(gamma_count)) $fatal(1, "RESIDUAL_BANK_REPLAY_GAMMA_ORDER");
            gamma_count++;
        end
        if (!bank_ce_n && !bank_we_n) begin
            if (bank_addr !== 9'(writes) || bank_d[231:0] !== vectors[writes][580:349] ||
                bank_d[255:248] !== 0)
                $fatal(1, "RESIDUAL_BANK_REPLAY_WRITE row=%0d", writes);
            writes++;
        end
        if (!bank_ce_n && bank_we_n) reads++;
        if (out_valid && !out_ready) stalls++;
        if (out_valid && out_ready) begin
            if (outputs>=512 || {out_tag, out_index, out_count, out_last, out_error, out_norm_q8,
                                out_outlier_mask, out_activation} !== expected[outputs])
                $fatal(1, "RESIDUAL_BANK_REPLAY_OUTPUT row=%0d", outputs);
            outputs++;
        end
    end

    initial begin
        if (!$value$plusargs("VECTORS=%s", fixture) ||
            !$value$plusargs("NORM_INPUTS=%s", gamma_path) ||
            !$value$plusargs("NORM_EXPECTED=%s", expected_path))
            $fatal(1, "Missing trained bank replay vectors");
        $readmemh(fixture, vectors);
        $readmemh(gamma_path, normalization_inputs);
        $readmemh(expected_path, expected);
        repeat (3) @(negedge clk);
        rst_n=1;
        if (cfg_ready) $fatal(1, "RESIDUAL_BANK_REPLAY_UNLEASED");
        lease_granted=1;
        for (int token=0; token<2; token++) begin
            cfg_token=1'(token);
            cfg_tag=32'ha4010000+32'(token);
            cfg_valid=1;
            do @(posedge clk); while (cfg_ready !== 1'b1);
            @(negedge clk);
            cfg_valid=0;
            for (int strip=0; strip<256; strip++) begin
                {projection_shift, projection_codes, residual_q32} = vectors[256*token+strip][348:0];
                in_valid=1;
                do @(posedge clk); while (in_ready !== 1'b1);
                @(negedge clk);
            end
            in_valid=0;
            wait (outputs==(token+1)*256 && cfg_ready);
            @(negedge clk);
        end
        if (gamma_count!=512 || writes!=512 || reads!=512 || inputs!=512 || stalls==0)
            $fatal(1, "RESIDUAL_BANK_REPLAY_CENSUS input=%0d gamma=%0d writes=%0d reads=%0d",
                   inputs, gamma_count, writes, reads);
        for (int row=0; row<512; row++) begin
            read_row=9'(row);
            read_valid=1;
            do @(posedge clk); while (read_ready !== 1'b1);
            @(negedge clk);
            read_valid=0;
            if (!response_valid || response_data !== vectors[row][580:349])
                $fatal(1, "RESIDUAL_BANK_REPLAY_READBACK row=%0d", row);
            response_ready=1;
            @(negedge clk);
            response_ready=0;
        end
        halfway_case=1;
        cfg_token=0;
        cfg_tag=32'ha4010010;
        cfg_valid=1;
        do @(posedge clk); while (cfg_ready !== 1'b1);
        @(negedge clk);
        cfg_valid=0;
        projection_shift=0;
        projection_codes=0;
        for (int strip=0; strip<256; strip++) begin
            // Rounding to 26 fractional bits hits both halfway points.
            // Direct rounding to 13 fractional bits produces two zeros.
            residual_q32 = strip == 0 ? {210'd0, -35'sd262143, 35'sd262143} : '0;
            in_valid=1;
            do @(posedge clk); while (in_ready !== 1'b1);
            @(negedge clk);
        end
        in_valid=0;
        wait (halfway_outputs==256 && cfg_ready);
        $display("RESIDUAL_BANK_REPLAY_PASS inputs=%0d activation_values=%0d bypass_values=4096 bank_reads=%0d stalls=%0d halfway_rows=%0d",
                 inputs, outputs*8, reads, stalls, halfway_outputs);
        $finish;
    end
    initial begin #300000; $fatal(1, "RESIDUAL_BANK_REPLAY_TIMEOUT"); end
endmodule
