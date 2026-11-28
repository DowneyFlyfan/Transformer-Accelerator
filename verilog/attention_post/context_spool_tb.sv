`timescale 1ns/1ps
`default_nettype none

// Synthetic component test.  The byte-addressed external memory is a bus peer,
// not a second context collector.  Only successful write responses commit data.
module tri_oracle_context_spool_tb;
    localparam integer STRIDE = 4231;
    localparam integer MAX_CASES = 64;
    localparam integer MEMORY_BYTES = 65536;
    localparam logic [63:0] SPOOL_BASE = 64'h1000;
    localparam logic [63:0] CODE_BASE = 64'h8000;
    logic clk, rst_n, cfg_valid, cfg_ready;
    logic [31:0] cfg_tag;
    logic [15:0] cfg_query, cfg_epoch;
    logic [63:0] cfg_spool_base, cfg_code_base;
    logic [287:0] cfg_weight_units, cfg_output_units;
    logic context_valid, context_ready;
    logic [31:0] context_tag;
    logic [15:0] context_query, context_epoch;
    logic [4:0] context_head;
    logic signed [8:0] context_unit;
    logic [2047:0] context_data;
    logic broker_done_valid, broker_done_ready, broker_done_error;
    logic done_valid, done_ready, done_error;
    logic [31:0] done_tag;
    logic [15:0] done_query, done_epoch;
    logic signed [9:0] done_unit;
    logic wr_req_valid, wr_req_ready, wr_data_valid, wr_data_ready;
    logic [63:0] wr_address, wr_data;
    logic [4:0] wr_length;
    logic wr_last, wr_rsp_valid, wr_rsp_ready, wr_error;
    logic rd_req_valid, rd_req_ready, rd_rsp_valid, rd_rsp_ready;
    logic [63:0] rd_address, rd_data;
    logic [4:0] rd_length;
    logic rd_last, rd_error;

    logic [31:0] vectors [0:MAX_CASES*STRIDE-1];
    logic [7:0] memory [0:MEMORY_BYTES-1];
    logic [7:0] staged [0:127];
    integer scratch_written [0:8447];
    integer output_written [0:2047];
    integer current_case, scenario, vector_base, case_count, passed;
    integer cycles, context_acks, broker_acks, write_requests, read_requests;
    integer scratch_ack_bytes, output_ack_bytes, output_requests;
    integer write_beats, read_beats;
    logic case_begin, expected_error, injected;
    logic write_active, ack_active, read_active, read_offer;
    logic [63:0] write_address, read_address;
    integer write_length, write_index, read_length, read_index;
    integer ack_delay, read_delay;
    logic write_error_pending, read_error_pending, read_last_pending;
    logic held_wr_req, held_wr_data, held_rd_req, held_done;
    logic [68:0] held_wr_req_tuple, held_rd_req_tuple;
    logic [64:0] held_wr_data_tuple;
    logic [74:0] held_done_tuple;
    string vector_path;

    tri_oracle_context_spool dut (.*);

    task automatic require(input logic condition, input string message);
        if (condition !== 1'b1)
            $fatal(1, "CONTEXT_SPOOL_ASSERT case=%0d scenario=%0d cycle=%0d %s",
                   current_case, scenario, cycles, message);
    endtask

    function automatic logic is_scratch(input logic [63:0] address);
        return address >= SPOOL_BASE && address < SPOOL_BASE + 8448;
    endfunction
    function automatic logic is_code(input logic [63:0] address);
        return address >= CODE_BASE && address < CODE_BASE + 2048;
    endfunction

    // Deterministic stalls are independent of the DUT's valid signals.
    always_comb begin
        wr_req_ready = rst_n && !case_begin && !write_active && !ack_active &&
                       cycles % 5 != 1;
        wr_data_ready = rst_n && write_active && cycles % 7 != 2 && cycles % 7 != 3;
        wr_rsp_valid = rst_n && ack_active && ack_delay == 0;
        wr_error = write_error_pending;
        rd_req_ready = rst_n && !case_begin && !read_active && cycles % 6 != 2;
        rd_rsp_valid = rst_n && read_active && read_offer && read_delay == 0;
        rd_data = 0;
        for (integer byte_lane = 0; byte_lane < 8; byte_lane = byte_lane + 1)
            if (read_active && read_address + 8*read_index + byte_lane < MEMORY_BYTES)
                rd_data[8*byte_lane+:8] = memory[read_address + 8*read_index + byte_lane];
        rd_error = read_error_pending;
        rd_last = read_last_pending || read_index == read_length - 1;
    end

    // Exactly one accepted burst owns each response.  A response is first
    // exposed strictly after its request handshake, and stays stable on stall.
    always @(posedge clk) begin : memory_peer
        integer address;
        if (!rst_n || case_begin) begin
            cycles <= 0;
            context_acks <= 0;
            broker_acks <= 0;
            write_requests <= 0;
            read_requests <= 0;
            write_beats <= 0;
            read_beats <= 0;
            scratch_ack_bytes <= 0;
            output_ack_bytes <= 0;
            output_requests <= 0;
            write_active <= 0;
            ack_active <= 0;
            read_active <= 0;
            read_offer <= 0;
            write_address <= 0;
            read_address <= 0;
            write_length <= 0;
            write_index <= 0;
            read_length <= 0;
            read_index <= 0;
            ack_delay <= 0;
            read_delay <= 0;
            write_error_pending <= 0;
            read_error_pending <= 0;
            read_last_pending <= 0;
            injected <= 0;
            held_wr_req <= 0;
            held_wr_data <= 0;
            held_rd_req <= 0;
            held_done <= 0;
            for (integer i = 0; i < MEMORY_BYTES; i = i + 1) memory[i] = 8'hA5;
            for (integer i = 0; i < 8448; i = i + 1) scratch_written[i] = 0;
            for (integer i = 0; i < 2048; i = i + 1) output_written[i] = 0;
        end else begin
            cycles <= cycles + 1;
            require(cycles < 100000, "bounded per-case deadline");
            if (held_wr_req)
                require(wr_req_valid === 1'b1 && {wr_address,wr_length} === held_wr_req_tuple,
                        "write request changed while held");
            if (held_wr_data)
                require(wr_data_valid === 1'b1 && {wr_data,wr_last} === held_wr_data_tuple,
                        "write data changed while held");
            if (held_rd_req)
                require(rd_req_valid === 1'b1 && {rd_address,rd_length} === held_rd_req_tuple,
                        "read request changed while held");
            if (held_done)
                require(done_valid === 1'b1 &&
                        {done_error,done_tag,done_query,done_epoch,done_unit} === held_done_tuple,
                        "completion tuple changed while held");
            held_wr_req <= wr_req_valid === 1'b1 && wr_req_ready !== 1'b1;
            held_wr_data <= wr_data_valid === 1'b1 && wr_data_ready !== 1'b1;
            held_rd_req <= rd_req_valid === 1'b1 && rd_req_ready !== 1'b1;
            held_done <= done_valid === 1'b1 && done_ready !== 1'b1;
            held_wr_req_tuple <= {wr_address,wr_length};
            held_wr_data_tuple <= {wr_data,wr_last};
            held_rd_req_tuple <= {rd_address,rd_length};
            held_done_tuple <= {done_error,done_tag,done_query,done_epoch,done_unit};
            if (context_valid === 1'b1 && context_ready === 1'b1) context_acks <= context_acks + 1;
            if (broker_done_valid === 1'b1 && broker_done_ready === 1'b1) broker_acks <= broker_acks + 1;

            if (ack_active && ack_delay > 0) ack_delay <= ack_delay - 1;
            if (wr_rsp_valid === 1'b1 && wr_rsp_ready === 1'b1) begin
                require(ack_active && !write_active, "unowned write response");
                if (!write_error_pending) begin
                    for (integer b = 0; b < 8*write_length; b = b + 1) begin
                        address = int'(write_address) + b;
                        memory[address] = staged[b];
                        if (is_scratch(write_address)) begin
                            require(scratch_written[address-int'(SPOOL_BASE)] == 0,
                                    "scratch byte written twice");
                            scratch_written[address-int'(SPOOL_BASE)] = 1;
                        end else begin
                            require(output_written[address-int'(CODE_BASE)] == 0,
                                    "output byte written twice");
                            output_written[address-int'(CODE_BASE)] = 1;
                        end
                    end
                    if (is_scratch(write_address)) scratch_ack_bytes <= scratch_ack_bytes + 8*write_length;
                    else output_ack_bytes <= output_ack_bytes + 8*write_length;
                end
                ack_active <= 0;
            end
            if (wr_data_valid === 1'b1 && wr_data_ready === 1'b1) begin
                require(write_active && !$isunknown({wr_data,wr_last}), "unowned/unknown write data");
                require(wr_last === (write_index == write_length-1), "write LAST mismatch");
                for (integer b = 0; b < 8; b = b + 1) staged[8*write_index+b] = wr_data[8*b+:8];
                write_beats <= write_beats + 1;
                if (write_index == write_length-1) begin
                    write_active <= 0;
                    ack_active <= 1;
                    ack_delay <= 2 + current_case % 3;
                end else write_index <= write_index + 1;
            end
            if (wr_req_valid === 1'b1 && wr_req_ready === 1'b1) begin
                require(!write_active && !ack_active && !read_active, "more than one owned burst");
                require(!$isunknown({wr_address,wr_length}) && wr_length >= 1 && wr_length <= 16 &&
                        wr_address[2:0] == 0, "invalid write request");
                require((is_scratch(wr_address) && is_scratch(wr_address+8*wr_length-1)) ||
                        (is_code(wr_address) && is_code(wr_address+8*wr_length-1)),
                        "write outside exact caller allocations");
                if (is_code(wr_address)) begin
                    require(broker_acks == 1 && scratch_ack_bytes == 8448,
                            "output before full scratch ACK and broker terminal");
                    output_requests <= output_requests + 1;
                end
                write_requests <= write_requests + 1;
                write_address <= wr_address;
                write_length <= int'(wr_length);
                write_index <= 0;
                write_active <= 1;
                write_error_pending <= 0;
                if (!injected && ((scenario == 7 && is_scratch(wr_address)) ||
                                  (scenario == 8 && is_code(wr_address)))) begin
                    write_error_pending <= 1;
                    injected <= 1;
                end
            end

            if (read_active && read_delay > 0) read_delay <= read_delay - 1;
            if (read_active && !read_offer && read_delay == 0 && cycles % 5 != 3)
                read_offer <= 1;
            if (rd_rsp_valid === 1'b1 && rd_rsp_ready === 1'b1) begin
                require(read_active, "unowned read response");
                read_beats <= read_beats + 1;
                if (rd_last) begin
                    read_active <= 0;
                    read_offer <= 0;
                end else begin
                    read_index <= read_index + 1;
                    read_offer <= 0;
                    read_delay <= 1 + (read_index % 3);
                end
            end
            if (rd_req_valid === 1'b1 && rd_req_ready === 1'b1) begin
                require(!read_active && !write_active && !ack_active, "more than one owned burst");
                require(!$isunknown({rd_address,rd_length}) && rd_length >= 1 && rd_length <= 16 &&
                        rd_address[2:0] == 0 && is_scratch(rd_address) &&
                        is_scratch(rd_address+8*rd_length-1), "invalid read request");
                require(scratch_ack_bytes == 8448 && broker_acks == 1,
                        "read before complete scratch ACK and terminal");
                for (integer b = 0; b < 8*int'(rd_length); b = b + 1)
                    require(scratch_written[int'(rd_address-SPOOL_BASE)+b] == 1,
                            "read not backed by actual write ACK");
                read_requests <= read_requests + 1;
                read_address <= rd_address;
                read_length <= int'(rd_length);
                read_index <= 0;
                read_active <= 1;
                read_offer <= 0;
                read_delay <= 2;
                read_error_pending <= 0;
                read_last_pending <= 0;
                if (!injected && scenario == 9) begin
                    read_error_pending <= 1;
                    injected <= 1;
                end
                if (!injected && scenario == 10 && rd_length > 1) begin
                    read_last_pending <= 1;
                    injected <= 1;
                end
            end
            if (done_valid === 1'b1) begin
                require(!write_active && !ack_active && !read_active, "completion before owned transport drains");
                if (scenario != 11 && scenario != 12 && scenario != 13 && scenario != 16)
                    require(broker_acks == 1, "completion before admitted broker terminal");
            end
        end
    end

    task automatic send_head(input integer ordinal);
        integer selected_head;
        begin
            selected_head = int'(vectors[vector_base+103+ordinal]);
            if (scenario == 4 && ordinal == 7) selected_head = int'(vectors[vector_base+103+6]);
            @(negedge clk);
            context_tag = cfg_tag;
            context_query = cfg_query;
            context_epoch = cfg_epoch;
            context_head = 5'(selected_head);
            context_unit = 9'(vectors[vector_base+7+selected_head]);
            for (integer lane = 0; lane < 64; lane = lane + 1)
                context_data[32*lane+:32] = vectors[vector_base+135+64*selected_head+lane];
            if (ordinal == 7) begin
                case (scenario)
                    1: context_tag = cfg_tag ^ 32'h100;
                    2: context_query = cfg_query ^ 16'h100;
                    3: context_epoch = cfg_epoch ^ 16'h100;
                    14: context_data[1023] = 1'bx;
                    15: context_unit[8] = 1'bx;
                    default: begin end
                endcase
            end
            context_valid = 1;
            do @(posedge clk); while (context_ready !== 1'b1);
            @(negedge clk);
            context_valid = 0;
        end
    endtask

    task automatic send_terminal;
        begin
            @(negedge clk);
            broker_done_error = scenario == 6 ? 1'b1 : scenario == 17 ? 1'bx : 1'b0;
            broker_done_valid = 1;
            do @(posedge clk); while (broker_done_ready !== 1'b1);
            @(negedge clk);
            broker_done_valid = 0;
            broker_done_error = 0;
        end
    endtask

    task automatic check_scratch;
        integer value, address;
        begin
            require(scratch_ack_bytes == 8448, "not all scratch bytes ACKed");
            for (integer h = 0; h < 32; h = h + 1) begin
                for (integer lane = 0; lane < 64; lane = lane + 1) begin
                    value = int'(vectors[vector_base+135+64*h+lane]);
                    address = int'(SPOOL_BASE) + 256*h + 4*lane;
                    require({memory[address+3],memory[address+2],memory[address+1],memory[address]}
                            === 32'(value), "signed32 scratch lane mismatch");
                end
                address = int'(SPOOL_BASE) + 8192 + 8*h;
                require({memory[address+7],memory[address+6],memory[address+5],memory[address+4],
                         memory[address+3],memory[address+2],memory[address+1],memory[address]}
                        === {55'b0,9'(vectors[vector_base+7+h])}, "unit word/padding mismatch");
            end
        end
    endtask

    task automatic run_case(input integer index);
        integer heads_to_send;
        begin
            current_case = index;
            vector_base = index * STRIDE;
            scenario = int'(vectors[vector_base+1]);
            expected_error = vectors[vector_base+6] != 0;
            require(vectors[vector_base] == 32'(index), "vector index mismatch");
            @(negedge clk);
            case_begin = 1;
            @(negedge clk);
            case_begin = 0;
            cfg_tag = vectors[vector_base+2];
            cfg_query = 16'(vectors[vector_base+3]);
            cfg_epoch = 16'(vectors[vector_base+4]);
            cfg_spool_base = SPOOL_BASE;
            cfg_code_base = CODE_BASE;
            if (scenario == 11) cfg_spool_base = SPOOL_BASE + 1;
            if (scenario == 12) cfg_code_base = SPOOL_BASE + 64;
            if (scenario == 13) cfg_spool_base = 64'hFFFF_FFFF_FFFF_FFC0;
            for (integer h = 0; h < 32; h = h + 1) begin
                cfg_weight_units[9*h+:9] = 9'(vectors[vector_base+39+h]);
                cfg_output_units[9*h+:9] = 9'(vectors[vector_base+71+h]);
            end
            if (scenario == 16) cfg_weight_units[287] = 1'bx;
            cfg_valid = 1;
            do @(posedge clk); while (cfg_ready !== 1'b1);
            @(negedge clk);
            cfg_valid = 0;
            if (scenario != 11 && scenario != 12 && scenario != 13 && scenario != 16) begin
                heads_to_send = scenario == 5 ? 7 : 32;
                for (integer ordinal = 0; ordinal < heads_to_send; ordinal = ordinal + 1)
                    send_head(ordinal);
                if (scenario == 0 && !expected_error && index % 3 == 2) begin
                    wait (scratch_ack_bytes == 8448);
                    repeat (5) @(posedge clk);
                end
                send_terminal();
            end
            wait (done_valid === 1'b1);
            @(negedge clk);
            require(done_error === expected_error, "unexpected success/error classification");
            require(done_tag === cfg_tag && done_query === cfg_query && done_epoch === cfg_epoch,
                    "completion identity mismatch");
            if (!expected_error) begin
                check_scratch();
                require(context_acks == 32 && broker_acks == 1, "incomplete head/terminal acceptance");
                require(done_unit === 10'(vectors[vector_base+5]), "common unit mismatch");
                require(output_ack_bytes == 2048, "not all output bytes ACKed");
                for (integer b = 0; b < 2048; b = b + 1)
                    require(output_written[b] == 1 &&
                            memory[int'(CODE_BASE)+b] === 8'(vectors[vector_base+2183+b]),
                            "context code differs from independent exact rational");
            end else begin
                if (scenario == 7 || scenario == 8 || scenario == 9 || scenario == 10)
                    require(injected === 1'b1, "requested bus fault was never reached");
                if (scenario == 11 || scenario == 12 || scenario == 13 || scenario == 16)
                    require(context_acks == 0 && broker_acks == 0 && write_requests == 0 && read_requests == 0,
                            "invalid configuration touched payload/broker");
                if (scenario != 8) require(output_ack_bytes == 0, "failed job committed output payload");
            end
            repeat (5) begin
                @(posedge clk);
                #1ps;
                require(done_valid === 1'b1 && done_error === expected_error, "held completion lost");
            end
            @(negedge clk);
            done_ready = 1;
            @(posedge clk);
            @(negedge clk);
            done_ready = 0;
            #1ps;
            require(cfg_ready === 1'b1 && done_valid === 1'b0, "job did not retire to Idle");
            passed = passed + 1;
            $display("CONTEXT_SPOOL_CASE_PASS case=%0d scenario=%0d error=%0d contexts=%0d writes=%0d reads=%0d unit=%0d",
                     index, scenario, expected_error, context_acks, write_requests, read_requests, $signed(done_unit));
        end
    endtask

    initial begin
        clk = 0;
        forever #5ns clk = ~clk;
    end
    initial begin
        rst_n = 0;
        case_begin = 0;
        cfg_valid = 0;
        cfg_tag = 0;
        cfg_query = 0;
        cfg_epoch = 0;
        cfg_spool_base = 0;
        cfg_code_base = 0;
        cfg_weight_units = 0;
        cfg_output_units = 0;
        context_valid = 0;
        context_tag = 0;
        context_query = 0;
        context_epoch = 0;
        context_head = 0;
        context_unit = 0;
        context_data = 0;
        broker_done_valid = 0;
        broker_done_error = 0;
        done_ready = 0;
        current_case = -1;
        scenario = 0;
        vector_base = 0;
        expected_error = 0;
        passed = 0;
        case_count = 30;
        if (!$value$plusargs("VECTORS=%s", vector_path))
            $fatal(1, "+VECTORS=<generated context_spool_vectors.hex> required");
        if ($value$plusargs("CASES=%d", case_count)) begin end
        require(case_count > 0 && case_count <= MAX_CASES, "invalid case count");
        $readmemh(vector_path, vectors, 0, case_count*STRIDE-1);
        repeat (4) @(negedge clk);
        rst_n = 1;
        for (integer index = 0; index < case_count; index = index + 1) run_case(index);
        require(passed == case_count, "missing case result");
        $display("CONTEXT_SPOOL_TEST_PASS cases=%0d component_only=1", passed);
        $finish;
    end
    initial begin
        #20ms;
        $fatal(1, "CONTEXT_SPOOL_GLOBAL_DEADLINE");
    end
endmodule

`default_nettype wire
