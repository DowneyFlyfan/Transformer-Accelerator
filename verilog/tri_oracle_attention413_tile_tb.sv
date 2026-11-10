`timescale 1ns/1ps
module tri_oracle_attention413_tile_tb #(
    parameter int FIRST_HEAD=0, HEAD_COUNT=32, CANARY=0
);
    localparam int HEADS=32, ROWS=510, SEQUENCE=606, WIDTH=64, QUERY_FIRST=96;
    localparam logic [31:0] TAG=32'h4130cafe;
    localparam logic [63:0] QUERY_BASE=64'h10000, KEY_BASE=64'h200000;
    logic clk=0;
    always #5 clk=~clk;
    logic rst_n=0, batch_valid=0, batch_last;
    wire batch_ready;
    logic [31:0] batch_tag;
    logic [63:0] batch_query_addr, batch_key_base;
    logic [16:0] batch_key_rows;
    logic [15:0] batch_query_first;
    logic [4:0] batch_queries;
    logic [47:0] batch_tile_start;
    wire score_valid, score_last, score_error, score_ready;
    wire [31:0] score_tag;
    wire [1:0] score_region;
    wire [7:0] score_lanes;
    wire [255:0] score_data;
    wire tensor_cfg_valid, tensor_cfg_ready, tensor_out_valid, tensor_out_last, tensor_out_ready;
    wire tensor_done_valid, tensor_done_error, tensor_done_ready;
    wire [31:0] tensor_cfg_tag, tensor_out_tag, native_done_tag;
    wire [4:0] tensor_cfg_tokens;
    wire [16:0] tensor_cfg_dense_rows;
    wire [2559:0] tensor_cfg_channels, tensor_cfg_keep;
    wire [63:0] tensor_cfg_activation_base, tensor_cfg_weight_base;
    wire [3:0] native_out_token;
    wire [7:0] tensor_out_count;
    wire [5119:0] tensor_results;
    wire [3071:0] tensor_out_data=tensor_results[3071:0];
    wire req_valid, req_ready, rsp_valid, rsp_ready, rsp_last, rsp_error;
    wire [63:0] req_address, rsp_data;
    wire [4:0] req_length;
    logic cfg_valid=0, out_ready=0;
    wire cfg_ready, classifier_in_ready, out_valid, out_error, out_streaming;
    logic [31:0] cfg_alpha;
    logic [12:0] cfg_rows;
    wire [31:0] out_tag;
    wire [17:0] out_inner, out_outer;
    logic [7:0] queries[HEADS*ROWS*WIDTH], keys[4*SEQUENCE*WIDTH];
    logic [31:0] expected_scores[HEADS*ROWS*3*32], alphas[HEADS];
    logic [7:0] counts[HEADS*ROWS*2], types[HEADS];
    logic reading=0;
    logic [63:0] read_address, expected_query, expected_key;
    int words_left, word_in_burst, cycles=0, fault=0, head_id, first_query, query_count, starts[3];
    int requests=0, read_words=0, stalls=0, error_beats=0, live_scores=0, masked_scores=0, score_beats;
    int query_reads[16][8], key_reads[3][32][8];
    bit held=0, final_batch;
    logic [299:0] held_packet;
    wire [299:0] packet={score_tag,score_last,score_error,score_region,score_lanes,score_data};
    wire permit=cycles%5<2;
    wire [3:0] tensor_out_token=(fault==3 && native_out_token==1) ? native_out_token^4'h8 : native_out_token;
    wire [31:0] tensor_done_tag=(fault==4) ? native_done_tag^32'h80000000 : native_done_tag;
    string fixture;

    tri_oracle_attention_tile_batch413 adapter (.*);
    tri_oracle_batched_tensor390 tensor (
        .clk, .rst_n, .cfg_valid(tensor_cfg_valid), .cfg_ready(tensor_cfg_ready),
        .cfg_paired(1'b0), .cfg_tag(tensor_cfg_tag), .cfg_tokens(tensor_cfg_tokens), .cfg_feature_words(10'd8),
        .cfg_dense_rows(tensor_cfg_dense_rows), .cfg_count(8'd96), .cfg_channels(tensor_cfg_channels),
        .cfg_keep(tensor_cfg_keep), .cfg_activation_base(tensor_cfg_activation_base),
        .cfg_weight_base(tensor_cfg_weight_base), .cfg_up_weight_base(64'd0), .cfg_activation_stride(32'd64),
        .out_valid(tensor_out_valid), .out_ready(tensor_out_ready), .out_tag(tensor_out_tag),
        .out_token(native_out_token), .out_last(tensor_out_last), .out_count(tensor_out_count),
        .out_channels(), .out_data(tensor_results), .done_valid(tensor_done_valid), .done_ready(tensor_done_ready),
        .done_error(tensor_done_error), .done_tag(native_done_tag),
        .req_valid, .req_ready, .req_address, .req_length, .rsp_valid, .rsp_ready, .rsp_last, .rsp_error, .rsp_data
    );
    assign score_ready=classifier_in_ready && permit;
    tri_oracle_attention_head_classifier410 classifier (
        .clk, .rst_n, .cfg_valid, .cfg_ready, .cfg_tag(TAG), .cfg_alpha, .cfg_rows,
        .cfg_ratio_num(8'd1), .cfg_ratio_den(8'd1), .in_valid(score_valid && permit),
        .in_last(score_last), .in_ready(classifier_in_ready), .in_tag(score_tag), .in_region(score_region),
        .in_lanes(score_lanes), .in_scores(score_data), .out_valid, .out_ready, .out_error,
        .out_streaming, .out_tag, .out_inner, .out_outer
    );
    assign req_ready=!reading && cycles%7!=0;
    assign rsp_valid=reading;
    assign rsp_last=words_left==1;
    assign rsp_error=fault==2 && word_in_burst==0;
    for (genvar byte_index=0; byte_index<8; byte_index++) begin : memory_read
        assign rsp_data[byte_index*8 +: 8]=read_address>=KEY_BASE ?
            keys[int'(read_address-KEY_BASE)+byte_index] : queries[int'(read_address-QUERY_BASE)+byte_index];
    end

    always @(posedge clk) if (rst_n) begin
        cycles<=cycles+1;
        if (req_valid && req_ready) begin
            if (fault inside {1,5} || req_length==0 || req_length>2 || req_address[2:0]!=0)
                $fatal(1,"BATCH413_BAD_READ address=%h length=%0d fault=%0d",req_address,req_length,fault);
            for (int word=0; word<int'(req_length); word++) begin
                logic [63:0] address;
                int index, feature, region;
                address=req_address+64'(word*8);
                if (address>=expected_query && address<expected_query+64'(query_count*WIDTH)) begin
                    index=int'(address-expected_query)/WIDTH;
                    feature=(int'(address-expected_query)%WIDTH)/8;
                    query_reads[index][feature]++;
                end else if (address>=expected_key && address<expected_key+SEQUENCE*WIDTH) begin
                    index=int'(address-expected_key)/WIDTH;
                    feature=(int'(address-expected_key)%WIDTH)/8;
                    region=-1;
                    for (int i=0; i<3; i++)
                        if (index>=starts[i] && index<starts[i]+32) region=i;
                    if (region<0 || index>=first_query+query_count)
                        $fatal(1,"BATCH413_UNSELECTED_OR_FUTURE_KEY key=%0d",index);
                    key_reads[region][index-starts[region]][feature]++;
                end else $fatal(1,"BATCH413_READ_OUTSIDE_BATCH address=%h",address);
            end
            requests++;
            read_words+=int'(req_length);
            reading<=1;
            read_address<=req_address;
            words_left<=int'(req_length);
            word_in_burst<=0;
        end else if (rsp_valid && rsp_ready) begin
            reading<=!rsp_last;
            read_address<=read_address+64'd8;
            words_left<=words_left-1;
            word_in_burst<=word_in_burst+1;
        end

        if (held && (!score_valid || packet!==held_packet)) $fatal(1,"BATCH413_SCORE_CHANGED_UNDER_STALL");
        held<=score_valid && !score_ready;
        if (score_valid && !score_ready) begin
            held_packet<=packet;
            stalls++;
        end
        if (score_valid && score_ready) begin
            if (score_tag!==TAG || batch_ready) $fatal(1,"BATCH413_LOST_OWNER");
            if (score_error) begin
                if (fault==0 || !score_last || score_region!=3 || score_lanes!=0 || score_data!=0)
                    $fatal(1,"BATCH413_BAD_TERMINAL_ERROR fault=%0d",fault);
                error_beats++;
            end else begin
                int position;
                position=first_query+score_beats/12;
                if (score_region!=(score_beats%12)/4 || score_last!==(fault==0 && final_batch && score_beats==query_count*12-1))
                    $fatal(1,"BATCH413_SCORE_ORDER head=%0d position=%0d beat=%0d",head_id,position,score_beats);
                for (int lane=0; lane<8; lane++) begin
                    int key_lane;
                    bit expected_live;
                    logic [31:0] expected;
                    key_lane=(score_beats%4)*8+lane;
                    expected_live=starts[score_region]+key_lane<=position;
                    expected=expected_scores[((head_id*ROWS+position-QUERY_FIRST)*3+int'(score_region))*32+key_lane];
                    if (score_lanes[lane]!==expected_live || score_data[lane*32 +: 32]!==expected)
                        $fatal(1,"BATCH413_BAD_SCORE head=%0d query=%0d region=%0d lane=%0d expected=%h actual=%h",
                               head_id,position,score_region,key_lane,expected,score_data[lane*32 +: 32]);
                    if (fault==0) begin
                        if (expected_live) live_scores++;
                        else masked_scores++;
                    end
                end
                score_beats++;
            end
        end
    end

    task automatic configure(input int head, rows);
        @(negedge clk);
        cfg_valid=1; cfg_rows=13'(rows); cfg_alpha=alphas[head];
        @(posedge clk);
        if (!cfg_ready) $fatal(1,"BATCH413_CLASSIFIER_BUSY");
        @(negedge clk);
        cfg_valid=0;
    endtask

    task automatic send_batch(input int head, start, count, input bit last, input int problem);
        int initial_requests, initial_errors, expected_beats;
        @(negedge clk);
        head_id=head; first_query=start; query_count=count; fault=problem; final_batch=last;
        score_beats=0; initial_requests=requests; initial_errors=error_beats;
        starts='{0,(start/32-2)*32,(start/32)*32};
        expected_query=QUERY_BASE+64'((head*ROWS+start-QUERY_FIRST)*WIDTH);
        expected_key=KEY_BASE+64'((head/8)*SEQUENCE*WIDTH);
        foreach (query_reads[row,word]) query_reads[row][word]=0;
        foreach (key_reads[region,lane,word]) key_reads[region][lane][word]=0;
        batch_valid=1; batch_tag=TAG; batch_last=last;
        batch_query_addr=expected_query; batch_key_base=expected_key;
        batch_key_rows=17'(SEQUENCE); batch_query_first=16'(start);
        batch_queries=fault==1 ? 5'd0 : 5'(count);
        batch_tile_start={16'(starts[2]),16'(fault==5 ? starts[0] : starts[1]),16'(starts[0])};
        @(posedge clk);
        if (!batch_ready) $fatal(1,"BATCH413_ADAPTER_BUSY");
        @(negedge clk);
        batch_valid=0; batch_tag='x; batch_query_addr='x; batch_key_base='x;
        batch_key_rows='x; batch_query_first='x; batch_queries='x; batch_tile_start='x; batch_last='x;
        while (!batch_ready) @(negedge clk);
        case (problem)
            0: expected_beats=count*12;
            3: expected_beats=12;
            4: expected_beats=(count-1)*12;
            default: expected_beats=0;
        endcase
        if (score_beats!=expected_beats || error_beats-initial_errors!=int'(problem!=0) || reading)
            $fatal(1,"BATCH413_SCORE_INVENTORY fault=%0d beats=%0d expected=%0d",problem,score_beats,expected_beats);
        if (problem inside {1,2,5}) begin
            if (requests-initial_requests!=int'(problem==2)) $fatal(1,"BATCH413_ERROR_READ_COUNT");
        end else for (int word=0; word<8; word++) begin
            bit needed;
            needed=0;
            for (int row=0; row<16; row++) begin
                if (query_reads[row][word]!=int'(row<count)) $fatal(1,"BATCH413_QUERY_RELOAD row=%0d word=%0d",row,word);
                if (row<count) for (int lane=0; lane<8; lane++)
                    needed|=queries[(head*ROWS+start-QUERY_FIRST+row)*WIDTH+word*8+lane]!=0;
            end
            for (int region=0; region<3; region++)
                for (int lane=0; lane<32; lane++)
                    if (key_reads[region][lane][word]!=int'(needed && starts[region]+lane<start+count))
                        $fatal(1,"BATCH413_KEY_RELOAD region=%0d lane=%0d word=%0d",region,lane,word);
        end
    endtask

    task automatic finish_head(input int inner, recent, input bit streaming, error);
        while (!out_valid) @(negedge clk);
        repeat (3) begin
            if (!out_valid || out_tag!==TAG || out_error!==error || out_streaming!==streaming ||
                out_inner!==18'(inner) || out_outer!==18'(recent))
                $fatal(1,"BATCH413_HEAD head=%0d inner=%0d recent=%0d type=%b error=%b",
                       head_id,out_inner,out_outer,out_streaming,out_error);
            @(negedge clk);
        end
        out_ready=1;
        @(negedge clk);
        out_ready=0;
    endtask

    initial begin
        int rows_checked, heads_checked, streaming_heads;
        rows_checked=0; heads_checked=0; streaming_heads=0;
        if (!$value$plusargs("FIXTURE=%s",fixture)) $fatal(1,"BATCH413_FIXTURE_REQUIRED");
        $readmemh({fixture,"/query.hex"},queries);
        $readmemh({fixture,"/key.hex"},keys);
        $readmemh({fixture,"/scores.hex"},expected_scores);
        $readmemh({fixture,"/alpha.hex"},alphas);
        $readmemh({fixture,"/counts.hex"},counts);
        $readmemh({fixture,"/streaming.hex"},types);
        repeat (3) @(negedge clk);
        rst_n=1;
        if (FIRST_HEAD==0) for (int problem=1; problem<=5; problem++) begin
            configure(0,3);
            send_batch(0,96,3,1,problem);
            finish_head(0,0,0,1);
        end
        for (int head=FIRST_HEAD; head<FIRST_HEAD+HEAD_COUNT; head++) begin
            int inner, recent;
            bit streaming;
            inner=0; recent=0;
            configure(head,CANARY ? 30 : ROWS);
            for (int start=QUERY_FIRST; start<SEQUENCE; start+=16) if (!CANARY || start==96 || start==592) begin
                int count;
                count=(SEQUENCE-start<16) ? SEQUENCE-start : 16;
                send_batch(head,start,count,start+count==SEQUENCE,0);
                for (int row=start-QUERY_FIRST; row<start-QUERY_FIRST+count; row++) begin
                    inner+=int'(counts[(head*ROWS+row)*2]);
                    recent+=int'(counts[(head*ROWS+row)*2+1]);
                end
                if (classifier.total_inner!==18'(inner) || classifier.total_outer!==18'(recent))
                    $fatal(1,"BATCH413_BATCH_COUNTS head=%0d start=%0d",head,start);
                rows_checked+=count;
            end
            streaming=recent>inner;
            if (!CANARY && streaming!==types[head][0]) $fatal(1,"BATCH413_REFERENCE_HEAD_INCONSISTENT");
            finish_head(inner,recent,streaming,0);
            heads_checked++;
            streaming_heads+=int'(streaming);
        end
        if (heads_checked!=HEAD_COUNT || rows_checked!=HEAD_COUNT*(CANARY ? 30 : ROWS) ||
            live_scores+masked_scores!=rows_checked*96 || error_beats!=(FIRST_HEAD==0 ? 5 : 0) || stalls==0)
            $fatal(1,"BATCH413_FINAL_INVENTORY");
        $display("BATCH413_PASS first=%0d heads=%0d rows=%0d live=%0d masked=%0d streaming=%0d errors=%0d requests=%0d words=%0d stalls=%0d",
                 FIRST_HEAD,heads_checked,rows_checked,live_scores,masked_scores,streaming_heads,error_beats,requests,read_words,stalls);
        $finish;
    end
    initial begin #100000000; $fatal(1,"BATCH413_WATCHDOG"); end
endmodule
