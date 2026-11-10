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
    parameter bit COMPILED_SIGN_BANK=0,
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
    logic [SLOT_W-1:0] frontier[IMAGE_WIDTH];
    logic [SLOT_W-1:0] column, upper_slot, left_slot, inherited_slot, free_slot, selected_slot;
    logic [FEATURES-1:0] left_sign, bank_read_sign;
    logic [HIT_W-1:0] threshold;
    logic [IMAGE_WIDTH-1:0] used, visible;
    logic new_image, has_map, has_upper, has_left, old_alias, advance, space;
    logic upper_match, left_match, free_found, inherited_found, store_sign, valid_step;
    wire [SLOT_W-1:0] bank_read_slot = old_alias ? inherited_slot : upper_slot;
    logic read_available, write_sign, reuse_left_sign;

    assign cfg_ready = state==Idle;
    assign done_valid = state==Result;
    assign space = !map_valid || map_ready;
    assign previous_root = new_image ? cursor : origins[cursor];
    assign old_alias = previous_root!=cursor;
    assign inherited_root = origins[previous_root];
    assign upper_slot = frontier[column];
    assign has_left = column!=0;
    assign left_slot = has_left ? frontier[column-1'b1] : '0;
    assign upper_match = has_upper && (reuse_left_sign ? left_match : reduction[LEVELS].upper[0]>=threshold);
    assign left_match = has_left && reduction[LEVELS].left[0]>=threshold;
    assign sign_ready = state==Run && space && read_available && !old_alias;
    assign advance = state==Run && space && read_available && (old_alias || sign_valid);
    assign write_sign = rst_n && advance && valid_step && store_sign;

    if (COMPILED_SIGN_BANK) begin : compiled_signs
        localparam int BANKS = (FEATURES+127)/128;
        localparam int DATA_W = 128*BANKS;
        logic read_valid;
        logic [DATA_W-1:0] read_data;
        wire needs_read = (old_alias || has_upper) && !reuse_left_sign;
        wire issue_read = rst_n && state==Run && needs_read && !read_valid;
        wire [4:0] address = write_sign ? 5'(selected_slot) : 5'(bank_read_slot);

        if (IMAGE_WIDTH > 32) begin : invalid_depth
            initial $fatal(1, "Compiled sign bank supports at most 32 columns");
        end

        // The memory holds its read output while disabled. Until this cursor
        // advances, its prefetched word remains valid through any input stall.
        assign reuse_left_sign = has_left && bank_read_slot==left_slot;
        assign read_available = !needs_read || read_valid;
        assign bank_read_sign = read_data[FEATURES-1:0];
        always_ff @(posedge clk or negedge rst_n) begin
            if (!rst_n) read_valid <= 0;
            else if (advance) read_valid <= 0;
            else if (issue_read) read_valid <= 1;
        end

        /* verilator lint_off DECLFILENAME */
        TS5N28HPCPSVTA32X128M2FW slices[BANKS-1:0] (
            .CLK(clk), .CEB(!(issue_read || write_sign)), .WEB(!write_sign),
            .A(address), .D(DATA_W'(sign_data)), .BWEB(128'b0), .Q(read_data)
        );
        /* verilator lint_on DECLFILENAME */
    end else begin : inferred_signs
        logic [FEATURES-1:0] bank_sign[IMAGE_WIDTH];
        assign reuse_left_sign = 0;
        assign read_available = 1;
        assign bank_read_sign = bank_sign[bank_read_slot];
        always_ff @(posedge clk) begin
            if (write_sign) bank_sign[selected_slot] <= sign_data;
        end
    end

    for (genvar level=0;level<=LEVELS;level++) begin : reduction
        localparam int NODES=LEAVES>>level;
        wire [HIT_W-1:0] upper[NODES], left[NODES];
        for (genvar node=0;node<NODES;node++) begin : counts
            if (level!=0) begin : sum
                assign upper[node]=reduction[level-1].upper[2*node]+reduction[level-1].upper[2*node+1];
                assign left[node]=reduction[level-1].left[2*node]+reduction[level-1].left[2*node+1];
            end else if (node<FEATURES) begin : compare
                assign upper[node]=HIT_W'(sign_data[node]==bank_read_sign[node]);
                assign left[node]=HIT_W'(sign_data[node]==left_sign[node]);
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
        inherited_slot='0;
        inherited_found=0;
        for (int slot=0;slot<IMAGE_WIDTH;slot++) begin
            if (!used[slot] && !free_found) begin
                free_found=1;
                free_slot=SLOT_W'(slot);
            end
            // Each root is created once, so at most one visible slot matches.
            if (visible[slot] && bank_root[slot]==inherited_root) begin
                inherited_found=1;
                inherited_slot=inherited_slot | SLOT_W'(slot);
            end
        end
    end

    always_comb begin
        store_sign=0;
        valid_step=1;
        if (old_alias) begin
            selected_slot=inherited_slot;
            selected_root=inherited_root;
            valid_step=inherited_found;
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
                            bank_root[selected_slot]<=cursor;
                            left_sign<=sign_data;
                        end else if ((old_alias || upper_match) && !reuse_left_sign) begin
                            left_sign<=bank_read_sign;
                        end
                        // The next column sees this step's chosen sign as its left
                        // neighbor. A left match keeps the prior cached sign.
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
