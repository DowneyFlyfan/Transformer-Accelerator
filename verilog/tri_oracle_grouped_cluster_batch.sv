`timescale 1ns/1ps

// Launch one grouped batch on any subset of the five cluster engines.
// The chip dispatcher holds the tag and descriptors through batch completion.
// Each result reports its originating cluster and the end of that cluster's stream.
module tri_oracle_grouped_cluster_batch (
    input  logic clk, rst_n,
    input  logic start_valid,
    output logic start_ready,
    input  logic [4:0] start_mask,
    output logic [4:0] cluster_start_valid,
    input  logic [4:0] cluster_start_ready,
    input  logic [4:0] cluster_done_valid, cluster_done_error,
    output logic [4:0] cluster_done_ready,
    input  logic [4:0] cluster_result_valid, cluster_result_last,
    input  logic [4:0][1:0] cluster_result_lane,
    input  logic [4:0][2047:0] cluster_result_data,
    output logic [4:0] cluster_result_ready,
    output logic result_valid, result_last,
    input  logic result_ready,
    output logic [2:0] result_cluster,
    output logic [1:0] result_lane,
    output logic [2047:0] result_data,
    output logic batch_active,
    output logic done_valid, done_error,
    input  logic done_ready
);
    typedef enum logic [1:0] {Idle, Execute, Complete} state_t;
    state_t state;
    logic [4:0] pending_launch, pending_done;
    logic [4:0] launched, retired, available_results;
    logic held_result, have_result;
    logic [2:0] held_cluster, result_priority, candidate;

    assign start_ready = state == Idle;
    assign done_valid = state == Complete;
    assign batch_active = state != Idle;
    assign cluster_start_valid = state == Execute ? pending_launch : '0;
    assign launched = cluster_start_valid & cluster_start_ready;
    assign cluster_done_ready = state == Execute ? pending_done & ~pending_launch : '0;
    assign retired = cluster_done_ready & cluster_done_valid;
    assign available_results = cluster_done_ready & cluster_result_valid;

    always_comb begin : choose_result
        int index;
        have_result = held_result;
        candidate = held_cluster;
        for (int offset = 0; offset < 5; offset++) begin
            index = int'(result_priority) + offset;
            if (index >= 5) index -= 5;
            if (!have_result && available_results[index]) begin
                candidate = 3'(index);
                have_result = 1;
            end
        end
    end

    assign result_cluster = candidate;
    assign result_valid = have_result && available_results[candidate];
    assign result_lane = cluster_result_lane[candidate];
    assign result_last = cluster_result_last[candidate];
    assign result_data = cluster_result_data[candidate];
    assign cluster_result_ready = result_valid && result_ready ? 5'b1 << candidate : '0;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= Idle;
            pending_launch <= '0;
            pending_done <= '0;
            done_error <= 0;
            held_result <= 0;
            held_cluster <= '0;
            result_priority <= '0;
        end else begin
            if (result_valid) begin
                held_result <= !result_ready;
                held_cluster <= candidate;
                if (result_ready)
                    result_priority <= candidate == 3'd4 ? 3'd0 : candidate + 1'b1;
            end
            case (state)
                Idle: if (start_valid) begin
                    pending_launch <= start_mask;
                    pending_done <= start_mask;
                    done_error <= start_mask == 0;
                    state <= start_mask == 0 ? Complete : Execute;
                end
                Execute: begin
                    pending_launch <= pending_launch & ~launched;
                    pending_done <= pending_done & ~retired;
                    if (|(retired & cluster_done_error)) done_error <= 1;
                    if ((pending_done & ~retired) == 0) state <= Complete;
                end
                Complete: if (done_ready) state <= Idle;
                default: state <= Idle;
            endcase
        end
    end
endmodule
