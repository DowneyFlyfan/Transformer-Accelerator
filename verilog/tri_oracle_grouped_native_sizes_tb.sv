`timescale 1ns/1ps
module tri_oracle_grouped_native_sizes_tb;
    logic clk=0,rst_n=0;
    always #5 clk=!clk;
    logic frame_valid=0,frame_ready,map_valid=0,map_ready,map_last=0;
    logic [9:0] map_origin=0;
    logic [21:0] table_request=0;
    logic prepare_valid=0,prepare_ready,done,error,done_ready=0;
    logic [10:0] first_position=0;
    logic [9:0] image_start=10'd5,first_visible=0,second_visible=0;
    logic [3:0] active_rows=4'hf,streaming_rows=4'ha;
    logic native_query_valid,native_query_ready,native_size_valid,native_size_ready;
    logic [9:0] native_query_position,native_size_count;
    logic native_size_last,native_error;
    logic [3:0][8:0] size_index='0;
    logic [3:0][9:0] selected_size;
    logic [9:0] map_data[576];
    int counted_queries=0,checked_sizes=0,cycles=0;
    int native_query_positions[8];

    tri_oracle_cluster_token_sizes tables (
        .clk,.rst_n,.frame_valid,.frame_ready,.map_valid,.map_ready,.map_origin,.map_last,.table_request,
        .table_word(),.query_valid(native_query_valid),.query_ready(native_query_ready),
        .query_position(native_query_position),.out_valid(native_size_valid),.out_ready(native_size_ready),
        .out_origin(),.out_count(native_size_count),.out_last(native_size_last),.error(native_error)
    );
    tri_oracle_grouped_token_sizes dut (.*);

    always @(posedge clk) if (rst_n) begin
        cycles++;
        if (cycles>10000) $fatal(1,"GROUPED_SIZES_TIMEOUT");
        if (native_query_valid && native_query_ready) begin
            if (counted_queries==8) $fatal(1,"EXTRA_GROUPED_SIZE_QUERY");
            native_query_positions[counted_queries]=int'(native_query_position);
            counted_queries++;
        end
    end

    task automatic install_map;
        frame_valid=1;
        @(posedge clk);
        if (!frame_ready) $fatal(1,"GROUPED_SIZES_FRAME");
        @(negedge clk);
        frame_valid=0;
        for (int index=0;index<576;index++) begin
            map_valid=1;
            map_origin=map_data[index];
            map_last=index==575;
            table_request={2'b11,10'(index),map_origin};
            @(posedge clk);
            if (!map_ready) $fatal(1,"GROUPED_SIZES_MAP index=%0d",index);
            @(negedge clk);
        end
        map_valid=0;
        map_last=0;
        table_request=0;
        if (native_error) $fatal(1,"GROUPED_SIZES_MAP_ERROR");
    endtask

    task automatic compare(input int start, input logic [3:0] mask, input bit invalid);
        int expected[2][512],visible[2];
        int root_sizes[576];
        int position,last_image,rank_count;
        last_image=int'(image_start)+575;
        for (int query=0;query<2;query++) begin
            position=start+query;
            foreach (root_sizes[entry]) root_sizes[entry]=0;
            for (int original=0;original<=position-int'(image_start) && original<576;original++)
                root_sizes[map_data[original]]++;
            rank_count=0;
            for (int rank=0;rank<int'(image_start) && rank<=position;rank++) expected[query][rank_count++]=1;
            foreach (root_sizes[entry]) if (root_sizes[entry]!=0) expected[query][rank_count++]=root_sizes[entry];
            for (int text=last_image+1;text<=position;text++) expected[query][rank_count++]=1;
            visible[query]=rank_count;
        end
        first_position=11'(start);
        first_visible=10'(visible[0]+int'(invalid));
        second_visible=10'(visible[1]);
        active_rows=mask;
        prepare_valid=1;
        @(posedge clk);
        if (!prepare_ready) $fatal(1,"GROUPED_SIZES_NOT_READY");
        @(negedge clk);
        prepare_valid=0;
        while (!done) @(negedge clk);
        if (error!==invalid) $fatal(1,"GROUPED_SIZES_ERROR expected=%b",invalid);
        if (!invalid) for (int lane=0;lane<4;lane++) if (mask[lane]) begin
            int count,query,rank;
            query=lane/2;
            count=streaming_rows[lane] && visible[query]>64 ? 64 : visible[query];
            for (int offset=0;offset<count;offset++) begin
                rank=(streaming_rows[lane] && visible[query]>64 && offset>=32) ?
                     visible[query]-64+offset : offset;
                size_index[lane]=9'(offset);
                #1;
                if (selected_size[lane]!==10'(expected[query][rank]))
                    $fatal(1,"GROUPED_SIZES_DATA lane=%0d offset=%0d rank=%0d size=%d expect=%d",
                           lane,offset,rank,selected_size[lane],expected[query][rank]);
                checked_sizes++;
            end
        end
        @(negedge clk);
        repeat (3) begin
            if (!done || error!==invalid || prepare_ready) $fatal(1,"GROUPED_SIZES_STALLED_COMPLETION");
            @(negedge clk);
        end
        done_ready=1;
        @(negedge clk);
        done_ready=0;
        if (!prepare_ready) $fatal(1,"GROUPED_SIZES_BUSY");
    endtask

    initial begin
        string map_file;
        if (!$value$plusargs("MAP=%s",map_file)) $fatal(1,"MISSING_NATIVE_MAP");
        $readmemh(map_file,map_data);
        repeat(5) @(negedge clk);
        rst_n=1;
        first_position=11'd580;
        first_visible=10'd347;
        second_visible=10'd348;
        prepare_valid=1;
        @(negedge clk);
        prepare_valid=0;
        repeat (6) @(negedge clk);
        if (done!==1 || error!==1 || counted_queries!=0)
            $fatal(1,"MISSING_MERGE_CONTEXT_NOT_REJECTED");
        done_ready=1;
        @(negedge clk);
        done_ready=0;
        $display("MISSING_MERGE_CONTEXT_REJECTED");
        install_map();
        compare(0,4'hf,0);
        compare(580,4'hf,0);
        compare(580,4'ha,0);
        compare(580,4'h4,0);
        compare(400,4'h1,1);
        compare(400,4'h1,0);
        compare(579,4'hf,0);
        compare(580,4'hf,1);
        if (counted_queries!=8 || checked_sizes!=2365 ||
            native_query_positions[0]!=575 || native_query_positions[1]!=575 ||
            native_query_positions[2]!=575 || native_query_positions[3]!=395 ||
            native_query_positions[4]!=395 || native_query_positions[5]!=574 ||
            native_query_positions[6]!=575 || native_query_positions[7]!=575)
            $fatal(1,"GROUPED_SIZES_COVERAGE queries=%d sizes=%d",counted_queries,checked_sizes);
        $display("GROUPED_NATIVE_SIZES_PASS queries=%0d exact_sizes=%0d",counted_queries,checked_sizes);
        $finish;
    end
endmodule
