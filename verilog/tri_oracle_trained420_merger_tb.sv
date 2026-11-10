`timescale 1ns/1ps
module tri_oracle_trained420_merger_tb #(
    parameter int FIRST_LAYER=0, LAYERS=22, THRESHOLD=1536
);
    localparam int GRID=24, TOKENS=576, FEATURES=2048, TOTAL_LAYERS=22;
    logic clk=0, rst_n=0;
    always #5 clk=~clk;
    logic in_valid=0, frame_valid=0, query_valid=0;
    logic [FEATURES-1:0] in_sign;
    logic [9:0] query_position;
    wire in_ready, frame_ready, map_valid, map_ready, query_ready;
    wire [9:0] map_index, map_origin;
    wire [1:0] map_kind;
    wire global_valid, global_done, row_valid, row_last, error;
    wire [9:0] global_origin, global_count, row_origin, row_count;
    logic row_ready=0;
    int tick=0;
    wire global_ready=tick%7!=0;
    logic [FEATURES-1:0] signs[TOTAL_LAYERS*TOKENS];
    logic [11:0] expected_map[TOTAL_LAYERS*TOKENS];
    int full_sizes[TOKENS], row_sizes[TOKENS];
    int active_layer, current_map, current_global, global_cursor;
    int maps_checked=0, left_merges=0, up_merges=0, global_checked=0, rows_checked=0, sizes_checked=0, stalls=0;
    bit row_blocked=0, global_blocked=0;
    logic [20:0] held_row;
    logic [19:0] held_global;
    string fixture;

    tri_oracle_token_merger #(.IMG_W(GRID),.IMG_H(GRID),.SIGN_W(FEATURES),.MATCH_THRESHOLD(THRESHOLD)) merger (
        .clk,.rst_n,.in_valid,.in_ready,.in_sign,
        .out_valid(map_valid),.out_ready(map_ready),.out_index(map_index),.out_origin(map_origin),.out_merge(map_kind),
        .size_valid(global_valid),.size_ready(global_ready),.size_origin(global_origin),.size_count(global_count),.done(global_done)
    );
    tri_oracle_causal_token_size #(.MAX_TOKENS(TOKENS)) causal (
        .clk,.rst_n,.frame_valid,.frame_ready,.map_valid,.map_ready,.map_origin,.map_last(map_index==TOKENS-1),
        .query_valid,.query_ready,.query_position,.out_valid(row_valid),.out_ready(row_ready),
        .out_origin(row_origin),.out_count(row_count),.out_last(row_last),.error
    );

    always @(posedge clk) if (rst_n) begin
        tick<=tick+1;
        if (error) $fatal(1,"BATCH420_CAUSAL_PROTOCOL layer=%0d",active_layer);
        if (map_valid && map_ready) begin
            if (current_map>=TOKENS || map_index!==10'(current_map) ||
                {map_kind,map_origin}!==expected_map[active_layer*TOKENS+current_map])
                $fatal(1,"BATCH420_WRONG_MAP layer=%0d token=%0d got=%03h expected=%03h",
                       active_layer,current_map,{map_kind,map_origin},expected_map[active_layer*TOKENS+current_map]);
            current_map++;
            maps_checked++;
            left_merges+=int'(map_kind==1);
            up_merges+=int'(map_kind==2);
        end
        if (global_blocked && (!global_valid || {global_origin,global_count}!==held_global))
            $fatal(1,"BATCH420_UNSTABLE_GLOBAL_SIZE");
        global_blocked<=global_valid && !global_ready;
        if (global_valid && !global_ready) held_global<={global_origin,global_count};
        if (global_valid && global_ready) begin
            while (global_cursor<TOKENS && full_sizes[global_cursor]==0) global_cursor++;
            if (global_cursor>=TOKENS || global_origin!==10'(global_cursor) || global_count!==10'(full_sizes[global_cursor]))
                $fatal(1,"BATCH420_WRONG_GLOBAL layer=%0d origin=%0d count=%0d",active_layer,global_origin,global_count);
            global_cursor++;
            current_global++;
            global_checked++;
        end
        if (row_blocked && (!row_valid || {row_origin,row_count,row_last}!==held_row))
            $fatal(1,"BATCH420_UNSTABLE_CAUSAL_SIZE");
        row_blocked<=row_valid && !row_ready;
        if (row_valid && !row_ready) begin
            held_row<={row_origin,row_count,row_last};
            stalls++;
        end
    end else begin
        row_blocked<=0;
        global_blocked<=0;
    end

    task automatic check_row(input int position);
        int expected_origin, expected_words, consumed, row_total, origin;
        foreach (row_sizes[index]) row_sizes[index]=0;
        expected_words=0;
        for (int token=0;token<=position;token++) begin
            origin=int'(expected_map[active_layer*TOKENS+token][9:0]);
            if (row_sizes[origin]==0) expected_words++;
            row_sizes[origin]++;
        end
        @(negedge clk);
        query_valid=1; query_position=10'(position);
        @(posedge clk);
        if (!query_ready) $fatal(1,"BATCH420_QUERY_NOT_READY layer=%0d position=%0d",active_layer,position);
        @(negedge clk);
        query_valid=0; query_position='x;
        expected_origin=0; consumed=0; row_total=0;
        while (consumed<expected_words) begin
            row_ready=tick%5!=0;
            @(posedge clk);
            if (row_valid && row_ready) begin
                while (expected_origin<TOKENS && row_sizes[expected_origin]==0) expected_origin++;
                if (expected_origin>=TOKENS || row_origin!==10'(expected_origin) ||
                    row_count!==10'(row_sizes[expected_origin]) || row_last!==(consumed+1==expected_words))
                    $fatal(1,"BATCH420_WRONG_CAUSAL layer=%0d query=%0d origin=%0d count=%0d",
                           active_layer,position,row_origin,row_count);
                consumed++;
                expected_origin++;
                sizes_checked++;
                row_total+=int'(row_count);
            end
            @(negedge clk);
        end
        row_ready=0;
        if (row_total!=position+1 || !query_ready) $fatal(1,"BATCH420_CAUSAL_INVENTORY");
        rows_checked++;
    endtask

    task automatic check_layer(input int layer);
        int roots, origin;
        @(negedge clk);
        rst_n=0;
        active_layer=layer; current_map=0; current_global=0; global_cursor=0;
        foreach (full_sizes[index]) full_sizes[index]=0;
        roots=0;
        for (int token=0;token<TOKENS;token++) begin
            origin=int'(expected_map[layer*TOKENS+token][9:0]);
            full_sizes[origin]++;
            roots+=int'(origin==token);
        end
        repeat (2) @(negedge clk);
        rst_n=1; frame_valid=1;
        @(posedge clk);
        if (!frame_ready) $fatal(1,"BATCH420_FRAME_NOT_READY");
        @(negedge clk);
        frame_valid=0;
        for (int token=0;token<TOKENS;token++) begin
            in_valid=1; in_sign=signs[layer*TOKENS+token];
            do @(posedge clk); while (!in_ready);
            @(negedge clk);
        end
        in_valid=0; in_sign='x;
        while (!global_done) @(negedge clk);
        if (current_map!=TOKENS || current_global!=roots) $fatal(1,"BATCH420_MERGE_INVENTORY");
        for (int position=0;position<TOKENS;position++) check_row(position);
        check_row(288); check_row(0); check_row(575); check_row(23); check_row(575);
    endtask

    initial begin
        if (!$value$plusargs("FIXTURE=%s",fixture)) $fatal(1,"BATCH420_FIXTURE_REQUIRED");
        $readmemh({fixture,"/signs.hex"},signs);
        $readmemh($sformatf("%s/map_%0d.hex",fixture,THRESHOLD),expected_map);
        for (int layer=FIRST_LAYER;layer<FIRST_LAYER+LAYERS;layer++) check_layer(layer);
        if (maps_checked!=LAYERS*TOKENS || rows_checked!=LAYERS*(TOKENS+5) || stalls==0)
            $fatal(1,"BATCH420_FINAL_INVENTORY");
        $display("BATCH420_PASS threshold=%0d first=%0d layers=%0d maps=%0d left=%0d up=%0d global=%0d rows=%0d sizes=%0d stalls=%0d",
                 THRESHOLD,FIRST_LAYER,LAYERS,maps_checked,left_merges,up_merges,global_checked,rows_checked,sizes_checked,stalls);
        $finish;
    end
    initial begin #30000000; $fatal(1,"BATCH420_WATCHDOG"); end
endmodule
