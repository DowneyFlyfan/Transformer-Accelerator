`timescale 1ns/1ps
module tri_oracle_projection_shared_bus_tb;
    logic clk=0, rst_n=0;
    always #5 clk=~clk;
    logic lease_granted=0, cfg_valid=0, cfg_ready, cfg_token;
    logic [31:0] cfg_tag;
    wire req_valid, req_ready, rsp_ready;
    wire [63:0] req_address;
    wire [4:0] req_length;
    logic [63:0] rsp_data;
    logic rsp_valid, rsp_last, rsp_error;
    int burst_packet, bus_beat, bus_beats, packet_wait;
    bit burst_active, inject_fault;
    bit recovery_case;
    wire operand_valid, operand_ready, operand_token;
    wire [7:0] operand_strip;
    wire [279:0] residual_q32;
    wire [4:0] projection_shift;
    logic [511:0] projection_packets[64];
    string packet_path;
    int packet_reads, operand_stalls;
    logic [708:0] vectors[576];
    int cycle;
    wire [348:0] operands = vectors[{operand_token, operand_strip}][348:0];
    assign residual_q32 = operands[279:0];
    assign projection_shift = operands[348:344];
    assign operand_valid = cycle%7>=3;
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
    int recovery_outputs=0, errors=0;

    tri_oracle_projection_bus_normalize dut (
        .*, .cfg_epsilon_q16(32'd43980465), .cfg_shift(6'd17)
    );
    logic native_req_valid, native_req_ready, native_rsp_valid, native_rsp_ready;
    logic native_rsp_last, native_rsp_error;
    logic [63:0] native_rsp_data, native_address;
    logic mem_req_valid, mem_req_ready, mem_rsp_valid, mem_rsp_ready;
    logic mem_rsp_last, mem_rsp_error;
    logic [63:0] mem_req_address, mem_rsp_data;
    logic [4:0] mem_req_length;
    bit native_burst;
    logic [63:0] accepted_native_address;
    int native_requests, native_beats, native_terminals, native_owner_stalls;
    int request_stalls;
    logic held_request, held_native_response;
    logic [68:0] held_payload;

    tri_oracle_narrow_read_arbiter shared_bus (
        .clk, .rst_n, .client_req_valid({req_valid,native_req_valid}),
        .client_req_ready({req_ready,native_req_ready}),
        .client_req_address({req_address,native_address}), .client_req_length({req_length,5'd2}),
        .client_rsp_valid({rsp_valid,native_rsp_valid}), .client_rsp_ready({rsp_ready,native_rsp_ready}),
        .client_rsp_last({rsp_last,native_rsp_last}), .client_rsp_error({rsp_error,native_rsp_error}),
        .client_rsp_data({rsp_data,native_rsp_data}),
        .mem_req_valid, .mem_req_ready, .mem_req_address, .mem_req_length,
        .mem_rsp_valid, .mem_rsp_ready, .mem_rsp_last, .mem_rsp_error, .mem_rsp_data
    );
    assign native_address = 64'h10000000+64'(native_requests)*16;
    assign native_req_valid = native_requests<256 && native_requests==native_terminals;
    assign native_rsp_ready = cycle%7>=4 &&
                              !(native_terminals==0 && native_beats==1 && !held_native_response);
    assign mem_req_ready = !burst_active && cycle%5>=2;
    assign mem_rsp_valid = burst_active && packet_wait==0;
    assign mem_rsp_last = bus_beat==(native_burst ? 1 : 7);
    assign mem_rsp_error = !native_burst && inject_fault && burst_packet==6 && bus_beat==2;
    assign mem_rsp_data = native_burst ? accepted_native_address+64'(bus_beat)*8 :
                                         projection_packets[burst_packet][64*bus_beat +: 64];

    always @(posedge clk) if (rst_n) begin
        if (held_request && (!mem_req_valid || {mem_req_address,mem_req_length} !== held_payload))
            $fatal(1,"PROJECTION_BUS_STALLED_OFFER");
        held_request = mem_req_valid && !mem_req_ready;
        held_payload = {mem_req_address,mem_req_length};
        if (held_request) request_stalls++;
        if (held_native_response && !native_rsp_valid)
            $fatal(1,"PROJECTION_BUS_LOST_STALLED_TERMINAL");
        held_native_response <= native_rsp_valid && !native_rsp_ready && native_rsp_last;
        if (native_rsp_valid && rsp_valid) $fatal(1,"PROJECTION_BUS_DOUBLE_OWNER");
        if (native_rsp_valid) begin
            if (!native_burst || native_rsp_error || native_rsp_last !== (native_beats%2==1) ||
                native_rsp_data !== accepted_native_address+64'(native_beats%2)*8)
                $fatal(1,"PROJECTION_BUS_NATIVE_RESPONSE");
            if (native_rsp_ready) begin
                native_beats++;
                if (native_rsp_last) native_terminals++;
            end else if (req_valid) native_owner_stalls++;
        end
        if (mem_req_valid && mem_req_ready) begin
            native_burst <= mem_req_address>=64'h10000000;
            if (mem_req_address>=64'h10000000) begin
                if (!native_req_ready || mem_req_address !== native_address || mem_req_length !== 5'd2)
                    $fatal(1,"PROJECTION_BUS_NATIVE_REQUEST");
                accepted_native_address <= mem_req_address;
                native_requests <= native_requests+1;
            end else begin
                int slot;
                slot = recovery_case ? packet_reads-64 : packet_reads;
                if (!req_ready || mem_req_address !== 64'h02000000+64'(slot%32)*65536+64'(slot/32)*64 ||
                    mem_req_length !== 5'd8)
                    $fatal(1, "PROJECTION_BUS_ADDRESS index=%0d address=%h",packet_reads,mem_req_address);
                burst_packet <= 2*(slot%32)+slot/32;
                packet_reads <= packet_reads+1;
            end
            bus_beat <= 0;
            packet_wait <= 3;
            burst_active <= 1;
        end else if (packet_wait!=0) packet_wait <= packet_wait-1;
        else if (mem_rsp_valid && mem_rsp_ready) begin
            if (!native_burst) bus_beats++;
            if (mem_rsp_last) burst_active <= 0;
            else bus_beat <= bus_beat+1;
        end
        if (dut.normalizer.projected_valid && !operand_valid) operand_stalls++;
    end
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
    always @(posedge clk) if (rst_n && recovery_case) begin
        if (out_valid && out_ready) begin
            if (out_error) begin
                if (errors!=0 || !out_last || out_tag!==32'hac001001 || (burst_active && !native_burst) ||
                    {out_count,out_index,out_norm_q8,out_outlier_mask,out_activation} !== '0)
                    $fatal(1, "PROJECTION_BUS_FAULT_RESPONSE");
                errors++;
            end else begin
                if (errors!=1 || recovery_outputs>=256 ||
                    {out_tag,out_index,out_count,out_last,out_error,out_norm_q8,out_outlier_mask,out_activation}
                    !== expected[recovery_outputs])
                    $fatal(1,"PROJECTION_BUS_RECOVERY index=%0d",recovery_outputs);
                recovery_outputs++;
            end
        end
    end else if (rst_n) begin
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
        if (bus_beats!=512) $fatal(1, "PROJECTION_BUS_BEAT_COUNT count=%0d",bus_beats);
        recovery_case=1;
        inject_fault=1;
        cfg_token=0;
        cfg_tag=32'hac001001;
        cfg_valid=1;
        do @(posedge clk); while (cfg_ready !== 1'b1);
        @(negedge clk);
        cfg_valid=0;
        wait (errors==1 && cfg_ready);
        @(negedge clk);
        if (packet_reads!=68 || bus_beats!=544) $fatal(1,"PROJECTION_BUS_FAILED_DRAIN");
        packet_reads=64;
        inject_fault=0;
        cfg_tag=32'ha4010000;
        cfg_valid=1;
        do @(posedge clk); while (cfg_ready !== 1'b1);
        @(negedge clk);
        cfg_valid=0;
        wait (recovery_outputs==256 && cfg_ready);
        if (packet_reads!=96 || bus_beats!=800) $fatal(1,"PROJECTION_BUS_RECOVERY_COUNTS");
        if (native_requests!=256 || native_terminals!=256 || native_beats!=512 ||
            native_owner_stalls==0 || request_stalls==0)
            $fatal(1,"PROJECTION_BUS_CONTENTION_COVERAGE");
        $display("PROJECTION_SHARED_BUS_PASS packets=64 activations=4096 residuals=4096 native_bursts=%0d held_owner_cycles=%0d request_stalls=%0d drained_faults=%0d recovery_strips=%0d",
                 native_terminals,native_owner_stalls,request_stalls,errors,recovery_outputs);
        $finish;
    end
    initial begin
        #300000;
        $fatal(1, "PROJECTION_BUS_TIMEOUT packets=%0d native=%0d/%0d outputs=%0d/%0d errors=%0d mem=%b/%b burst=%b beat=%0d wait=%0d",
               packet_reads, native_requests, native_terminals, outputs, recovery_outputs,
               errors, mem_req_valid, mem_rsp_valid, burst_active, bus_beat, packet_wait);
    end
endmodule
