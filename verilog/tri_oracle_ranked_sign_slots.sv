`timescale 1ns/1ps

// Observe each strip once per token during metadata fill. The first token
// initializes every configured strip, including inactive strips. Build may
// coincide with the final observation. Single-token frames bypass allocation.
module tri_oracle_ranked_sign_slots #(
    parameter int SLOT_BITS = 5
) (
    input logic clk, rst_n,
    input logic frame_start, frame_enable,
    input logic [8:0] frame_strips,
    input logic observe_valid, observe_first, observe_active,
    input logic [7:0] observe_strip,
    input logic build,
    output logic map_ready,
    input logic [7:0] lookup_strip,
    output logic lookup_valid,
    output logic [SLOT_BITS-1:0] lookup_slot
);
    localparam int ENTRIES = 1 << SLOT_BITS;
    typedef enum logic [2:0] {Idle, Collect, FindCutoff, BuildMap, Ready, Bypass} state_t;
    state_t state;

    logic [8:0] strips;
    logic [4:0] strip_uses[256];
    logic [8:0] histogram[17];
    logic [4:0] cutoff, uses;
    logic [8:0] remaining;
    logic [7:0] scan_strip, count_address;
    logic [SLOT_BITS-1:0] next_slot, strip_slot[256];
    logic strip_selected[256];
    logic observe, add_use, select_strip;

    assign count_address = state == BuildMap ? scan_strip : observe_strip;
    assign uses = state == Collect && observe_first ? 5'd0 : strip_uses[count_address];
    assign observe = state == Collect && observe_valid && {1'b0, observe_strip} < strips;
    assign add_use = observe && observe_active && uses < 5'd16;
    assign select_strip = uses > cutoff || (uses == cutoff && remaining != 0);
    assign map_ready = state == Ready || state == Bypass;
    assign lookup_valid = state == Ready && {1'b0, lookup_strip} < strips && strip_selected[lookup_strip];
    assign lookup_slot = lookup_valid ? strip_slot[lookup_strip] : '0;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= Idle;
            strips <= '0;
            cutoff <= '0;
            remaining <= '0;
            scan_strip <= '0;
            next_slot <= '0;
            foreach (histogram[bin]) histogram[bin] <= '0;
        end else if (frame_start) begin
            state <= frame_enable && frame_strips != 0 && frame_strips <= 9'd256 ? Collect : Bypass;
            strips <= frame_strips;
            cutoff <= 5'd16;
            remaining <= 9'(ENTRIES);
            scan_strip <= '0;
            next_slot <= '0;
            foreach (histogram[bin]) histogram[bin] <= bin == 0 ? frame_strips : 9'd0;
        end else case (state)
            Collect: begin
                // The first token initializes every configured entry.
                if (observe && (observe_first || add_use))
                    strip_uses[observe_strip] <= add_use ? uses + 5'd1 : 5'd0;
                if (add_use) begin
                    histogram[uses] <= histogram[uses] - 9'd1;
                    histogram[uses + 5'd1] <= histogram[uses + 5'd1] + 9'd1;
                end
                if (build) state <= FindCutoff;
            end
            FindCutoff: begin
                if (histogram[cutoff] >= remaining || cutoff == 5'd2) state <= BuildMap;
                else begin
                    remaining <= remaining - histogram[cutoff];
                    cutoff <= cutoff - 5'd1;
                end
            end
            BuildMap: begin
                strip_selected[scan_strip] <= select_strip;
                if (select_strip) begin
                    strip_slot[scan_strip] <= next_slot;
                    next_slot <= next_slot + 1'b1;
                    if (uses == cutoff) remaining <= remaining - 9'd1;
                end
                if ({1'b0, scan_strip} + 9'd1 == strips) state <= Ready;
                else scan_strip <= scan_strip + 8'd1;
            end
            default: ;
        endcase
    end
endmodule
