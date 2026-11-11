`timescale 1ns/1ps
// Pair retrieval heads in heavy groups with streaming heads in light groups.
// Keep each physical destination's head-slot count and publish both maps
// together. The deterministic order and retrieval-count cost are local choices.
module tri_oracle_head_offload (
    input  logic clk, rst_n,
    input  logic [31:0] known_heads, streaming_heads,
    input  logic [4:0] lookup_head,
    output logic map_ready,
    output logic [4:0] cluster_owner, core_owner
);
    typedef enum logic [2:0] {Ready, Clear, Seed, SweepStart, Sweep, Check, FindHeads, Swap} state_t;
    state_t state;
    logic [31:0] planned_known, planned_streaming;
    logic mode_core;
    logic [4:0] owner_map [2][32];
    logic [3:0] retrieval [20], streaming [20];
    logic [4:0] head_index, group_index, seed_owner, seed_group, current_group;
    logic [4:0] donor_group, receiver_group, donor_head, receiver_head;
    logic [3:0] donor_load, receiver_load;
    logic donor_found, receiver_found;

    function automatic logic [4:0] group_for(input logic per_core, input logic [4:0] owner);
        return per_core ? owner : {2'b0, owner[4:2]};
    endfunction

    assign seed_owner = tri_oracle_wac_softmax_types::core_owner(head_index);
    assign seed_group = group_for(mode_core, seed_owner);
    assign current_group = group_for(mode_core, owner_map[mode_core][head_index]);
    assign map_ready = state == Ready && known_heads == planned_known &&
                       (streaming_heads & known_heads) == planned_streaming;
    assign cluster_owner = owner_map[0][lookup_head];
    assign core_owner = owner_map[1][lookup_head];

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= Ready;
            planned_known <= '0;
            planned_streaming <= '0;
            mode_core <= 1'b0;
            head_index <= '0;
            group_index <= '0;
            donor_group <= '0;
            receiver_group <= '0;
            donor_head <= '0;
            receiver_head <= '0;
            donor_load <= '0;
            receiver_load <= '0;
            donor_found <= 1'b0;
            receiver_found <= 1'b0;
            for (int head = 0; head < 32; head++) begin
                owner_map[0][head] <= tri_oracle_wac_softmax_types::core_owner(5'(head));
                owner_map[1][head] <= tri_oracle_wac_softmax_types::core_owner(5'(head));
            end
            for (int group = 0; group < 20; group++) begin
                retrieval[group] <= '0;
                streaming[group] <= '0;
            end
        end else begin
            case (state)
                Ready: if (!map_ready) begin
                    planned_known <= known_heads;
                    planned_streaming <= streaming_heads & known_heads;
                    mode_core <= 1'b0;
                    state <= Clear;
                end
                Clear: begin
                    for (int group = 0; group < 20; group++) begin
                        retrieval[group] <= '0;
                        streaming[group] <= '0;
                    end
                    head_index <= '0;
                    state <= Seed;
                end
                Seed: begin
                    owner_map[mode_core][head_index] <= seed_owner;
                    if (planned_known[head_index]) begin
                        if (planned_streaming[head_index]) streaming[seed_group] <= streaming[seed_group] + 1'b1;
                        else retrieval[seed_group] <= retrieval[seed_group] + 1'b1;
                    end
                    if (head_index == 31) state <= SweepStart;
                    else head_index <= head_index + 1'b1;
                end
                SweepStart: begin
                    group_index <= '0;
                    donor_load <= '0;
                    receiver_load <= '1;
                    state <= Sweep;
                end
                Sweep: begin
                    if (retrieval[group_index] > donor_load) begin
                        donor_load <= retrieval[group_index];
                        donor_group <= group_index;
                    end
                    if (streaming[group_index] != 0 && retrieval[group_index] < receiver_load) begin
                        receiver_load <= retrieval[group_index];
                        receiver_group <= group_index;
                    end
                    if (group_index == (mode_core ? 5'd19 : 5'd4)) state <= Check;
                    else group_index <= group_index + 1'b1;
                end
                Check: begin
                    // A swap reduces the sum of squared retrieval loads iff
                    // the donor has at least two more retrieval heads.
                    if ({1'b0, donor_load} > {1'b0, receiver_load} + 5'd1) begin
                        head_index <= '0;
                        donor_found <= 1'b0;
                        receiver_found <= 1'b0;
                        state <= FindHeads;
                    end else if (!mode_core) begin
                        mode_core <= 1'b1;
                        state <= Clear;
                    end else state <= Ready;
                end
                FindHeads: begin
                    if (planned_known[head_index]) begin
                        if (!donor_found && !planned_streaming[head_index] && current_group == donor_group) begin
                            donor_head <= head_index;
                            donor_found <= 1'b1;
                        end
                        if (!receiver_found && planned_streaming[head_index] && current_group == receiver_group) begin
                            receiver_head <= head_index;
                            receiver_found <= 1'b1;
                        end
                    end
                    if (head_index == 31) state <= Swap;
                    else head_index <= head_index + 1'b1;
                end
                Swap: if (donor_found && receiver_found) begin
                    owner_map[mode_core][donor_head] <= owner_map[mode_core][receiver_head];
                    owner_map[mode_core][receiver_head] <= owner_map[mode_core][donor_head];
                    retrieval[donor_group] <= retrieval[donor_group] - 1'b1;
                    retrieval[receiver_group] <= retrieval[receiver_group] + 1'b1;
                    streaming[donor_group] <= streaming[donor_group] + 1'b1;
                    streaming[receiver_group] <= streaming[receiver_group] - 1'b1;
                    state <= SweepStart;
                end else state <= Clear;
                default: state <= Clear;
            endcase
        end
    end
endmodule
