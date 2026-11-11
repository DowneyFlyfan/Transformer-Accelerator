`timescale 1ns/1ps
module tri_oracle_cluster_token_sizes_tb;
    localparam int TOKENS=576, LAYERS=22;
    logic clk=0, rst_n=0;
    always #5 clk=~clk;
    logic frame_valid=0, map_valid=0, map_last=0, query_valid=0, row_ready=0;
    logic [9:0] map_origin, query_position;
    wire frame_ready, map_ready, query_ready, row_valid, row_last, error;
    wire [9:0] row_origin, row_count;
    logic [21:0] table_request='0;
    wire [79:0] table_word;
    logic [9:0] golden[LAYERS*TOKENS], captured[LAYERS*TOKENS];
    int mode_id, layer_id, row_sizes[TOKENS], tick=0;
    int checked_rows=0, checked_sizes=0, checked_maps=0, cross_bank=0, parallel_reads=0;
    int bank_reads[5];
    logic was_stalled=0;
    logic [20:0] held_output;
    string golden_fixture, captured_fixture;

    tri_oracle_cluster_token_sizes dut (
        .clk,.rst_n,.frame_valid,.frame_ready,.map_valid,.map_ready,
        .map_origin,.map_last,.query_valid,.query_ready,.query_position,
        .out_valid(row_valid),.out_ready(row_ready),.out_origin(row_origin),
        .out_count(row_count),.out_last(row_last),.error,.table_request,.table_word
    );

    always @(posedge clk) if (rst_n) begin
        tick<=tick+1;
        if (was_stalled && (!row_valid || {row_origin,row_count,row_last}!==held_output))
            $fatal(1,"LOCAL_SIZE_OUTPUT_CHANGED_WHILE_STALLED");
        was_stalled<=row_valid && !row_ready;
        held_output<={row_origin,row_count,row_last};
        for (int bank=0; bank<5; bank++)
            if (dut.controller.read_issued[bank]) bank_reads[bank]++;
        if ($countones(dut.controller.read_issued)>1) parallel_reads++;
        if (dut.controller.apply_step && dut.controller.step_origin[9:7]!==dut.controller.step_bank) cross_bank++;
    end

    task automatic write_table(input int token, input logic [9:0] origin);
        table_request={2'b11,10'(token),origin};
    endtask

    task automatic load_frame;
        frame_valid=1;
        @(posedge clk);
        if (!frame_ready) $fatal(1,"LOCAL_SIZE_FRAME_NOT_READY");
        @(negedge clk);
        frame_valid=0;
        for (int token=0;token<TOKENS;token++) begin
            map_valid=1;
            map_origin=captured[layer_id*TOKENS+token];
            map_last=token==TOKENS-1;
            write_table(token,map_origin);
            @(posedge clk);
            if (!map_ready || error) $fatal(1,"LOCAL_SIZE_MAP_REJECTED token=%0d",token);
            checked_maps++;
            @(negedge clk);
        end
        table_request='0;
        map_valid=0;
        map_last=0;
        if (!query_ready || error) $fatal(1,"LOCAL_SIZE_FRAME_REJECTED");
    endtask

    task automatic check_table_readback;
        for (int address=0;address<TOKENS;address+=8) begin
            table_request={2'b10,10'(address),10'd0};
            @(negedge clk);
            for (int lane=0;lane<8;lane++)
                if (table_word[lane*10+:10]!==captured[layer_id*TOKENS+address+lane])
                    $fatal(1,"LOCAL_SIZE_TABLE_READBACK address=%0d lane=%0d",address,lane);
        end
        table_request='0;
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
        if (!query_ready) $fatal(1,"LOCAL_SIZE_QUERY_NOT_READY");
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
                    $fatal(1,"LOCAL_SIZE_PREFIX_MISMATCH mode=%0d layer=%0d query=%0d beat=%0d got=%0d/%0d/%b expected=%0d/%0d/%b",
                           mode_id,layer_id,position,received,row_origin,row_count,row_last,expected_origin,
                           row_sizes[expected_origin],received+1==expected_words);
                expected_origin++;
                received++;
                checked_sizes++;
                total+=int'(row_count);
            end
            @(negedge clk);
        end
        row_ready=0;
        if (total!=position+1 || !query_ready) $fatal(1,"LOCAL_SIZE_PREFIX_TOTAL");
        checked_rows++;
    endtask

    initial begin
        foreach (bank_reads[bank]) bank_reads[bank]=0;
        if (!$value$plusargs("GOLDEN=%s",golden_fixture) || !$value$plusargs("CAPTURED=%s",captured_fixture))
            $fatal(1,"LOCAL_SIZE_FIXTURE");
        repeat (3) @(negedge clk);
        rst_n=1;
        mode_id=2;
        layer_id=0;
        for (int token=0;token<TOKENS;token++) begin
            golden[token]=(token%11==0) ? 10'(token) : 10'd0;
            captured[token]=golden[token];
        end
        load_frame();
        check_table_readback();
        check_row(575);
        check_row(127);
        check_row(128);
        check_row(255);
        check_row(256);
        check_row(511);
        check_row(512);
        check_row(0);
        check_row(575);
        if (cross_bank==0 || parallel_reads==0) $fatal(1,"LOCAL_SIZE_NO_CROSS_BANK_ACTIVITY");
        $display("LOCAL_SIZE_BOUNDARIES_PASS cross_bank=%0d parallel_reads=%0d",cross_bank,parallel_reads);

        // The write is valid for the table port, but the stored origin is a future token.
        load_frame();
        check_row(129);
        write_table(129,10'd130);
        @(negedge clk);
        table_request='0;
        query_valid=1;
        query_position=10'd127;
        @(posedge clk);
        if (!query_ready) $fatal(1,"LOCAL_SIZE_CORRUPT_QUERY_NOT_READY");
        @(negedge clk);
        query_valid=0;
        wait(error || row_valid);
        if (row_valid || !error) $fatal(1,"LOCAL_SIZE_CORRUPTED_WORD_ACCEPTED");
        @(negedge clk);
        $display("LOCAL_SIZE_FUTURE_ORIGIN_REJECTED");
        checked_maps=0;
        checked_rows=0;
        checked_sizes=0;
        if (!$test$plusargs("BOUNDARY_ONLY")) begin
            for (int mode=0;mode<2;mode++) begin
                mode_id=mode;
                $readmemh($sformatf("%s/map_%0d.hex",golden_fixture,mode),golden);
                $readmemh($sformatf("%s/map_%0d.hex",captured_fixture,mode),captured);
                for (int layer=0;layer<LAYERS;layer++) begin
                    layer_id=layer;
                    load_frame();
                    for (int position=0;position<TOKENS;position++) check_row(position);
                    check_row(23);
                    check_row(575);
                end
            end
            $display("LOCAL_SIZE_TRAINED_PASS maps=%0d rows=%0d sizes=%0d",checked_maps,checked_rows,checked_sizes);
        end
        foreach (bank_reads[bank]) begin
            if (bank_reads[bank]==0) $fatal(1,"LOCAL_SIZE_BANK_INACTIVE bank=%0d",bank);
            $display("LOCAL_SIZE_BANK_READS bank=%0d reads=%0d",bank,bank_reads[bank]);
        end
        $finish;
    end
    initial begin #120000000; $fatal(1,"LOCAL_SIZE_WATCHDOG"); end
endmodule
