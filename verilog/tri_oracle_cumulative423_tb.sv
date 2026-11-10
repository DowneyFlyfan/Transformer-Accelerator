`timescale 1ns/1ps
module tri_oracle_cumulative423_tb #(parameter int FIRST_MODE=0, MODES=2);
    localparam int TOKENS=576, FEATURES=2048, LAYERS=22;
    logic clk=0, rst_n=0;
    always #5 clk=~clk;
    logic cfg_valid=0, cfg_new_image=0, sign_valid=0, done_ready=0;
    logic [11:0] cfg_minimum_matches;
    logic [FEATURES-1:0] sign_data;
    wire cfg_ready, sign_ready, map_valid, map_ready, map_last, done_valid, done_error;
    wire [9:0] map_index, map_origin;
    logic frame_valid=0, query_valid=0, row_ready=0;
    logic [9:0] query_position;
    wire frame_ready, causal_map_ready, query_ready, row_valid, row_last, error;
    wire [9:0] row_origin, row_count;
    logic [FEATURES-1:0] signs[LAYERS*TOKENS];
    logic [9:0] golden[LAYERS*TOKENS];
    int row_sizes[TOKENS];
    int mode_id, layer_id, frame_maps, frame_signs, tick=0;
    int checked_maps=0, checked_signs=0, checked_rows=0, checked_sizes=0, map_stalls=0, done_stalls=0, cfg_errors=0;
    bit valid_frame=0, blocked=0;
    logic [20:0] held;
    logic [1:0] last_hold=0;
    wire permit=tick%7!=0 && (!map_last || last_hold==3);
    string fixture;

    tri_oracle_cumulative_token_merger423 merger (.*);
    assign map_ready=permit && causal_map_ready;
    tri_oracle_causal_token_size #(.MAX_TOKENS(TOKENS)) causal (
        .clk,.rst_n,.frame_valid,.frame_ready,.map_valid(map_valid && permit),.map_ready(causal_map_ready),
        .map_origin,.map_last,.query_valid,.query_ready,.query_position,
        .out_valid(row_valid),.out_ready(row_ready),.out_origin(row_origin),.out_count(row_count),.out_last(row_last),.error
    );

    always @(posedge clk) if (rst_n) begin
        tick<=tick+1;
        if (error) $fatal(1,"BATCH423_CAUSAL_ERROR mode=%0d layer=%0d",mode_id,layer_id);
        if (done_valid && done_error && valid_frame)
            $fatal(1,"BATCH423_UNEXPECTED_DONE mode=%0d layer=%0d maps=%0d",mode_id,layer_id,frame_maps);
        if (blocked && (!map_valid || {map_index,map_origin,map_last}!==held))
            $fatal(1,"BATCH423_MAP_NOT_STABLE");
        blocked<=map_valid && !map_ready;
        if (map_valid && !map_ready) begin
            map_stalls++;
            held<={map_index,map_origin,map_last};
            if (map_last) begin
                if (done_valid) $fatal(1,"BATCH423_DONE_BEFORE_LAST_ACCEPTED");
                if (last_hold!=3) last_hold<=last_hold+1'b1;
            end
        end
        if (map_valid && map_ready) begin
            if (!valid_frame || frame_maps>=TOKENS || map_index!==10'(frame_maps) ||
                map_origin!==golden[layer_id*TOKENS+frame_maps] || map_last!==(frame_maps==TOKENS-1))
                $fatal(1,"BATCH423_WRONG_MAP mode=%0d layer=%0d token=%0d got=%0d expected=%0d",
                       mode_id,layer_id,frame_maps,map_origin,golden[layer_id*TOKENS+frame_maps]);
            frame_maps++;
            checked_maps++;
        end
        if (sign_valid && sign_ready) begin
            frame_signs++;
            checked_signs++;
        end
    end

    task automatic configure(input bit fresh, input int threshold, input bit valid_expected);
        @(negedge clk);
        cfg_valid=1; cfg_new_image=fresh; cfg_minimum_matches=12'(threshold);
        valid_frame=valid_expected; frame_valid=valid_expected;
        last_hold=0; frame_maps=0; frame_signs=0;
        @(posedge clk);
        if (!cfg_ready || (valid_expected && !frame_ready)) $fatal(1,"BATCH423_CONFIG_NOT_READY");
        @(negedge clk);
        cfg_valid=0; frame_valid=0; cfg_new_image='x; cfg_minimum_matches='x;
    endtask

    task automatic finish_frame(input bit expected_error, input int signs_expected);
        while (!done_valid) @(negedge clk);
        repeat (5) begin
            if (!done_valid || done_error!==expected_error || cfg_ready || sign_ready || map_valid ||
                frame_maps!=(expected_error ? 0 : TOKENS) || frame_signs!=signs_expected)
                $fatal(1,"BATCH423_WRONG_COMPLETION error=%b maps=%0d signs=%0d",done_error,frame_maps,frame_signs);
            done_stalls++;
            @(negedge clk);
        end
        cfg_errors+=int'(expected_error);
        done_ready=1;
        @(negedge clk);
        done_ready=0;
    endtask

    task automatic check_row(input int position);
        int expected_origin, expected_words, received, total, origin;
        foreach (row_sizes[index]) row_sizes[index]=0;
        expected_words=0;
        for (int token=0;token<=position;token++) begin
            origin=int'(golden[layer_id*TOKENS+token]);
            if (row_sizes[origin]==0) expected_words++;
            row_sizes[origin]++;
        end
        @(negedge clk);
        query_valid=1; query_position=10'(position);
        @(posedge clk);
        if (!query_ready) $fatal(1,"BATCH423_QUERY_NOT_READY");
        @(negedge clk);
        query_valid=0; query_position='x;
        expected_origin=0; received=0; total=0;
        while (received<expected_words) begin
            row_ready=tick%5!=0;
            @(posedge clk);
            if (row_valid && row_ready) begin
                while (expected_origin<TOKENS && row_sizes[expected_origin]==0) expected_origin++;
                if (expected_origin>=TOKENS || row_origin!==10'(expected_origin) ||
                    row_count!==10'(row_sizes[expected_origin]) || row_last!==(received+1==expected_words))
                    $fatal(1,"BATCH423_PREFIX_MISMATCH mode=%0d layer=%0d query=%0d",mode_id,layer_id,position);
                expected_origin++;
                received++;
                checked_sizes++;
                total+=int'(row_count);
            end
            @(negedge clk);
        end
        row_ready=0;
        if (total!=position+1 || !query_ready) $fatal(1,"BATCH423_PREFIX_TOTAL");
        checked_rows++;
    endtask

    task automatic check_layer(input int layer);
        int needed;
        layer_id=layer;
        configure(layer==0,1536,1);
        needed=0;
        for (int position=0;position<TOKENS;position++) begin
            if (layer==0 || golden[(layer-1)*TOKENS+position]==10'(position)) begin
                sign_valid=1; sign_data=signs[layer*TOKENS+position];
                do @(posedge clk); while (!sign_ready);
                @(negedge clk);
                sign_valid=0; sign_data='x;
                needed++;
            end
        end
        finish_frame(0,needed);
        for (int position=0;position<TOKENS;position++) check_row(position);
        check_row(23); check_row(575);
    endtask

    initial begin
        if (!$value$plusargs("FIXTURE=%s",fixture)) $fatal(1,"BATCH423_FIXTURE_REQUIRED");
        repeat (3) @(negedge clk);
        rst_n=1;
        configure(0,1536,0);
        finish_frame(1,0);
        for (int mode=FIRST_MODE;mode<FIRST_MODE+MODES;mode++) begin
            mode_id=mode;
            $readmemh($sformatf("%s/signs_%0d.hex",fixture,mode),signs);
            $readmemh($sformatf("%s/map_%0d.hex",fixture,mode),golden);
            for (int layer=0;layer<LAYERS;layer++) begin
                check_layer(layer);
                if (layer==0) begin
                    configure(0,2049,0);
                    finish_frame(1,0);
                end
            end
        end
        if (checked_maps!=MODES*LAYERS*TOKENS || checked_rows!=MODES*LAYERS*(TOKENS+2) ||
            checked_signs>=checked_maps || map_stalls==0 || cfg_errors!=MODES+1)
            $fatal(1,"BATCH423_FINAL_INVENTORY");
        $display("BATCH423_PASS modes=%0d layers=%0d maps=%0d signs=%0d rows=%0d sizes=%0d cfg_errors=%0d map_stalls=%0d done_stalls=%0d",
                 MODES,MODES*LAYERS,checked_maps,checked_signs,checked_rows,checked_sizes,cfg_errors,map_stalls,done_stalls);
        $finish;
    end
    initial begin #120000000; $fatal(1,"BATCH423_WATCHDOG"); end
endmodule
