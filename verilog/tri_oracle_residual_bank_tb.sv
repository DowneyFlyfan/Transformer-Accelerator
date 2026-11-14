`timescale 1ns/1ps
module tri_oracle_residual_bank_tb;
    logic clk = 0, rst_n = 0;
    always #5 clk = ~clk;

    logic lease_granted = 0, req_valid = 0, req_ready, req_write;
    logic req_token;
    logic [7:0] req_strip;
    logic [231:0] req_data;
    logic rsp_valid, rsp_ready = 0;
    logic [231:0] rsp_data;
    logic bank_ce_n, bank_we_n;
    logic [8:0] bank_addr;
    logic [255:0] bank_d, bank_q;
    logic [620:0] samples [512];
    string fixture;

    tri_oracle_residual_bank_adapter dut (.*);
    for (genvar bank = 0; bank < 4; bank++) begin : input_memory
        TS5N28HPCPSVTA512X64M4F input_bank (
            .CLK(clk), .CEB(bank_ce_n), .WEB(bank_we_n), .A(bank_addr),
            .D(bank_d[64*bank +: 64]), .Q(bank_q[64*bank +: 64])
        );
    end

    task automatic write_strip(input int index);
        @(negedge clk); #1;
        req_valid = 1;
        req_write = 1;
        req_token = 1'(index / 256);
        req_strip = 8'(index);
        req_data = samples[index][231:0];
        #1;
        if (!req_ready || bank_ce_n || bank_we_n || bank_addr !== 9'(index) || bank_d[255:232] !== 0)
            $fatal(1, "RESIDUAL_BANK_WRITE index=%0d addr=%0d", index, bank_addr);
        @(posedge clk); #1;
        if (rsp_valid)
            $fatal(1, "RESIDUAL_BANK_WRITE_RETURNED_RESPONSE");
    endtask

    task automatic read_strip(input int index, input int stall);
        @(negedge clk); #1;
        req_write = 0;
        req_valid = 1;
        req_token = 1'(index / 256);
        req_strip = 8'(index);
        #1;
        if (!req_ready || bank_ce_n || !bank_we_n || bank_addr !== 9'(index))
            $fatal(1, "RESIDUAL_BANK_READ_INDEX index=%0d addr=%0d", index, bank_addr);
        @(posedge clk); #2;
        if (!rsp_valid || rsp_data !== samples[index][231:0])
            $fatal(1, "RESIDUAL_BANK_READBACK index=%0d actual=%h expected=%h", index, rsp_data, samples[index][231:0]);
        @(negedge clk); #1;
        req_valid = 0;
        req_write = 1;
        req_data = ~req_data;
        req_strip = ~req_strip;
        repeat (stall) begin
            @(posedge clk); #2;
            if (!rsp_valid || rsp_data !== samples[index][231:0] || req_ready || !bank_ce_n)
                $fatal(1, "RESIDUAL_BANK_STALLED_RESPONSE index=%0d", index);
        end
        @(negedge clk); #1;
        rsp_ready = 1;
        @(posedge clk); #2;
        if (rsp_valid)
            $fatal(1, "RESIDUAL_BANK_RESPONSE_NOT_RETIRED");
        @(negedge clk); #1;
        rsp_ready = 0;
    endtask

    initial begin
        if (!$value$plusargs("TRAINED=%s", fixture))
            $fatal(1, "RESIDUAL_BANK_FIXTURE_MISSING");
        $readmemh(fixture, samples);
        req_valid = 1;
        req_write = 1;
        req_token = 0;
        req_strip = 0;
        req_data = '1;
        repeat (3) @(negedge clk);
        #1;
        rst_n = 1;
        #1;
        if (req_ready || !bank_ce_n || rsp_valid)
            $fatal(1, "RESIDUAL_BANK_ACCESSED_WITHOUT_LEASE");
        req_valid = 0;
        @(negedge clk); #1;
        lease_granted = 1;
        for (int index = 0; index < 512; index++)
            write_strip(index);
        for (int slot = 0; slot < 512; slot++)
            read_strip((slot*149 + 257) % 512, slot % 4);

        // A controller can clear or release the lease after every response.
        @(negedge clk); #1;
        lease_granted = 0;
        req_valid = 1;
        req_write = 1;
        req_token = 1;
        req_strip = 8'hff;
        req_data = '0;
        #1;
        if (req_ready || !bank_ce_n || rsp_valid)
            $fatal(1, "RESIDUAL_BANK_LEASE_RELEASE_UNSAFE");
        @(negedge clk); #1;
        req_valid = 0;
        lease_granted = 1;
        read_strip(511, 2);
        $display("RESIDUAL_BANK_PASS trained_strips=512 values=4096 macros=4");
        $finish;
    end
    initial begin
        #100000;
        $fatal(1, "RESIDUAL_BANK_TIMEOUT");
    end
endmodule
