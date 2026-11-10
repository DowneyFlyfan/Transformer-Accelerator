`timescale 1ns/1ps
// Raster-order token merging across layers. Consume signs only for the prior
// layer's surviving roots, and emit a map entry for every original cell.
// Map entries below the cursor are current, and entries above it are prior.
// A removed cell inherits its earlier root's new destination. Neighboring
// groups stay connected, so the one-row frontier retains any sign still needed.
module tri_oracle_cumulative_token_merger423 #(
    parameter int IMAGE_WIDTH=24,
    parameter int IMAGE_HEIGHT=24,
    parameter int FEATURES=2048,
    localparam int TOKENS=IMAGE_WIDTH*IMAGE_HEIGHT,
    localparam int INDEX_W=TOKENS>1 ? $clog2(TOKENS) : 1,
    localparam int SLOT_W=IMAGE_WIDTH>1 ? $clog2(IMAGE_WIDTH) : 1,
    localparam int HIT_W=$clog2(FEATURES+1)
) (
    input logic clk, rst_n,
    input logic cfg_valid, cfg_new_image,
    output logic cfg_ready,
    input logic [HIT_W-1:0] cfg_minimum_matches,
    input logic sign_valid,
    output logic sign_ready,
    input logic [FEATURES-1:0] sign_data,
    output logic map_valid,
    input logic map_ready,
    output logic [INDEX_W-1:0] map_index, map_origin,
    output logic map_last,
    output logic done_valid, done_error,
    input logic done_ready
);
    localparam int LEVELS=$clog2(FEATURES);
    localparam int LEAVES=1<<LEVELS;
    typedef enum logic [1:0] {Idle, Run, Finish, Result} state_t;
    state_t state;
    logic [INDEX_W-1:0] cursor, previous_root, inherited_root, selected_root;
    logic [INDEX_W-1:0] origins[TOKENS], bank_root[IMAGE_WIDTH];
    logic [SLOT_W-1:0] frontier[IMAGE_WIDTH], root_slot[TOKENS];
    logic [SLOT_W-1:0] column, upper_slot, left_slot, inherited_slot, free_slot, selected_slot;
    logic [FEATURES-1:0] bank_sign[IMAGE_WIDTH];
    logic [HIT_W-1:0] threshold;
    logic [IMAGE_WIDTH-1:0] used, visible;
    logic new_image, has_map, has_upper, has_left, old_alias, advance, space;
    logic upper_match, left_match, free_found, store_sign, valid_step;

    assign cfg_ready = state==Idle;
    assign done_valid = state==Result;
    assign space = !map_valid || map_ready;
    assign previous_root = new_image ? cursor : origins[cursor];
    assign old_alias = previous_root!=cursor;
    assign inherited_root = origins[previous_root];
    assign inherited_slot = root_slot[inherited_root];
    assign upper_slot = frontier[column];
    assign has_left = column!=0;
    assign left_slot = has_left ? frontier[column-1'b1] : '0;
    assign upper_match = has_upper && reduction[LEVELS].upper[0]>=threshold;
    assign left_match = has_left && reduction[LEVELS].left[0]>=threshold;
    assign sign_ready = state==Run && space && !old_alias;
    assign advance = state==Run && space && (old_alias || sign_valid);

    for (genvar level=0;level<=LEVELS;level++) begin : reduction
        localparam int NODES=LEAVES>>level;
        wire [HIT_W-1:0] upper[NODES], left[NODES];
        for (genvar node=0;node<NODES;node++) begin : counts
            if (level!=0) begin : sum
                assign upper[node]=reduction[level-1].upper[2*node]+reduction[level-1].upper[2*node+1];
                assign left[node]=reduction[level-1].left[2*node]+reduction[level-1].left[2*node+1];
            end else if (node<FEATURES) begin : compare
                assign upper[node]=HIT_W'(sign_data[node]==bank_sign[upper_slot][node]);
                assign left[node]=HIT_W'(sign_data[node]==bank_sign[left_slot][node]);
            end else begin : padding
                assign upper[node]='0;
                assign left[node]='0;
            end
        end
    end

    always_comb begin
        used='0;
        visible='0;
        for (int col=0;col<IMAGE_WIDTH;col++) begin
            if (has_upper || col<int'(column)) begin
                visible[frontier[col]]=1;
                if (col!=int'(column)) used[frontier[col]]=1;
            end
        end
        free_slot='0;
        free_found=0;
        for (int slot=0;slot<IMAGE_WIDTH;slot++) begin
            if (!used[slot] && !free_found) begin
                free_found=1;
                free_slot=SLOT_W'(slot);
            end
        end
        store_sign=0;
        valid_step=1;
        if (old_alias) begin
            selected_slot=inherited_slot;
            selected_root=inherited_root;
            valid_step=visible[inherited_slot] && bank_root[inherited_slot]==inherited_root;
        end else if (upper_match) begin
            selected_slot=upper_slot;
            selected_root=bank_root[upper_slot];
        end else if (left_match) begin
            selected_slot=left_slot;
            selected_root=bank_root[left_slot];
        end else begin
            selected_slot=free_slot;
            selected_root=cursor;
            store_sign=1;
            valid_step=free_found;
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=Idle;
            has_map<=0;
            new_image<=1;
            cursor<='0;
            column<='0;
            has_upper<=0;
            threshold<='0;
            map_valid<=0;
            map_index<='0;
            map_origin<='0;
            map_last<=0;
            done_error<=0;
        end else begin
            if (map_valid && map_ready) map_valid<=0;
            case (state)
                Idle: if (cfg_valid) begin
                    new_image<=cfg_new_image;
                    threshold<=cfg_minimum_matches;
                    cursor<='0;
                    column<='0;
                    has_upper<=0;
                    done_error<=cfg_minimum_matches>HIT_W'(FEATURES) || (!cfg_new_image && !has_map);
                    if (cfg_minimum_matches>HIT_W'(FEATURES) || (!cfg_new_image && !has_map)) state<=Result;
                    else state<=Run;
                end
                Run: if (advance) begin
                    if (!valid_step) begin
                        done_error<=1;
                        has_map<=0;
                        state<=Result;
                    end else begin
                        if (store_sign) begin
                            root_slot[cursor]<=selected_slot;
                            bank_sign[selected_slot]<=sign_data;
                            bank_root[selected_slot]<=cursor;
                        end
                        frontier[column]<=selected_slot;
                        origins[cursor]<=selected_root;
                        map_valid<=1;
                        map_index<=cursor;
                        map_origin<=selected_root;
                        map_last<=cursor==INDEX_W'(TOKENS-1);
                        if (cursor==INDEX_W'(TOKENS-1)) state<=Finish;
                        else begin
                            cursor<=cursor+1'b1;
                            if (column==SLOT_W'(IMAGE_WIDTH-1)) begin
                                column<='0;
                                has_upper<=1;
                            end else column<=column+1'b1;
                        end
                    end
                end
                Finish: if (space) begin
                    has_map<=1;
                    state<=Result;
                end
                Result: if (done_ready) state<=Idle;
                default: begin
                    has_map<=0;
                    done_error<=1;
                    state<=Result;
                end
            endcase
        end
    end
endmodule
