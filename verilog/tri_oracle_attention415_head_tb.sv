`timescale 1ns/1ps
module tri_oracle_attention415_head_tb;
    localparam int HEADS=32, ROWS=510, SEQUENCE=606, WIDTH=64, FIRST_QUERY=96;
    localparam logic [31:0] TAG=32'h4150cafe;
    localparam logic [63:0] QUERY_BASE=64'h10000, KEY_BASE=64'h200000;
    logic clk=0, rst_n=0;
    always #5 clk=~clk;
    logic cfg_valid=0, out_ready=0;
    wire cfg_ready, out_valid, out_error, out_streaming;
    logic [31:0] cfg_tag, cfg_alpha;
    logic [12:0] cfg_tokens;
    logic [7:0] cfg_ratio_num, cfg_ratio_den;
    logic [63:0] cfg_query_base, cfg_key_base;
    wire [31:0] out_tag;
    wire [17:0] out_inner, out_outer;

    wire tensor_cfg_valid, tensor_cfg_ready, tensor_out_valid, tensor_out_last, tensor_out_ready;
    wire tensor_done_valid, tensor_done_error, tensor_done_ready;
    wire [31:0] tensor_cfg_tag, tensor_out_tag, tensor_done_tag;
    wire [4:0] tensor_cfg_tokens;
    wire [16:0] tensor_cfg_dense_rows;
    wire [2559:0] tensor_cfg_channels, tensor_cfg_keep;
    wire [63:0] tensor_cfg_activation_base, tensor_cfg_weight_base;
    wire [3:0] tensor_out_token;
    wire [7:0] tensor_out_count;
    wire [5119:0] tensor_results;
    wire [3071:0] tensor_out_data=tensor_results[3071:0];
    wire req_valid, req_ready, rsp_valid, rsp_ready, rsp_last, rsp_error;
    wire [63:0] req_address, rsp_data;
    wire [4:0] req_length;

    logic [7:0] queries[HEADS*ROWS*WIDTH], keys[4*SEQUENCE*WIDTH];
    logic [7:0] counts[HEADS*ROWS*2], types[HEADS];
    logic [31:0] alphas[HEADS];
    logic [63:0] read_address;
    logic reading=0, inject_request=0, fault_seen=0;
    bit fault_armed=0, invalid_case=0;
    int cycles=0, words_left, read_beat, accepted_batches, accepted_tensor, read_requests;
    int configured_tokens, next_position, prefill_batches=0, head_case;
    string fixture;

    tri_oracle_attention_head_predictor415 dut (.cfg_head_id(5'd0), .head_request(), .head_response('0), .*);
    tri_oracle_batched_tensor390 tensor (
        .clk, .rst_n, .cfg_valid(tensor_cfg_valid), .cfg_ready(tensor_cfg_ready),
        .cfg_paired(1'b0), .cfg_tag(tensor_cfg_tag), .cfg_tokens(tensor_cfg_tokens), .cfg_feature_words(10'd8),
        .cfg_dense_rows(tensor_cfg_dense_rows), .cfg_count(8'd96), .cfg_channels(tensor_cfg_channels),
        .cfg_keep(tensor_cfg_keep), .cfg_activation_base(tensor_cfg_activation_base),
        .cfg_weight_base(tensor_cfg_weight_base), .cfg_up_weight_base(64'd0), .cfg_activation_stride(32'd64),
        .out_valid(tensor_out_valid), .out_ready(tensor_out_ready), .out_tag(tensor_out_tag),
        .out_token(tensor_out_token), .out_last(tensor_out_last), .out_count(tensor_out_count),
        .out_channels(), .out_data(tensor_results), .done_valid(tensor_done_valid), .done_ready(tensor_done_ready),
        .done_error(tensor_done_error), .done_tag(tensor_done_tag),
        .req_valid, .req_ready, .req_address, .req_length, .rsp_valid, .rsp_ready, .rsp_last, .rsp_error, .rsp_data
    );
    assign req_ready=!reading && cycles%7!=0;
    assign rsp_valid=reading;
    assign rsp_last=words_left==1;
    assign rsp_error=inject_request && read_beat==0;
    for (genvar byte_index=0; byte_index<8; byte_index++) begin : read_memory
        assign rsp_data[byte_index*8 +: 8]=read_address>=KEY_BASE ?
            keys[int'(read_address-KEY_BASE)+byte_index] : queries[int'(read_address-QUERY_BASE)+byte_index];
    end

    always @(posedge clk) if (rst_n) begin
        cycles<=cycles+1;
        if (dut.batch_valid && dut.batch_ready) begin
            int expected_count, recent;
            expected_count=configured_tokens-next_position;
            if (expected_count>16) expected_count=16;
            recent=next_position/32*32;
            if (invalid_case || expected_count<1 || dut.batch_queries!==5'(expected_count) ||
                dut.batch_query_first!==16'(next_position) || dut.batch_key_rows!==17'(configured_tokens) ||
                dut.batch_tile_start!=={16'(recent),16'(recent-64),16'd0} || dut.batch_tag!==TAG ||
                dut.batch_query_addr!==QUERY_BASE+64'((head_case*ROWS+next_position-FIRST_QUERY)*WIDTH) ||
                dut.batch_key_base!==KEY_BASE+64'((head_case/8)*SEQUENCE*WIDTH) ||
                dut.batch_last!==(next_position+expected_count==configured_tokens))
                $fatal(1,"BATCH415_BAD_SCHEDULE position=%0d count=%0d",next_position,expected_count);
            accepted_batches++;
            next_position+=expected_count;
        end
        if (tensor_cfg_valid && tensor_cfg_ready) accepted_tensor++;
        if (req_valid && req_ready) begin
            logic second_query_batch;
            if (invalid_case || fault_seen || req_length==0 || req_length>2)
                $fatal(1,"BATCH415_UNEXPECTED_REQUEST addr=%h",req_address);
            second_query_batch=req_address>=QUERY_BASE+16*WIDTH && req_address<QUERY_BASE+32*WIDTH;
            if (fault_armed && second_query_batch) begin
                int inner_prefix, recent_prefix;
                inner_prefix=0; recent_prefix=0;
                for (int row=0; row<16; row++) begin
                    inner_prefix+=int'(counts[row*2]); recent_prefix+=int'(counts[row*2+1]);
                end
                if (accepted_batches!=2 || dut.local_classification.classifier.total_inner!==18'(inner_prefix) ||
                    dut.local_classification.classifier.total_outer!==18'(recent_prefix))
                    $fatal(1,"BATCH415_ERROR_WITHOUT_CHECKED_PREFIX");
            end
            inject_request<=fault_armed && second_query_batch;
            fault_seen<=fault_armed && second_query_batch;
            reading<=1;
            read_address<=req_address;
            words_left<=int'(req_length);
            read_beat<=0;
            read_requests++;
        end else if (rsp_valid && rsp_ready) begin
            reading<=!rsp_last;
            read_address<=read_address+64'd8;
            words_left<=words_left-1;
            read_beat<=read_beat+1;
        end
        if (out_valid && reading) $fatal(1,"BATCH415_RESULT_BEFORE_READ_DRAIN");
    end

    task automatic configure(input int head, tokens, input logic [7:0] numerator, denominator,
                             input logic [63:0] query_base, key_base, input bit invalid, inject);
        @(negedge clk);
        head_case=head; configured_tokens=tokens; next_position=FIRST_QUERY;
        accepted_batches=0; accepted_tensor=0; read_requests=0;
        fault_armed=inject; fault_seen=0; invalid_case=invalid;
        cfg_valid=1; cfg_tokens=13'(tokens); cfg_tag=TAG; cfg_alpha=alphas[head];
        cfg_ratio_num=numerator; cfg_ratio_den=denominator;
        cfg_query_base=query_base; cfg_key_base=key_base;
        @(posedge clk);
        if (!cfg_ready) $fatal(1,"BATCH415_BUSY");
        @(negedge clk);
        cfg_valid=0; cfg_tokens='x; cfg_tag='x; cfg_alpha='x;
        cfg_ratio_num='x; cfg_ratio_den='x; cfg_query_base='x; cfg_key_base='x;
    endtask

    task automatic finish_head(input int inner, recent, expected_batches, input bit streaming, error);
        while (!out_valid) @(negedge clk);
        repeat (5) begin
            if (!out_valid || cfg_ready || out_tag!==TAG || out_error!==error || out_streaming!==streaming ||
                out_inner!==18'(inner) || out_outer!==18'(recent) || accepted_batches!=expected_batches ||
                accepted_tensor!=expected_batches || (invalid_case && read_requests!=0) || (fault_armed && !fault_seen))
                $fatal(1,"BATCH415_RESULT batches=%0d inner=%0d recent=%0d streaming=%b error=%b",
                       accepted_batches,out_inner,out_outer,out_streaming,out_error);
            @(negedge clk);
        end
        out_ready=1;
        @(negedge clk);
        out_ready=0;
        if (!cfg_ready) $fatal(1,"BATCH415_OWNER_NOT_RELEASED");
    endtask

    initial begin
        int inner, recent;
        if (!$value$plusargs("FIXTURE=%s",fixture)) $fatal(1,"BATCH415_FIXTURE_REQUIRED");
        $readmemh({fixture,"/query.hex"},queries);
        $readmemh({fixture,"/key.hex"},keys);
        $readmemh({fixture,"/alpha.hex"},alphas);
        $readmemh({fixture,"/counts.hex"},counts);
        $readmemh({fixture,"/streaming.hex"},types);
        repeat (3) @(negedge clk);
        rst_n=1;
        configure(0,96,1,1,QUERY_BASE,KEY_BASE,1,0);
        finish_head(0,0,0,0,1);
        configure(0,4193,1,1,QUERY_BASE,KEY_BASE,1,0);
        finish_head(0,0,0,0,1);
        configure(0,SEQUENCE,1,0,QUERY_BASE,KEY_BASE,1,0);
        finish_head(0,0,0,0,1);
        configure(0,SEQUENCE,1,1,QUERY_BASE+1,KEY_BASE,1,0);
        finish_head(0,0,0,0,1);
        configure(0,97,1,1,64'hffffffffffffffc8,KEY_BASE,1,0);
        finish_head(0,0,0,0,1);
        configure(0,97,1,1,QUERY_BASE,64'hfffffffffffffff8,1,0);
        finish_head(0,0,0,0,1);
        configure(0,97,0,1,QUERY_BASE,KEY_BASE,0,0);
        if (counts[0]<=counts[1] || counts[1]==0) $fatal(1,"BATCH415_RATIO_FIXTURE_CHANGED");
        finish_head(int'(counts[0]),int'(counts[1]),1,1,0);
        configure(0,SEQUENCE,1,1,QUERY_BASE,KEY_BASE,0,1);
        finish_head(0,0,2,0,1);

        inner=0; recent=0;
        for (int row=0; row<ROWS; row++) begin
            inner+=int'(counts[2*row]); recent+=int'(counts[2*row+1]);
        end
        configure(0,SEQUENCE,1,1,QUERY_BASE,KEY_BASE,0,0);
        finish_head(inner,recent,32,types[0][0],0);
        prefill_batches=accepted_batches;
        $display("BATCH415_PASS heads=1 rows=510 batches=%0d inner=%0d recent=%0d invalid=6 late_abort=1 ratio=1 requests=%0d",
                 prefill_batches,inner,recent,read_requests);
        $finish;
    end
    initial begin #20000000; $fatal(1,"BATCH415_WATCHDOG"); end
endmodule
