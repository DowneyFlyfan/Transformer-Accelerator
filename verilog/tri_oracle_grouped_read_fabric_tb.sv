`timescale 1ns/1ps

module tri_oracle_grouped_read_fabric_tb;
    localparam int BurstsPerCluster = 24;
    logic clk = 0, rst_n = 0;
    always #5 clk = ~clk;

    logic [4:0] client_req_valid = '0, client_req_ready;
    logic [4:0][63:0] client_req_address = '0;
    logic [4:0][5:0] client_req_length = '0;
    logic [4:0] client_rsp_valid, client_rsp_ready = '0;
    logic [4:0] client_rsp_last, client_rsp_error;
    logic [4:0][511:0] client_rsp_data;
    logic [1:0] mem_req_valid, mem_req_ready = '0;
    logic [1:0][63:0] mem_req_address;
    logic [1:0][5:0] mem_req_length;
    logic [1:0] mem_rsp_valid = '0, mem_rsp_last = '0, mem_rsp_error = '0, mem_rsp_ready;
    logic [1:0][511:0] mem_rsp_data = '0;

    int sent[5] = '{default:0}, completed[5] = '{default:0};
    int lane_owner[2] = '{-1, -1};
    int lane_beat[2] = '{default:0};
    int cycles = 0, request_stalls = 0, response_stalls = 0, overlapping = 0, transfers = 0, errors = 0;
    logic [1:0] held = '0, held_response = '0;
    logic [1:0][69:0] held_request = '0;

    tri_oracle_grouped_read_fabric dut (.*);

    function automatic logic [63:0] address(input int client, sequence_no);
        return (64'(client) << 16) | (64'(sequence_no) << 6);
    endfunction

    function automatic int length(input int client, sequence_no);
        return sequence_no == 0 ? 63 : 1 + (client * 5 + sequence_no * 3) % 11;
    endfunction

    function automatic logic [511:0] data_word(input int client, sequence_no, beat);
        logic [511:0] value;
        for (int word = 0; word < 8; word++)
            value[word*64+:64] = 64'ha7c3000000000000 | (64'(word) << 32) |
                                 (64'(client) << 24) | (64'(sequence_no) << 16) | 64'(beat);
        return value;
    endfunction

    always @(posedge clk) if (rst_n) begin : scoreboard
        logic [4:0] req_ready, rsp_valid;
        int offered[2];
        req_ready = '0;
        rsp_valid = '0;
        if (lane_owner[0] >= 0 && lane_owner[1] >= 0) overlapping++;
        for (int lane = 0; lane < 2; lane++) begin
            int client, sequence_no;
            offered[lane] = -1;
            if (held[lane] &&
                {mem_req_valid[lane], mem_req_address[lane], mem_req_length[lane]} !==
                {1'b1, held_request[lane]})
                $fatal(1, "GROUPED_READ_UNSTABLE_OFFER lane=%0d", lane);
            held[lane] = mem_req_valid[lane] && !mem_req_ready[lane];
            held_response[lane] = mem_rsp_valid[lane] && !mem_rsp_ready[lane];
            held_request[lane] = {mem_req_address[lane], mem_req_length[lane]};
            if (held[lane]) request_stalls++;
            if (mem_req_valid[lane]) begin
                client = int'(mem_req_address[lane][18:16]);
                offered[lane] = client;
                if (client >= 5 || lane_owner[lane] >= 0 || !client_req_valid[client] ||
                    sent[client] != completed[client] ||
                    mem_req_address[lane] !== address(client, sent[client]) ||
                    mem_req_length[lane] !== 6'(length(client, sent[client])))
                    $fatal(1, "GROUPED_READ_BAD_REQUEST lane=%0d client=%0d", lane, client);
                if (mem_req_ready[lane]) req_ready[client] = 1;
            end
            if (lane_owner[lane] >= 0) begin
                client = lane_owner[lane];
                sequence_no = completed[client];
                if (mem_rsp_ready[lane] !== client_rsp_ready[client])
                    $fatal(1, "GROUPED_READ_BAD_READY lane=%0d client=%0d", lane, client);
                if (mem_rsp_valid[lane]) begin
                    rsp_valid[client] = 1;
                    if ({client_rsp_data[client], client_rsp_last[client], client_rsp_error[client]} !==
                        {data_word(client, sequence_no, lane_beat[lane]), mem_rsp_last[lane], mem_rsp_error[lane]})
                        $fatal(1, "GROUPED_READ_BAD_RESPONSE lane=%0d client=%0d beat=%0d", lane, client, lane_beat[lane]);
                end
            end else if (mem_rsp_ready[lane] !== 0) $fatal(1, "GROUPED_READ_SPURIOUS_READY");
        end
        if (offered[0] >= 0 && offered[0] == offered[1]) $fatal(1, "GROUPED_READ_DUPLICATE_OFFER");
        if (client_req_ready !== req_ready || client_rsp_valid !== rsp_valid)
            $fatal(1, "GROUPED_READ_WRONG_OWNER");
        for (int lane = 0; lane < 2; lane++) begin
            if (mem_req_valid[lane] && mem_req_ready[lane]) begin
                lane_owner[lane] = offered[lane];
                lane_beat[lane] = 0;
                sent[offered[lane]]++;
            end else if (mem_rsp_valid[lane]) begin
                if (!mem_rsp_ready[lane]) response_stalls++;
                else begin
                    transfers++;
                    if (mem_rsp_error[lane]) errors++;
                    if (mem_rsp_last[lane]) begin
                        completed[lane_owner[lane]]++;
                        lane_owner[lane] = -1;
                    end else lane_beat[lane]++;
                end
            end
        end
    end

    initial begin : drive_traffic
        int finished, expected_transfers, expected_errors;
        expected_transfers = 0;
        expected_errors = 0;
        repeat (3) @(negedge clk);
        rst_n = 1;
        for (int client = 0; client < 5; client++)
            for (int burst = 0; burst < BurstsPerCluster; burst++) begin
                expected_transfers += length(client, burst);
                if ((client + burst) % 9 == 0) expected_errors++;
            end
        for (cycles = 0; cycles < 6000; cycles++) begin
            finished = 0;
            for (int client = 0; client < 5; client++) begin
                if (completed[client] == BurstsPerCluster) finished++;
                client_req_valid[client] = sent[client] == completed[client] && sent[client] < BurstsPerCluster;
                client_req_address[client] = address(client, sent[client]);
                client_req_length[client] = 6'(length(client, sent[client]));
                client_rsp_ready[client] = (cycles + client * 3) % 7 < 5;
            end
            if (finished == 5) break;
            for (int lane = 0; lane < 2; lane++) begin
                int client, sequence_no;
                mem_req_ready[lane] = (lane == 1 || cycles >= 17) && (cycles + lane) % 5 != 3;
                client = lane_owner[lane];
                mem_rsp_valid[lane] = 0;
                mem_rsp_last[lane] = 0;
                mem_rsp_error[lane] = 0;
                mem_rsp_data[lane] = '1;
                if (client >= 0) begin
                    sequence_no = completed[client];
                    mem_rsp_valid[lane] = held_response[lane] || (cycles + lane * 2) % 4 != 0;
                    mem_rsp_last[lane] = lane_beat[lane] + 1 == length(client, sequence_no);
                    mem_rsp_error[lane] = mem_rsp_last[lane] && (client + sequence_no) % 9 == 0;
                    mem_rsp_data[lane] = data_word(client, sequence_no, lane_beat[lane]);
                end
            end
            @(negedge clk);
        end
        if (finished != 5 || transfers != expected_transfers || errors != expected_errors ||
            request_stalls < 15 || response_stalls < 100 || overlapping < 100)
            $fatal(1, "GROUPED_READ_COVERAGE finished=%0d transfers=%0d errors=%0d", finished, transfers, errors);
        $display("GROUPED_READ_PASS clusters=5 bursts=%0d transfers=%0d errors=%0d request_stalls=%0d response_stalls=%0d overlapping_cycles=%0d",
                 5 * BurstsPerCluster, transfers, errors, request_stalls, response_stalls, overlapping);
        $finish;
    end
endmodule
