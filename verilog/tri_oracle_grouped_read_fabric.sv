`timescale 1ns/1ps

// Five cluster engines share two burst-read lanes. A lane reserves its client
// when it captures a request and releases it after the last response transfer.
module tri_oracle_grouped_read_fabric (
    input  logic clk, rst_n,
    input  logic [4:0] client_req_valid,
    output logic [4:0] client_req_ready,
    input  logic [4:0][63:0] client_req_address,
    input  logic [4:0][5:0] client_req_length,
    output logic [4:0] client_rsp_valid,
    input  logic [4:0] client_rsp_ready,
    output logic [4:0] client_rsp_last, client_rsp_error,
    output logic [4:0][511:0] client_rsp_data,
    output logic [1:0] mem_req_valid,
    input  logic [1:0] mem_req_ready,
    output logic [1:0][63:0] mem_req_address,
    output logic [1:0][5:0] mem_req_length,
    input  logic [1:0] mem_rsp_valid, mem_rsp_last, mem_rsp_error,
    output logic [1:0] mem_rsp_ready,
    input  logic [1:0][511:0] mem_rsp_data
);
    typedef enum logic [1:0] {Idle, Offer, Receive} lane_state_t;
    lane_state_t state [2];
    logic [1:0][2:0] owner, candidate;
    logic [1:0] allocate;
    logic [2:0] next_client, priority_after_allocation;
    logic [4:0] waiting;

    always_comb begin : choose_clients
        int index;
        waiting = client_req_valid;
        for (int lane = 0; lane < 2; lane++)
            if (state[lane] != Idle) waiting[owner[lane]] = 0;

        allocate = '0;
        candidate = '0;
        priority_after_allocation = next_client;
        index = 0;
        for (int lane = 0; lane < 2; lane++) begin
            if (state[lane] == Idle) begin
                for (int offset = 0; offset < 5; offset++) begin
                    index = int'(priority_after_allocation) + offset;
                    if (index >= 5) index -= 5;
                    if (!allocate[lane] && waiting[index]) begin
                        allocate[lane] = 1;
                        candidate[lane] = 3'(index);
                    end
                end
                if (allocate[lane]) begin
                    waiting[candidate[lane]] = 0;
                    priority_after_allocation = candidate[lane] == 3'd4 ? 3'd0 : candidate[lane] + 1'b1;
                end
            end
        end
    end

    always_comb begin : route_transfers
        client_req_ready = '0;
        client_rsp_valid = '0;
        client_rsp_last = '0;
        client_rsp_error = '0;
        client_rsp_data = '0;
        mem_req_valid = '0;
        mem_rsp_ready = '0;
        for (int lane = 0; lane < 2; lane++) begin
            if (state[lane] == Offer) begin
                mem_req_valid[lane] = 1;
                client_req_ready[owner[lane]] = mem_req_ready[lane];
            end
            if (state[lane] == Receive) begin
                mem_rsp_ready[lane] = client_rsp_ready[owner[lane]];
                client_rsp_valid[owner[lane]] = mem_rsp_valid[lane];
                client_rsp_last[owner[lane]] = mem_rsp_last[lane];
                client_rsp_error[owner[lane]] = mem_rsp_error[lane];
                client_rsp_data[owner[lane]] = mem_rsp_data[lane];
            end
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            next_client <= '0;
            owner <= '0;
            mem_req_address <= '0;
            mem_req_length <= '0;
            for (int lane = 0; lane < 2; lane++) state[lane] <= Idle;
        end else begin
            next_client <= priority_after_allocation;
            for (int lane = 0; lane < 2; lane++) begin
                case (state[lane])
                    Idle: if (allocate[lane]) begin
                        owner[lane] <= candidate[lane];
                        mem_req_address[lane] <= client_req_address[candidate[lane]];
                        mem_req_length[lane] <= client_req_length[candidate[lane]];
                        state[lane] <= Offer;
                    end
                    Offer: if (mem_req_ready[lane]) state[lane] <= Receive;
                    Receive: if (mem_rsp_valid[lane] && mem_rsp_ready[lane] && mem_rsp_last[lane])
                        state[lane] <= Idle;
                    default: state[lane] <= Idle;
                endcase
            end
        end
    end
endmodule
