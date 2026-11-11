`timescale 1ns/1ps
package tri_oracle_token_size_types;
    typedef struct packed {
        logic begin_frame, begin_query;
        logic [9:0] query_position;
        logic accept_map;
        logic [9:0] map_position, map_origin;
        logic [18:0] table_request;
        logic walking, advance, apply_step;
        logic [9:0] lookup_origin;
        logic subtract, emit_advance;
    } bank_command_t;

    typedef struct packed {
        logic [79:0] table_word;
        logic done, read_issued, step_valid;
        logic [9:0] step_origin, step_position;
        logic step_subtract, root_known, emit_valid, emit_last;
        logic [9:0] out_origin, out_count;
    } bank_result_t;
endpackage

// Causal token sizes from the five in-place merge tables. Each aggregator owns
// its cursor, root locations, and counts. A cross-bank alias updates the bank
// holding its surviving token, with one update committed per cycle.
module tri_oracle_token_size_control (
    input logic clk, rst_n,
    input logic frame_valid,
    output logic frame_ready,
    input logic map_valid,
    output logic map_ready,
    input logic [9:0] map_origin,
    input logic map_last,
    input logic query_valid,
    output logic query_ready,
    input logic [9:0] query_position,
    output logic out_valid,
    input logic out_ready,
    output logic [9:0] out_origin, out_count,
    output logic out_last, error,
    input logic [21:0] table_request,
    output logic [79:0] table_word,
    output tri_oracle_token_size_types::bank_command_t [4:0] bank_command,
    input tri_oracle_token_size_types::bank_result_t [4:0] bank_result
);
    localparam int TOKENS=576, BANKS=5;
    typedef enum logic [1:0] {Idle, Load, Walk, Emit} state_t;
    state_t state;
    logic loaded;
    logic [9:0] mapped_tokens;
    logic [2:0] external_read_bank, step_bank, emit_bank;
    logic [BANKS-1:0] bank_done, step_valid, read_issued;
    logic [BANKS-1:0] root_known, emit_valid, emit_last;
    logic [BANKS-1:0][9:0] bank_step_origin, bank_step_position, bank_out_origin, bank_out_count;
    logic [BANKS-1:0] bank_step_subtract;
    logic [BANKS-1:0][79:0] external_words;
    logic [9:0] lookup_origin, step_origin, step_position;
    logic step_available, step_subtract, apply_step, bad_step;
    logic bad_map, accept_map, begin_frame, begin_query, allow_external;
    logic [2:0] request_bank;

    assign frame_ready=state==Idle;
    assign map_ready=state==Load;
    assign query_ready=state==Idle && loaded && !error && !frame_valid;
    assign begin_frame=frame_valid && frame_ready;
    assign begin_query=query_valid && query_ready && query_position<mapped_tokens;
    assign allow_external=state==Idle || state==Load;
    assign request_bank=table_request[19:17];
    assign table_word=external_read_bank<3'(BANKS) ? external_words[external_read_bank] : '0;
    assign lookup_origin=state==Load ? map_origin : step_origin;
    assign bad_map=map_origin>mapped_tokens || (map_origin<mapped_tokens && !(|root_known)) ||
                   (mapped_tokens==10'(TOKENS-1) && !map_last);
    assign accept_map=map_valid && map_ready && !bad_map;
    assign bad_step=step_available && (step_origin>step_position || !(|root_known));
    assign apply_step=state==Walk && step_available && !bad_step && !table_request[21];

    always_comb begin
        step_bank='0;
        emit_bank='0;
        for (int bank=BANKS-1;bank>=0;bank--) begin
            if (step_valid[bank]) step_bank=3'(bank);
            if (emit_valid[bank]) emit_bank=3'(bank);
        end
    end
    assign step_available=|step_valid;
    assign step_origin=bank_step_origin[step_bank];
    assign step_position=bank_step_position[step_bank];
    assign step_subtract=bank_step_subtract[step_bank];
    assign out_valid=state==Emit && |emit_valid && bank_out_count[emit_bank]!=0;
    assign out_origin=out_valid ? bank_out_origin[emit_bank] : '0;
    assign out_count=out_valid ? bank_out_count[emit_bank] : '0;
    assign out_last=out_valid && emit_last[emit_bank] &&
                    (emit_valid & ~(5'b1 << emit_bank))=='0;

    for (genvar bank=0;bank<BANKS;bank++) begin : route
        tri_oracle_token_size_types::bank_command_t command;
        tri_oracle_token_size_types::bank_result_t result;
        assign bank_command[bank]=command;
        assign result=bank_result[bank];
        assign command.begin_frame=begin_frame;
        assign command.begin_query=begin_query;
        assign command.query_position=query_position;
        assign command.accept_map=accept_map;
        assign command.map_position=mapped_tokens;
        assign command.map_origin=map_origin;
        assign command.table_request={allow_external && table_request[21] && request_bank==3'(bank),
                                      table_request[20], table_request[16:0]};
        assign command.walking=state==Walk;
        assign command.advance=apply_step && step_bank==3'(bank);
        assign command.apply_step=apply_step;
        assign command.lookup_origin=lookup_origin;
        assign command.subtract=step_subtract;
        assign command.emit_advance=out_valid && out_ready && emit_bank==3'(bank);
        assign external_words[bank]=result.table_word;
        assign bank_done[bank]=result.done;
        assign read_issued[bank]=result.read_issued;
        assign step_valid[bank]=result.step_valid;
        assign bank_step_origin[bank]=result.step_origin;
        assign bank_step_position[bank]=result.step_position;
        assign bank_step_subtract[bank]=result.step_subtract;
        assign root_known[bank]=result.root_known;
        assign emit_valid[bank]=result.emit_valid;
        assign emit_last[bank]=result.emit_last;
        assign bank_out_origin[bank]=result.out_origin;
        assign bank_out_count[bank]=result.out_count;
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=Idle;
            loaded<=0;
            error<=0;
            mapped_tokens<='0;
            external_read_bank<='0;
        end else begin
            if (allow_external && table_request[21] && !table_request[20])
                external_read_bank<=request_bank;
            if (table_request[21] && (!allow_external || request_bank>=3'(BANKS))) begin
                state<=Idle;
                loaded<=0;
                error<=1;
            end else case (state)
                Idle: if (begin_frame) begin
                    state<=Load;
                    loaded<=0;
                    error<=0;
                    mapped_tokens<='0;
                end else if (query_valid && query_ready) begin
                    if (begin_query) state<=Walk;
                    else begin
                        loaded<=0;
                        error<=1;
                    end
                end
                Load: if (map_valid) begin
                    if (bad_map) begin
                        state<=Idle;
                        loaded<=0;
                        error<=1;
                    end else begin
                        mapped_tokens<=mapped_tokens+1'b1;
                        if (map_last) begin
                            loaded<=1;
                            state<=Idle;
                        end
                    end
                end
                Walk: if (bad_step) begin
                    state<=Idle;
                    loaded<=0;
                    error<=1;
                end else if (&bank_done) state<=Emit;
                Emit: if (!out_valid) begin
                    state<=Idle;
                    loaded<=0;
                    error<=1;
                end else if (out_ready && out_last) state<=Idle;
                default: begin
                    state<=Idle;
                    loaded<=0;
                    error<=1;
                end
            endcase
        end
    end
endmodule

module tri_oracle_token_size_bank #(
    parameter int BANK_START=0, ENTRIES=128,
    parameter bit COMPILED_TABLE=1
) (
    input logic clk, rst_n,
    input tri_oracle_token_size_types::bank_command_t command,
    output tri_oracle_token_size_types::bank_result_t result
);
    tri_oracle_aggregator_token_sizes #(
        .BANK_START(BANK_START), .ENTRIES(ENTRIES), .COMPILED_TABLE(COMPILED_TABLE)
    ) local_sizes (
        .clk, .rst_n, .begin_frame(command.begin_frame), .begin_query(command.begin_query),
        .query_position(command.query_position), .accept_map(command.accept_map),
        .map_position(command.map_position), .map_origin(command.map_origin),
        .external_request(command.table_request), .external_word(result.table_word),
        .walking(command.walking), .done(result.done), .read_issued(result.read_issued),
        .step_valid(result.step_valid), .step_origin(result.step_origin),
        .step_position(result.step_position), .step_subtract(result.step_subtract),
        .advance(command.advance), .apply_step(command.apply_step), .lookup_origin(command.lookup_origin),
        .subtract(command.subtract), .root_known(result.root_known),
        .emit_valid(result.emit_valid), .emit_last(result.emit_last),
        .out_origin(result.out_origin), .out_count(result.out_count), .emit_advance(command.emit_advance)
    );
endmodule

module tri_oracle_aggregator_token_sizes #(
    parameter int BANK_START=0, ENTRIES=128,
    parameter bit COMPILED_TABLE=1,
    localparam int ADDRESS_WIDTH=$clog2(ENTRIES)
) (
    input logic clk, rst_n, begin_frame, begin_query,
    input logic [9:0] query_position,
    input logic accept_map,
    input logic [9:0] map_position, map_origin,
    input logic [18:0] external_request,
    output logic [79:0] external_word,
    input logic walking,
    output logic done, read_issued, step_valid,
    output logic [9:0] step_origin, step_position,
    output logic step_subtract,
    input logic advance, apply_step,
    input logic [9:0] lookup_origin,
    input logic subtract,
    output logic root_known,
    output logic emit_valid, emit_last,
    output logic [9:0] out_origin, out_count,
    input logic emit_advance
);
    localparam logic [9:0] START=10'(BANK_START), LIMIT=10'(BANK_START+ENTRIES);
    logic [ENTRIES-1:0] roots;
    logic [ADDRESS_WIDTH-1:0] origin_location[ENTRIES], location_origin[ENTRIES];
    logic [9:0] location_count[ENTRIES];
    logic [ADDRESS_WIDTH:0] root_count, cursor, target_end, emit_slot, next_slot;
    logic [ADDRESS_WIDTH-1:0] offset, map_offset, lookup_offset, current_slot;
    logic cached, pending, cache_hit;
    logic [6:0] cached_word_address, word_address;
    logic [79:0] cached_word;
    logic [18:0] request;

    assign step_subtract=cursor>target_end;
    assign done=cursor==target_end;
    assign offset=ADDRESS_WIDTH'(step_subtract ? cursor-1'b1 : cursor);
    assign word_address=7'(offset) & 7'h78;
    assign cache_hit=cached && !pending && cached_word_address==word_address;
    assign read_issued=walking && !done && !cache_hit && !pending;
    assign request=read_issued ? {2'b10,word_address,10'd0} : external_request;
    assign step_valid=walking && !done && cache_hit;
    assign step_origin=cached_word[10*int'(offset[2:0])+:10];
    assign step_position=START+10'(offset);
    assign map_offset=ADDRESS_WIDTH'(map_position);
    assign lookup_offset=ADDRESS_WIDTH'(lookup_origin);
    assign root_known=lookup_origin>=START && lookup_origin<LIMIT && roots[lookup_offset];
    assign current_slot=origin_location[lookup_offset];
    assign next_slot=emit_slot+1'b1;
    assign emit_valid=emit_slot<root_count && {1'b0,location_origin[ADDRESS_WIDTH'(emit_slot)]}<target_end;
    assign emit_last=next_slot>=root_count || {1'b0,location_origin[ADDRESS_WIDTH'(next_slot)]}>=target_end;
    assign out_origin=START+10'(location_origin[ADDRESS_WIDTH'(emit_slot)]);
    assign out_count=location_count[ADDRESS_WIDTH'(emit_slot)];

    tri_oracle_token_merge_table454 #(.COMPILED(COMPILED_TABLE), .ENTRIES(ENTRIES)) table_bank (
        .clk, .request, .word(external_word)
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            root_count<='0;
            cursor<='0;
            target_end<='0;
            emit_slot<='0;
            cached<=0;
            pending<=0;
            cached_word_address<='0;
            cached_word<='0;
        end else if (begin_frame) begin
            root_count<='0;
            cursor<='0;
            target_end<='0;
            emit_slot<='0;
            cached<=0;
            pending<=0;
        end else begin
            if (accept_map && map_position>=START && map_position<LIMIT && map_origin==map_position)
                root_count<=root_count+1'b1;
            if (begin_query) begin
                if (query_position<START) target_end<='0;
                else if (query_position>=LIMIT) target_end<=(ADDRESS_WIDTH+1)'(ENTRIES);
                else target_end<=(ADDRESS_WIDTH+1)'(query_position-START)+1'b1;
                emit_slot<='0;
            end else if (emit_advance) emit_slot<=next_slot;
            if (read_issued) begin
                cached_word_address<=word_address;
                pending<=1;
            end else if (pending) begin
                cached_word<=external_word;
                cached<=1;
                pending<=0;
            end else if (external_request[18] && external_request[17]) begin
                cached<=0;
            end
            if (advance) cursor<=step_subtract ? cursor-1'b1 : cursor+1'b1;
        end
    end

    // Only mapped roots are read. Initializing each new root avoids a reset
    // across the location and count storage.
    always_ff @(posedge clk) begin
        if (accept_map && map_position>=START && map_position<LIMIT) begin
            roots[map_offset]<=map_origin==map_position;
            if (map_origin==map_position) begin
                origin_location[map_offset]<=ADDRESS_WIDTH'(root_count);
                location_origin[ADDRESS_WIDTH'(root_count)]<=map_offset;
                location_count[ADDRESS_WIDTH'(root_count)]<='0;
            end
        end else if (apply_step && root_known) begin
            location_count[current_slot]<=subtract ? location_count[current_slot]-1'b1
                                                   : location_count[current_slot]+1'b1;
        end
    end
endmodule

module tri_oracle_cluster_token_sizes #(
    parameter bit COMPILED_TABLES=1
) (
    input logic clk, rst_n,
    input logic frame_valid,
    output logic frame_ready,
    input logic map_valid,
    output logic map_ready,
    input logic [9:0] map_origin,
    input logic map_last,
    input logic query_valid,
    output logic query_ready,
    input logic [9:0] query_position,
    output logic out_valid,
    input logic out_ready,
    output logic [9:0] out_origin, out_count,
    output logic out_last, error,
    input logic [21:0] table_request,
    output logic [79:0] table_word
);
    tri_oracle_token_size_types::bank_command_t [4:0] bank_command;
    tri_oracle_token_size_types::bank_result_t [4:0] bank_result;
    tri_oracle_token_size_control controller (
        .clk, .rst_n, .frame_valid, .frame_ready, .map_valid, .map_ready, .map_origin, .map_last,
        .query_valid, .query_ready, .query_position, .out_valid, .out_ready, .out_origin, .out_count,
        .out_last, .error, .table_request, .table_word, .bank_command, .bank_result
    );
    for (genvar bank=0; bank<5; bank++) begin : local_bank
        tri_oracle_token_size_bank #(
            .BANK_START(bank*128), .ENTRIES(bank==4 ? 64 : 128), .COMPILED_TABLE(COMPILED_TABLES)
        ) unit (.clk, .rst_n, .command(bank_command[bank]), .result(bank_result[bank]));
    end
endmodule
