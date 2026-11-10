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
    tri_oracle_cumulative_merge447 #(
        .IMAGE_WIDTH(IMAGE_WIDTH), .IMAGE_HEIGHT(IMAGE_HEIGHT), .FEATURES(FEATURES),
        .COMPILED_SIGN_BANK(COMPILED_SIGN_BANK)
    ) implementation (.merge_sign_control(), .merge_sign_counts('0), .merge_table_request(), .merge_table_word('0), .*);
endmodule

/* verilator lint_off DECLFILENAME */
module tri_oracle_cumulative_merge447 #(
    parameter int IMAGE_WIDTH=24,
    parameter int IMAGE_HEIGHT=24,
    parameter int FEATURES=2048,
    parameter bit COMPILED_SIGN_BANK=0,
    parameter bit AGGREGATOR_SIGN_BANK=0,
    parameter bit AGGREGATOR_MERGE_TABLE=0,
    localparam int TOKENS=IMAGE_WIDTH*IMAGE_HEIGHT,
    localparam int INDEX_W=TOKENS>1 ? $clog2(TOKENS) : 1,
    localparam int SLOT_W=IMAGE_WIDTH>1 ? $clog2(IMAGE_WIDTH) : 1,
    localparam int HIT_W=$clog2(FEATURES+1),
    localparam int BANK_W=128,
    localparam int BANKS=(FEATURES+BANK_W-1)/BANK_W,
    localparam int SHARDS=BANKS<5 ? BANKS : 5
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
    input logic done_ready,
    output logic [2*SLOT_W+2:0] merge_sign_control,
    input logic [2*SHARDS*HIT_W-1:0] merge_sign_counts,
    output logic [21:0] merge_table_request,
    input logic [79:0] merge_table_word
);
    localparam int BASE_BANKS=BANKS/SHARDS, EXTRA_BANKS=BANKS%SHARDS;
    localparam int SUM_LEVELS=$clog2(SHARDS), SUM_LEAVES=1<<SUM_LEVELS;
    typedef enum logic [1:0] {Idle, Run, Finish, Result} state_t;
    state_t state;
    logic [INDEX_W-1:0] cursor, previous_root, inherited_root, selected_root;
    logic [INDEX_W-1:0] bank_root[IMAGE_WIDTH];
    logic [SLOT_W-1:0] frontier[IMAGE_WIDTH];
    logic [SLOT_W-1:0] column, upper_slot, left_slot, inherited_slot, free_slot, selected_slot;
    logic [HIT_W-1:0] threshold;
    logic [IMAGE_WIDTH-1:0] used, visible;
    logic new_image, has_map, has_upper, has_left, old_alias, advance, space;
    logic upper_match, left_match, free_found, inherited_found, store_sign, valid_step;
    wire [SLOT_W-1:0] bank_read_slot = old_alias ? inherited_slot : upper_slot;
    logic read_available, issue_read, write_sign, reuse_left_sign;
    logic load_left_from_memory, table_ready;
    wire [HIT_W-1:0] upper_partial[SHARDS], left_partial[SHARDS];

    assign cfg_ready = state==Idle;
    assign done_valid = state==Result;
    assign space = !map_valid || map_ready;
    assign old_alias = previous_root!=cursor;
    if (AGGREGATOR_MERGE_TABLE) begin : remote_table
        typedef enum logic [1:0] {ReadPrevious, CapturePrevious, Resolve, CaptureInherited} table_state_t;
        table_state_t table_state;
        logic root_valid, alias_valid;
        logic [79:0] previous_word;
        logic [INDEX_W-1:0] last_root_index, last_root_origin, last_alias_index, last_alias_origin;
        wire [2:0] cursor_field = 3'(cursor);
        wire [2:0] parent_field = 3'(previous_root);
        wire root_hit = root_valid && previous_root==last_root_index;
        wire alias_hit = alias_valid && previous_root==last_alias_index;
        wire read_previous = rst_n && state==Run && table_state==ReadPrevious;
        wire read_inherited = rst_n && state==Run && table_state==Resolve && old_alias && !root_hit && !alias_hit;
        wire write_entry = rst_n && advance && valid_step;
        wire [INDEX_W-1:0] table_index = read_inherited ? previous_root : cursor;
        // Prefetch the whole prior-layer word before replacing its first
        // entry. Inherited reads address earlier entries already updated by
        // this layer, so the same bank stores both portions of the raster map.
        assign merge_table_request = {read_previous || read_inherited || write_entry,
            write_entry, 10'(table_index), 10'(selected_root)};
        assign previous_root = new_image ? cursor : INDEX_W'(previous_word[10*cursor_field+:10]);
        assign inherited_root = root_hit ? last_root_origin : last_alias_origin;
        assign table_ready = table_state==Resolve && (!old_alias || root_hit || alias_hit);

        if (TOKENS > 640) begin : invalid_capacity
            initial $fatal(1, "Aggregator merge tables support at most 640 tokens");
        end
        always_ff @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                table_state <= ReadPrevious;
                root_valid <= 0; alias_valid <= 0;
                previous_word <= '0;
                last_root_index <= '0; last_root_origin <= '0;
                last_alias_index <= '0; last_alias_origin <= '0;
            end else if (state==Idle && cfg_valid && cfg_minimum_matches<=HIT_W'(FEATURES) &&
                         (cfg_new_image || has_map)) begin
                table_state <= cfg_new_image ? Resolve : ReadPrevious;
                root_valid <= 0; alias_valid <= 0;
            end else if (state==Run) begin
                case (table_state)
                    ReadPrevious: table_state <= CapturePrevious;
                    CapturePrevious: begin
                        previous_word <= merge_table_word;
                        table_state <= Resolve;
                    end
                    Resolve: begin
                        if (read_inherited) table_state <= CaptureInherited;
                        if (advance && valid_step) begin
                            if (!old_alias) begin
                                root_valid <= 1;
                                last_root_index <= cursor;
                                last_root_origin <= selected_root;
                            end
                            if (!new_image && cursor_field==7) table_state <= ReadPrevious;
                        end
                    end
                    CaptureInherited: begin
                        alias_valid <= 1;
                        last_alias_index <= previous_root;
                        last_alias_origin <= INDEX_W'(merge_table_word[10*parent_field+:10]);
                        table_state <= Resolve;
                    end
                    default: table_state <= ReadPrevious;
                endcase
            end
        end
    end else begin : local_table
        logic [INDEX_W-1:0] origins[TOKENS];
        assign previous_root = new_image ? cursor : origins[cursor];
        assign inherited_root = origins[previous_root];
        assign merge_table_request = '0;
        assign table_ready = 1;
        always_ff @(posedge clk) if (rst_n && advance && valid_step) origins[cursor] <= selected_root;
    end
    assign upper_slot = frontier[column];
    assign has_left = column!=0;
    assign left_slot = has_left ? frontier[column-1'b1] : '0;
    assign upper_match = has_upper && (reuse_left_sign ? left_match : sum_shards[SUM_LEVELS].upper[0]>=threshold);
    assign left_match = has_left && sum_shards[SUM_LEVELS].left[0]>=threshold;
    assign sign_ready = state==Run && space && table_ready && read_available && !old_alias;
    assign advance = state==Run && space && table_ready && read_available && (old_alias || sign_valid);
    assign write_sign = rst_n && advance && valid_step && store_sign;
    assign load_left_from_memory = rst_n && advance && valid_step && !store_sign &&
                                   (old_alias || upper_match) && !reuse_left_sign;

    if (COMPILED_SIGN_BANK) begin : compiled_signs
        logic read_valid;
        wire needs_read = (old_alias || has_upper) && !reuse_left_sign;
        assign issue_read = rst_n && state==Run && table_ready && needs_read && !read_valid;

        if (IMAGE_WIDTH > 32) begin : invalid_depth
            initial $fatal(1, "Compiled sign bank supports at most 32 columns");
        end

        // The memory holds its read output while disabled. Until this cursor
        // advances, its prefetched word remains valid through any input stall.
        assign reuse_left_sign = has_left && bank_read_slot==left_slot;
        assign read_available = !needs_read || read_valid;
        always_ff @(posedge clk or negedge rst_n) begin
            if (!rst_n) read_valid <= 0;
            else if (advance) read_valid <= 0;
            else if (issue_read) read_valid <= 1;
        end

    end else begin : inferred_signs
        assign issue_read = 0;
        assign reuse_left_sign = 0;
        assign read_available = 1;
    end

    // Control packs the read and write addresses followed by the read, write,
    // and left-cache-update enables. Scores return as {upper, left} per shard.
    assign merge_sign_control = AGGREGATOR_SIGN_BANK ?
        {bank_read_slot, selected_slot, issue_read, write_sign, load_left_from_memory} : '0;

    // For the full 2048-feature path the sixteen physical slices are grouped
    // as four, three, three, three, three. No padding bits enter the score.
    for (genvar group=0;group<SHARDS;group++) begin : similarity_shards
        localparam int BANK_START=group*BASE_BANKS+(group<EXTRA_BANKS ? group : EXTRA_BANKS);
        localparam int GROUP_BANKS=BASE_BANKS+(group<EXTRA_BANKS ? 1 : 0);
        localparam int FIRST=BANK_START*BANK_W;
        localparam int WIDTH=(FIRST+GROUP_BANKS*BANK_W>FEATURES) ? FEATURES-FIRST : GROUP_BANKS*BANK_W;
        localparam int LOCAL_HIT_W=$clog2(WIDTH+1);
        wire [LOCAL_HIT_W-1:0] upper_hits, left_hits;
        if (AGGREGATOR_SIGN_BANK) begin : remote_bank
            assign {upper_partial[group], left_partial[group]} = merge_sign_counts[group*2*HIT_W+:2*HIT_W];
        end else begin : local_bank
            tri_oracle_token_similarity_shard446 #(
                .FEATURES(WIDTH), .IMAGE_WIDTH(IMAGE_WIDTH), .SLOT_W(SLOT_W),
                .COMPILED_SIGN_BANK(COMPILED_SIGN_BANK)
            ) shard (
                .clk, .sign_data(sign_data[FIRST+:WIDTH]), .read_slot(bank_read_slot),
                .write_slot(selected_slot), .read_enable(issue_read), .write_enable(write_sign),
                .load_left_from_memory, .upper_hits, .left_hits
            );
            assign upper_partial[group]=HIT_W'(upper_hits);
            assign left_partial[group]=HIT_W'(left_hits);
        end
    end

    for (genvar level=0;level<=SUM_LEVELS;level++) begin : sum_shards
        localparam int NODES=SUM_LEAVES>>level;
        wire [HIT_W-1:0] upper[NODES], left[NODES];
        for (genvar node=0;node<NODES;node++) begin : counts
            if (level!=0) begin : sum
                assign upper[node]=sum_shards[level-1].upper[2*node]+sum_shards[level-1].upper[2*node+1];
                assign left[node]=sum_shards[level-1].left[2*node]+sum_shards[level-1].left[2*node+1];
            end else if (node<SHARDS) begin : partial
                assign upper[node]=upper_partial[node];
                assign left[node]=left_partial[node];
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
                        if (store_sign) bank_root[selected_slot]<=cursor;
                        // The next column sees this step's chosen sign as its left
                        // neighbor. A left match keeps the prior cached sign.
                        frontier[column]<=selected_slot;
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

// Each shard keeps its surviving signs and both comparisons local. Only the
// match counts cross the shard boundary.
module tri_oracle_token_similarity_shard446 #(
    parameter int FEATURES=512,
    parameter int IMAGE_WIDTH=24,
    parameter int SLOT_W=5,
    parameter bit COMPILED_SIGN_BANK=0,
    parameter bit COMPACT_SIGN_DEPTH=0,
    localparam int HIT_W=$clog2(FEATURES+1)
) (
    input logic clk,
    input logic [FEATURES-1:0] sign_data,
    input logic [SLOT_W-1:0] read_slot, write_slot,
    input logic read_enable, write_enable, load_left_from_memory,
    output logic [HIT_W-1:0] upper_hits, left_hits
);
    localparam int LEVELS=$clog2(FEATURES);
    localparam int LEAVES=1<<LEVELS;
    logic [FEATURES-1:0] memory_sign, left_sign;

    if (COMPILED_SIGN_BANK) begin : compiled
        localparam int BANKS=(FEATURES+127)/128;
        localparam int DATA_W=128*BANKS;
        wire [4:0] address = write_enable ? 5'(write_slot) : 5'(read_slot);
        wire [DATA_W-1:0] read_data;
        if (COMPACT_SIGN_DEPTH) begin : compact
            if (IMAGE_WIDTH!=24) begin : invalid_geometry
                initial $fatal(1, "Compact sign storage requires a 24-column image");
            end
            TS5N28HPCPSVTA24X128M2FW slices[BANKS-1:0] (
                .CLK(clk), .CEB(!(read_enable || write_enable)), .WEB(!write_enable),
                .A(address), .D(DATA_W'(sign_data)), .BWEB(128'b0), .Q(read_data)
            );
        end else begin : standard
            TS5N28HPCPSVTA32X128M2FW slices[BANKS-1:0] (
                .CLK(clk), .CEB(!(read_enable || write_enable)), .WEB(!write_enable),
                .A(address), .D(DATA_W'(sign_data)), .BWEB(128'b0), .Q(read_data)
            );
        end
        assign memory_sign = read_data[FEATURES-1:0];
    end else begin : inferred
        logic [FEATURES-1:0] bank_sign[IMAGE_WIDTH];
        assign memory_sign = bank_sign[read_slot];
        always_ff @(posedge clk) if (write_enable) bank_sign[write_slot] <= sign_data;
    end

    always_ff @(posedge clk) begin
        if (write_enable) left_sign <= sign_data;
        else if (load_left_from_memory) left_sign <= memory_sign;
    end

    for (genvar level=0;level<=LEVELS;level++) begin : reduction
        localparam int NODES=LEAVES>>level;
        localparam int COUNT_W=level+1;
        wire [COUNT_W-1:0] upper[NODES], left[NODES];
        for (genvar node=0;node<NODES;node++) begin : counts
            if (level!=0) begin : sum
                assign upper[node]=COUNT_W'(reduction[level-1].upper[2*node])+
                                   COUNT_W'(reduction[level-1].upper[2*node+1]);
                assign left[node]=COUNT_W'(reduction[level-1].left[2*node])+
                                  COUNT_W'(reduction[level-1].left[2*node+1]);
            end else if (node<FEATURES) begin : compare
                assign upper[node]=sign_data[node]==memory_sign[node];
                assign left[node]=sign_data[node]==left_sign[node];
            end else begin : padding
                assign upper[node]='0;
                assign left[node]='0;
            end
        end
    end
    assign upper_hits=HIT_W'(reduction[LEVELS].upper[0]);
    assign left_hits=HIT_W'(reduction[LEVELS].left[0]);
endmodule

// Four clusters own 128 entries and the final cluster owns the
// remaining 64. Each compiled word holds eight origins.
module tri_oracle_token_merge_table454 #(
    parameter bit COMPILED=1,
    parameter int ENTRIES=128,
    localparam int ADDRESS_W=$clog2(ENTRIES)
) (
    input logic clk,
    input logic [18:0] request,
    output logic [79:0] word
);
    wire active, write_entry;
    wire [6:0] address;
    wire [9:0] value;
    assign {active, write_entry, address, value} = request;
    if (ENTRIES!=128 && ENTRIES!=64) begin : invalid_geometry
        initial $fatal(1, "Origin tables support 64 or 128 entries");
    end
    if (COMPILED) begin : compiled
        wire [79:0] mask;
        for (genvar field=0;field<8;field++) begin : fields
            assign mask[10*field+:10]={10{address[2:0]!=3'(field)}};
        end
        if (ENTRIES==128) begin : full
            TS5N28HPCPSVTA16X80M2FW entries (
                .CLK(clk), .CEB(!active), .WEB(!write_entry), .A(address[6:3]),
                .D({8{value}}), .BWEB(mask), .Q(word)
            );
        end else begin : tail
            TS5N28HPCPSVTA8X80M2FW entries (
                .CLK(clk), .CEB(!active), .WEB(!write_entry), .A(address[5:3]),
                .D({8{value}}), .BWEB(mask), .Q(word)
            );
        end
    end else begin : inferred
        logic [9:0] entries[ENTRIES];
        always_ff @(posedge clk) if (active) begin
            if (write_entry) entries[ADDRESS_W'(address)] <= value;
            else for (int field=0;field<8;field++) begin
                word[10*field+:10] <= entries[{address[ADDRESS_W-1:3],3'(field)}];
            end
        end
    end
endmodule

// Cluster-side adapter for a 24-column surviving-sign bank.
module tri_oracle_aggregator_sign447 #(
    parameter int FEATURES=512,
    parameter bit COMPILED_SIGN_BANK=1,
    parameter bit COMPACT_SIGN_DEPTH=0,
    localparam int HIT_W=$clog2(FEATURES+1)
) (
    input logic clk,
    input logic [FEATURES-1:0] sign_data,
    input logic [12:0] control,
    output logic [23:0] counts
);
    wire [HIT_W-1:0] upper_hits, left_hits;
    tri_oracle_token_similarity_shard446 #(
        .FEATURES(FEATURES), .IMAGE_WIDTH(24), .SLOT_W(5),
        .COMPILED_SIGN_BANK(COMPILED_SIGN_BANK), .COMPACT_SIGN_DEPTH(COMPACT_SIGN_DEPTH)
    ) shard (
        .clk, .sign_data, .read_slot(control[12:8]), .write_slot(control[7:3]),
        .read_enable(control[2]), .write_enable(control[1]), .load_left_from_memory(control[0]),
        .upper_hits, .left_hits
    );
    assign counts = {12'(upper_hits), 12'(left_hits)};
endmodule
/* verilator lint_on DECLFILENAME */
