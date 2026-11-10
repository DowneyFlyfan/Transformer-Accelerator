`timescale 1ns/1ps
module tri_oracle_qkv429_tb #(
    parameter int FIRST_HEAD=0, HEAD_COUNT=2, TEST_ERRORS=0
);
    localparam int TOKENS=4, WORDS=256;
    localparam logic [63:0] ACTIVATION_BASE=64'h10000, WEIGHT_BASE=64'h10000000;
    localparam logic [63:0] SHARD_BASE=WEIGHT_BASE+64'(FIRST_HEAD*64*2048);
    logic clk=0, rst_n=0;
    always #5 clk=~clk;
    logic cfg_valid=0, angle_valid=0, angle_last, out_ready=0, done_ready=0;
    logic [4:0] cfg_tokens;
    logic [5:0] cfg_start_head, cfg_heads;
    logic [31:0] cfg_tag;
    logic [239:0] cfg_shifts;
    logic [95:0] cfg_shift_biases;
    logic [511:0] angle_cos, angle_sin;
    wire cfg_ready, angle_ready, out_valid, out_last, done_valid, done_error;
    wire [31:0] out_tag, done_tag;
    wire [5:0] out_head;
    wire [3:0] out_token;
    wire [511:0] out_data;

    wire tensor_cfg_valid, tensor_cfg_ready, tensor_out_valid, tensor_out_ready, tensor_out_last;
    wire tensor_done_valid, tensor_done_ready, tensor_done_error;
    wire [31:0] tensor_cfg_tag, tensor_out_tag, native_out_tag, tensor_done_tag;
    wire [4:0] tensor_cfg_tokens;
    wire [7:0] tensor_cfg_count, tensor_out_count;
    wire [2559:0] tensor_cfg_channels, tensor_cfg_keep, tensor_out_channels;
    wire [63:0] tensor_cfg_activation_base, tensor_cfg_weight_base;
    wire [3:0] tensor_out_token;
    wire [5119:0] tensor_out_data;

    wire req_valid, rsp_ready;
    wire [63:0] req_address;
    wire [4:0] req_length;
    logic reading=0;
    logic [63:0] read_address;
    int words_left, cycles=0, fault=0, requests=0, vectors=0, rejects=0, stalls=0;
    logic [63:0] activations[TOKENS*WORDS], weights[HEAD_COUNT*64*WORDS];
    logic [511:0] cosines[TOKENS], sines[TOKENS], expected[HEAD_COUNT*TOKENS];
    logic [31:0] dots[HEAD_COUNT*TOKENS*64];
    logic [239:0] shifts[1];
    logic [95:0] shift_biases[1];
    string fixture;

    wire req_ready=!reading && cycles%5!=0;
    wire rsp_valid=reading;
    wire rsp_last=words_left==1;
    wire rsp_error=fault==3;
    wire [63:0] rsp_data=read_address>=WEIGHT_BASE ?
        weights[int'((read_address-SHARD_BASE)>>3)] : activations[int'((read_address-ACTIVATION_BASE)>>3)];
    assign tensor_out_tag=fault==4 ? native_out_tag^32'h80000000 : native_out_tag;

    tri_oracle_qkv429 dut (.cfg_activation_base(ACTIVATION_BASE), .cfg_weight_base(WEIGHT_BASE),
                          .tensor_out_data(tensor_out_data[4095:0]), .*);
    tri_oracle_batched_tensor390 tensor (
        .clk,.rst_n,.cfg_valid(tensor_cfg_valid),.cfg_ready(tensor_cfg_ready),.cfg_paired(1'b0),
        .cfg_tag(tensor_cfg_tag),.cfg_tokens(tensor_cfg_tokens),.cfg_feature_words(10'd256),
        .cfg_dense_rows(17'd2560),.cfg_count(tensor_cfg_count),.cfg_channels(tensor_cfg_channels),.cfg_keep(tensor_cfg_keep),
        .cfg_activation_base(tensor_cfg_activation_base),.cfg_weight_base(tensor_cfg_weight_base),
        .cfg_up_weight_base(64'd0),.cfg_activation_stride(32'd2048),
        .out_valid(tensor_out_valid),.out_ready(tensor_out_ready),.out_tag(native_out_tag),.out_token(tensor_out_token),
        .out_last(tensor_out_last),.out_count(tensor_out_count),.out_channels(tensor_out_channels),.out_data(tensor_out_data),
        .done_valid(tensor_done_valid),.done_ready(tensor_done_ready),.done_error(tensor_done_error),.done_tag(tensor_done_tag),
        .req_valid,.req_ready,.req_address,.req_length,.rsp_valid,.rsp_ready,.rsp_last,.rsp_error,.rsp_data
    );

    always @(posedge clk) if (rst_n) begin
        cycles<=cycles+1;
        if (req_valid && req_ready) begin
            if (req_length==0 || req_address[2:0]!=0 || fault inside {1,2} ||
                (req_address<WEIGHT_BASE && (req_address<ACTIVATION_BASE ||
                 req_address+64'(req_length)*8>ACTIVATION_BASE+TOKENS*2048)) ||
                (req_address>=WEIGHT_BASE && (req_address<SHARD_BASE ||
                 req_address+64'(req_length)*8>SHARD_BASE+64'(HEAD_COUNT*64*2048))))
                $fatal(1,"QKV429_READ address=%h",req_address);
            requests++;
            reading<=1;
            read_address<=req_address;
            words_left<=int'(req_length);
        end else if (rsp_valid && rsp_ready) begin
            reading<=!rsp_last;
            read_address<=read_address+64'd8;
            words_left<=words_left-1;
        end
        if (fault!=0 && out_valid) $fatal(1,"QKV429_FAULT_OUTPUT fault=%0d",fault);
        if (fault==0 && tensor_out_valid && tensor_out_ready) begin
            for (int lane=0;lane<int'(tensor_out_count);lane++) begin
                int channel, golden_index;
                channel=int'(tensor_out_channels[lane*16+:16])-FIRST_HEAD*64;
                golden_index=((channel/64)*TOKENS+int'(tensor_out_token))*64+channel%64;
                if (channel<0 || channel>=HEAD_COUNT*64 || int'(tensor_out_token)>=TOKENS ||
                    tensor_out_data[lane*32+:32]!==dots[golden_index])
                    $fatal(1,"QKV429_DOT first=%0d channel=%0d token=%0d",FIRST_HEAD,channel,tensor_out_token);
            end
        end
    end

    task automatic run(input int problem);
        @(negedge clk);
        fault=problem; cfg_valid=1;
        cfg_start_head=6'(FIRST_HEAD); cfg_heads=problem==1 ? 6'd0 : 6'(HEAD_COUNT);
        cfg_tokens=5'(TOKENS); cfg_tag=32'h42901000+32'(problem); cfg_shifts=shifts[0];
        cfg_shift_biases=shift_biases[0];
        @(posedge clk);
        if (!cfg_ready) $fatal(1,"QKV429_CONFIG");
        @(negedge clk);
        cfg_valid=0;
        if (FIRST_HEAD<36 && problem!=1) begin
            for (int token=0;token<(problem==2 ? 1 : TOKENS);token++) begin
                angle_valid=1; angle_last=(problem==2 || token==TOKENS-1);
                angle_cos=cosines[token]; angle_sin=sines[token];
                do @(posedge clk); while (!angle_ready);
                @(negedge clk);
            end
            angle_valid=0;
        end
        if (problem==0) begin
            for (int base=0;base<HEAD_COUNT;base+=2) begin
                int tile_heads;
                tile_heads=HEAD_COUNT-base>=2 ? 2 : 1;
                for (int token=0;token<TOKENS;token++) begin
                    for (int offset=0;offset<tile_heads;offset++) begin
                        int head;
                        head=base+offset;
                        while (!out_valid) @(negedge clk);
                        repeat (2) begin
                            if (!out_valid || out_tag!==cfg_tag || out_head!==6'(FIRST_HEAD+head) ||
                                out_token!==4'(token) || out_last!==(head==HEAD_COUNT-1 && token==TOKENS-1) ||
                                out_data!==expected[head*TOKENS+token])
                                $fatal(1,"QKV429_VECTOR head=%0d token=%0d",FIRST_HEAD+head,token);
                            stalls++;
                            @(negedge clk);
                        end
                        out_ready=1;
                        @(negedge clk);
                        out_ready=0;
                        vectors++;
                    end
                end
            end
        end
        while (!done_valid) @(negedge clk);
        repeat (3) begin
            if (!done_valid || done_error!==(problem!=0) || done_tag!==cfg_tag || reading || out_valid || cfg_ready)
                $fatal(1,"QKV429_DONE fault=%0d error=%b",problem,done_error);
            @(negedge clk);
        end
        done_ready=1;
        @(negedge clk);
        done_ready=0;
        rejects+=int'(problem!=0);
    endtask

    initial begin
        if (!$value$plusargs("FIXTURE=%s",fixture)) $fatal(1,"QKV429_FIXTURE");
        $readmemh({fixture,"/activation.hex"},activations);
        $readmemh({fixture,"/weights.hex"},weights);
        $readmemh({fixture,"/cos.hex"},cosines);
        $readmemh({fixture,"/sin.hex"},sines);
        $readmemh({fixture,"/shifts.hex"},shifts);
        $readmemh({fixture,"/shift_biases.hex"},shift_biases);
        $readmemh({fixture,"/expected.hex"},expected);
        $readmemh({fixture,"/dots.hex"},dots);
        repeat (4) @(negedge clk);
        rst_n=1;
        if (TEST_ERRORS!=0) begin
            run(1);
            run(2);
            run(3);
            run(4);
        end
        run(0);
        $display("QKV429_PASS first=%0d heads=%0d vectors=%0d faults=%0d stalls=%0d",
                 FIRST_HEAD,HEAD_COUNT,vectors,rejects,stalls);
        $finish;
    end

    initial begin
        #100000000;
        $fatal(1,"QKV429_TIMEOUT head=%0d",FIRST_HEAD);
    end
endmodule
