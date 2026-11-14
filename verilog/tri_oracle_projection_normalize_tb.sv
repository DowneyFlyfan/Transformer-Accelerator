`timescale 1ns/1ps
module tri_oracle_projection_normalize_tb;
    logic clk=0, rst_n=0;
    always #5 clk=~clk;
    logic lease_granted=0, cfg_valid=0, cfg_ready, cfg_token;
    logic [31:0] cfg_tag;
    wire packet_request_valid, packet_request_ready, packet_response_ready;
    logic packet_response_valid=0;
    wire [5:0] packet_request_address;
    logic [511:0] packet_response_data;
    wire operand_valid, operand_ready, operand_token;
    wire [7:0] operand_strip;
    wire [279:0] residual_q32;
    wire [4:0] projection_shift;
    logic [511:0] projection_packets[64];
    string packet_path;
    int packet_reads, operand_stalls, packet_wait;
    logic [708:0] vectors[576];
    int cycle;
    wire [348:0] operands = vectors[{operand_token, operand_strip}][348:0];
    assign residual_q32 = operands[279:0];
    assign projection_shift = operands[348:344];
    assign operand_valid = cycle%7>=3;
    assign packet_request_ready = !packet_response_valid && packet_wait==0 && cycle%5>=2;
    always @(posedge clk) if (rst_n) begin
        if (packet_request_valid && packet_request_ready) begin
            if (packet_request_address !== {5'(packet_reads%32), 1'(packet_reads/32)})
                $fatal(1, "PROJECTION_NORMALIZE_PACKET_ADDRESS index=%0d", packet_reads);
            packet_reads++;
            packet_response_data <= projection_packets[packet_request_address];
            packet_wait <= 3;
        end else if (packet_wait!=0) begin
            packet_wait <= packet_wait-1;
            if (packet_wait==1) packet_response_valid <= 1;
        end else if (packet_response_valid && packet_response_ready) packet_response_valid <= 0;
        if (dut.projected_valid && !operand_valid) operand_stalls++;
    end
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

    logic [255:0] normalization_inputs[512];
    logic [247:0] expected[512];
    string fixture, gamma_path, expected_path;
    int inputs, outputs, gamma_count, writes, reads, stalls;

    tri_oracle_projection_normalize dut (
        .*, .cfg_epsilon_q16(32'd43980465), .cfg_shift(6'd17)
    );
    for (genvar bank=0; bank<4; bank++) begin : banks
        wire [8:0] address;
`ifdef SWAP_REPLAY_ADDRESS
        assign address = bank_we_n ? bank_addr ^ 9'd1 : bank_addr;
`else
        assign address = bank_addr;
`endif
        TS5N28HPCPSVTA512X64M4F memory (
            .CLK(clk), .CEB(bank_ce_n), .WEB(bank_we_n), .A(address),
            .D(bank_d[64*bank +: 64]), .Q(bank_q[64*bank +: 64])
        );
    end
    assign out_ready = cycle%17<5;
    assign gamma_valid = cycle%7>=3;
    assign gamma_data = normalization_inputs[{cfg_token, gamma_strip}][255:128];

    always @(negedge clk) cycle++;
    always @(posedge clk) if (rst_n) begin
        if (operand_valid && operand_ready) begin
            if ({operand_token, operand_strip} !== 9'(inputs))
                $fatal(1, "PROJECTION_NORMALIZE_OPERAND_ADDRESS index=%0d", inputs);
            inputs++;
        end
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
        if (!$value$plusargs("PACKETS=%s", packet_path)) $fatal(1, "Missing mapped packets");
        $readmemh(packet_path, projection_packets);
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
        if (packet_reads!=64 || operand_stalls==0)
            $fatal(1, "PROJECTION_NORMALIZE_INVENTORY packets=%0d operand_stalls=%0d", packet_reads, operand_stalls);
        $display("PROJECTION_NORMALIZE_PASS packets=%0d strips=%0d activations=4096 residuals=4096 operand_stalls=%0d",
                 packet_reads, inputs, operand_stalls);
        $finish;
    end
    initial begin #300000; $fatal(1, "RESIDUAL_BANK_REPLAY_TIMEOUT"); end
endmodule
