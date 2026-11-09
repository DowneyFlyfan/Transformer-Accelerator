`timescale 1ns/1ps
// Real checkpoint slice:64 original intermediate channels,2048 input features,
// full5632-byte down row stride,35 highest legal model output rows.
// Catches loss of original IDs, projection strides, nonlinear quantization,
// prediction skip mistakes and unknown arithmetic outputs under memory stalls.
module tri_oracle_model_feedforward_tb #(parameter integer HARDWARE_PREDICTION=0);
    string fixture_directory=".cache/model_reference/feedforward_fixture";
    integer fixture_override;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,cfg_valid=0,in_valid=0,in_last=0,in_group_last=0,out_ready=0;
    wire cfg_ready,in_ready,out_valid,out_last,out_fallback,out_error,req_valid,rsp_ready;
    reg [31:0] cfg_tag=32'h4d4f444c;
    localparam [63:0] ACT_BASE=64'h1000,GATE_BASE=64'h100000,
        UP_BASE=64'h40000000,DOWN_BASE=64'h80000000,
        GATE_SIGN_BASE=64'h100000000,UP_SIGN_BASE=64'h200000000;
    wire [63:0] cfg_activation_base=ACT_BASE,cfg_weight_base=GATE_BASE,
        cfg_up_weight_base=UP_BASE,cfg_down_weight_base=DOWN_BASE;
    wire [9:0] cfg_features=256;
    wire [16:0] cfg_dense_features=5632;
    reg [31:0] configuration[0:4];
    wire [5:0] cfg_gate_shift=configuration[0][5:0],
        cfg_up_shift=configuration[1][5:0],cfg_down_shift=configuration[2][5:0];
    wire [15:0] cfg_output_start=configuration[3][15:0];
    wire [8:0] cfg_output_count=configuration[4][8:0];
    reg [10:0] in_group=0;
    reg [127:0] norm_activations=0;
    reg [255:0] gate_weight_signs=0,up_weight_signs=0;
    reg group_valid=0,stats_valid=0,stats_last=0,replay_valid=0,replay_last=0;
    wire group_ready,stats_ready,replay_ready;
    reg [127:0] stats_data=0,replay_data=0;
    reg [15:0] raw_residual[0:2047];
    reg [15:0] learned_gamma[0:2047];
    reg [127:0] replay_gamma=0;
    reg [31:0] epsilon[0:0];
    reg [31:0] activation_shift[0:0];
    wire [31:0] out_tag;
    wire [5:0] out_count;
    wire [511:0] out_channels;
    wire [1023:0] out_data;
    wire [63:0] req_address;
    wire [4:0] req_length;
    reg rsp_valid=0,rsp_last=0;
    wire rsp_error=0;
    reg [63:0] rsp_data=0;
    integer cycle=0,requests=0,beats=0,length=0,received=0;
    integer gate_bytes=0,up_bytes=0,activation_bytes=0,down_bytes=0,skipped=0,sign_bytes=0;
    reg model_active=0;
    reg [63:0] address=0;
    wire req_ready=!model_active && !rsp_valid && cycle%4!=0;
    reg [7:0] activation[0:2047],gate_weights[0:131071],up_weights[0:131071];
    reg [7:0] down_weights[0:197119],skip_channels[0:63];
    reg [15:0] normalized[0:2047],groups[0:1];
    reg [31:0] expected[0:34];
    reg [1576:0] held;
    reg stalled=0;
    generate
        if(HARDWARE_PREDICTION==0) begin: software_prediction
            tri_oracle_feedforward_core dut(.*);
        end else if(HARDWARE_PREDICTION==1) begin: hardware_prediction
            tri_oracle_normalized_feedforward_core dut(
                .clk(clk),.rst_n(rst_n),.cfg_valid(cfg_valid),.cfg_ready(cfg_ready),
                .cfg_tag(cfg_tag),.cfg_epsilon_q16(epsilon[0]),
                .cfg_activation_base(cfg_activation_base),.cfg_weight_base(cfg_weight_base),
                .cfg_up_weight_base(cfg_up_weight_base),.cfg_down_weight_base(cfg_down_weight_base),
                .cfg_gate_sign_base(GATE_SIGN_BASE),.cfg_up_sign_base(UP_SIGN_BASE),
                .cfg_gate_shift(cfg_gate_shift),.cfg_up_shift(cfg_up_shift),
                .cfg_down_shift(cfg_down_shift),.cfg_features(cfg_features),
                .cfg_dense_features(cfg_dense_features),.cfg_output_start(cfg_output_start),
                .cfg_output_count(cfg_output_count),.group_valid(group_valid),
                .group_ready(group_ready),.group_id(in_group),.group_last(in_group_last),
                .stats_valid(stats_valid),.stats_ready(stats_ready),.stats_last(stats_last),
                .stats_data(stats_data),.replay_valid(replay_valid),.replay_ready(replay_ready),
                .replay_last(replay_last),.replay_data(replay_data),.out_valid(out_valid),
                .out_ready(out_ready),.out_last(out_last),.out_fallback(out_fallback),
                .out_error(out_error),.out_tag(out_tag),.out_count(out_count),
                .out_channels(out_channels),.out_data(out_data),.req_valid(req_valid),
                .req_ready(req_ready),.req_address(req_address),.req_length(req_length),
                .rsp_valid(rsp_valid),.rsp_last(rsp_last),.rsp_error(rsp_error),
                .rsp_ready(rsp_ready),.rsp_data(rsp_data)
            );
        end else begin: cached_prediction
            tri_oracle_cached_feedforward_core dut(
                .clk(clk),.rst_n(rst_n),.cfg_valid(cfg_valid),.cfg_ready(cfg_ready),
                .cfg_tag(cfg_tag),.cfg_epsilon_q16(epsilon[0]),
                .cfg_activation_base(cfg_activation_base),.cfg_weight_base(cfg_weight_base),
                .cfg_up_weight_base(cfg_up_weight_base),.cfg_down_weight_base(cfg_down_weight_base),
                .cfg_gate_sign_base(GATE_SIGN_BASE),.cfg_up_sign_base(UP_SIGN_BASE),
                .cfg_gate_shift(cfg_gate_shift),.cfg_up_shift(cfg_up_shift),
                .cfg_down_shift(cfg_down_shift),.cfg_activation_shift(activation_shift[0][5:0]),
                .cfg_features(cfg_features),.cfg_dense_features(cfg_dense_features),
                .cfg_output_start(cfg_output_start),.cfg_output_count(cfg_output_count),
                .group_valid(group_valid),.group_ready(group_ready),
                .group_id(in_group),.group_last(in_group_last),
                .stats_valid(stats_valid),.stats_ready(stats_ready),.stats_last(stats_last),
                .stats_data(stats_data),.replay_valid(replay_valid),.replay_ready(replay_ready),
                .replay_last(replay_last),.replay_data(replay_data),.replay_gamma(replay_gamma),
                .out_valid(out_valid),.out_ready(out_ready),.out_last(out_last),
                .out_fallback(out_fallback),.out_error(out_error),.out_tag(out_tag),
                .out_count(out_count),.out_channels(out_channels),.out_data(out_data),
                .req_valid(req_valid),.req_ready(req_ready),.req_address(req_address),
                .req_length(req_length),.rsp_valid(rsp_valid),.rsp_last(rsp_last),
                .rsp_error(rsp_error),.rsp_ready(rsp_ready),.rsp_data(rsp_data)
            );
        end
    endgenerate
    function automatic integer selected_row(input integer original);
        if(original/32==int'(groups[0])) selected_row=original%32;
        else if(original/32==int'(groups[1])) selected_row=32+original%32;
        else selected_row=-1;
    endfunction
    always @(posedge clk) begin: memory_model
        integer lane,original,row,column,index,phase,group_index,pair_index,feature;
        reg [63:0] cursor,offset;
        if(!rst_n) begin cycle<=0;model_active<=0;rsp_valid<=0;end
        else begin
            cycle<=cycle+1;
            if(req_valid && req_ready) begin
                if(req_length==0 || req_length>16 || req_address[2:0]!=0)
                    $fatal(1,"model fixture invalid request");
                address<=req_address;length<=int'(req_length);beats<=0;model_active<=1;
                requests=requests+1;
                if(HARDWARE_PREDICTION!=0 && req_address>=GATE_SIGN_BASE) begin
                    phase=req_address>=UP_SIGN_BASE?6:5;
                    offset=req_address-(phase==6?UP_SIGN_BASE:GATE_SIGN_BASE);
                    group_index=int'(offset/8192);pair_index=int'((offset%8192)/8);
                    row=selected_row(group_index*32);
                    feature=pair_index*2;
                    if(req_length!=1 || row<0 || feature>=2048 ||
                        !(($signed(normalized[feature])>768 || $signed(normalized[feature])< -768) ||
                          ($signed(normalized[feature+1])>768 || $signed(normalized[feature+1])< -768)))
                        $fatal(1,"model sign request outside selected outlier pairs");
                    sign_bytes=sign_bytes+8;
                end else if(req_address>=DOWN_BASE) down_bytes=down_bytes+int'(req_length)*8;
                else if(req_address>=UP_BASE) up_bytes=up_bytes+int'(req_length)*8;
                else if(req_address>=GATE_BASE) gate_bytes=gate_bytes+int'(req_length)*8;
                else activation_bytes=activation_bytes+int'(req_length)*8;
            end
            if(model_active && !rsp_valid && cycle%3!=0) begin
                rsp_valid<=1;rsp_last<=beats==length-1;
                if(HARDWARE_PREDICTION!=0 && address>=GATE_SIGN_BASE) begin
                    phase=address>=UP_SIGN_BASE?6:5;
                    offset=address-(phase==6?UP_SIGN_BASE:GATE_SIGN_BASE);
                    group_index=int'(offset/8192);pair_index=int'((offset%8192)/8);
                    for(integer half=0;half<2;half=half+1) begin
                        feature=pair_index*2+half;
                        for(integer channel=0;channel<32;channel=channel+1) begin
                            row=selected_row(group_index*32+channel);
                            if(row<0 || feature>=2048) $fatal(1,"model sign response outside fixture");
                            index=row*2048+feature;
                            rsp_data[half*32+channel]<=phase==6?up_weights[index][7]:gate_weights[index][7];
                        end
                    end
                end else for(lane=0;lane<8;lane=lane+1) begin
                    cursor=address+64'(beats*8+lane);
                    if(address>=DOWN_BASE) begin
                        offset=cursor-DOWN_BASE;row=int'(offset/5632)-int'(configuration[3]);
                        column=int'(offset%5632);
                        if(row<0 || row>=35) $fatal(1,"model down row outside configured outputs");
                        rsp_data[lane*8+:8]<=down_weights[row*5632+column];
                    end else if(address>=GATE_BASE) begin
                        phase=address>=UP_BASE?2:1;
                        offset=cursor-(phase==2?UP_BASE:GATE_BASE);
                        original=int'(offset/2048);column=int'(offset%2048);
                        row=selected_row(original);
                        if(row<0 || skip_channels[row]!=0) $fatal(1,"model fetched unselected or predicted-skipped row %0d",original);
                        index=row*2048+column;
                        rsp_data[lane*8+:8]<=phase==2?up_weights[index]:gate_weights[index];
                    end else begin
                        if(HARDWARE_PREDICTION==2) $fatal(1,"model cached top requested external activation");
                        offset=cursor-ACT_BASE;
                        if(cursor<ACT_BASE || offset>=2048) $fatal(1,"model activation stride outside2048 features");
                        rsp_data[lane*8+:8]<=activation[int'(offset)];
                    end
                end
            end
            if(rsp_valid && rsp_ready) begin
                rsp_valid<=0;
                if(rsp_last) model_active<=0;else beats<=beats+1;
            end
        end
    end
    always @(negedge clk) if(rst_n) out_ready=cycle%5!=0;
    always @(posedge clk) if(rst_n) begin: scoreboard
        integer lane,count;
        if(stalled && (!out_valid || {out_count,out_last,out_error,out_fallback,out_tag,out_channels,out_data}!==held))
            $fatal(1,"model output changed under backpressure");
        stalled=out_valid && !out_ready;
        held={out_count,out_last,out_error,out_fallback,out_tag,out_channels,out_data};
        if(out_valid && out_ready) begin
            count=35-received>32?32:35-received;
            if(out_error!==1'b0 || out_fallback!==1'b0 || out_tag!==32'h4d4f444c || out_count!==6'(count) || out_last!==(received+count==35))
                $fatal(1,"model result metadata mismatch");
            for(lane=0;lane<32;lane=lane+1) begin
                if(lane<count) begin
                    if(out_channels[lane*16+:16]!==16'(int'(configuration[3])+received+lane) ||
                       out_data[lane*32+:32]!==expected[received+lane])
                        $fatal(1,"model reference mismatch row=%0d got=%0d expected=%0d",received+lane,$signed(out_data[lane*32+:32]),$signed(expected[received+lane]));
                end else if(out_data[lane*32+:32]!==32'd0) $fatal(1,"nonzero padded output");
            end
            received=received+count;
        end
    end
    initial begin: stimulus
        integer group_index,strip,lane,row,timeout;
        fixture_override=$value$plusargs("FIXTURE_DIR=%s",fixture_directory);
        $readmemh({fixture_directory,"/configuration.hex"},configuration);
        if(HARDWARE_PREDICTION<2) $readmemh({fixture_directory,"/activation.hex"},activation);
        $readmemh({fixture_directory,"/gate.hex"},gate_weights);
        $readmemh({fixture_directory,"/up.hex"},up_weights);
        $readmemh({fixture_directory,"/down.hex"},down_weights);
        $readmemh({fixture_directory,"/norm.hex"},normalized);
        $readmemh({fixture_directory,"/expected.hex"},expected);
        $readmemh({fixture_directory,"/skip.hex"},skip_channels);
        $readmemh({fixture_directory,"/groups.hex"},groups);
        if(HARDWARE_PREDICTION!=0) begin
            $readmemh({fixture_directory,"/raw_residual.hex"},raw_residual);
            $readmemh({fixture_directory,"/epsilon_q16.hex"},epsilon);
        end
        if(HARDWARE_PREDICTION==2) begin
            $readmemh({fixture_directory,"/gamma.hex"},learned_gamma);
            $readmemh({fixture_directory,"/activation_shift.hex"},activation_shift);
        end
        for(row=0;row<64;row=row+1) if(skip_channels[row]!=0) skipped=skipped+1;
        repeat(2) @(negedge clk);rst_n=1;
        @(negedge clk);cfg_valid=1;
        @(posedge clk);if(!cfg_ready) $fatal(1,"model configuration blocked");
        @(negedge clk);cfg_valid=0;
        if(HARDWARE_PREDICTION==2) begin
            for(integer pass=0;pass<2;pass=pass+1) begin
                for(strip=0;strip<256;strip=strip+1) begin
                    @(negedge clk);
                    if(pass==0) begin stats_valid=1;stats_last=strip==255;end
                    else begin replay_valid=1;replay_last=strip==255;end
                    for(lane=0;lane<8;lane=lane+1) begin
                        stats_data[lane*16+:16]=raw_residual[strip*8+lane];
                        replay_data[lane*16+:16]=raw_residual[strip*8+lane];
                        replay_gamma[lane*16+:16]=learned_gamma[strip*8+lane];
                    end
                    timeout=0;@(posedge clk);
                    while((pass==0?stats_ready:replay_ready)!==1'b1 && timeout<300000) begin
                        @(posedge clk);timeout=timeout+1;end
                    if((pass==0?stats_ready:replay_ready)!==1'b1)
                        $fatal(1,"model cached preparation stalled");
                    @(negedge clk);stats_valid=0;replay_valid=0;
                    stats_data='1;replay_data='1;replay_gamma='1;
                end
            end
        end
        for(group_index=0;group_index<2;group_index=group_index+1) begin
            if(HARDWARE_PREDICTION!=0) begin
                @(negedge clk);group_valid=1;in_group=groups[group_index][10:0];
                in_group_last=group_index==1;timeout=0;@(posedge clk);
                while(!group_ready && timeout<300000) begin @(posedge clk);timeout=timeout+1;end
                if(!group_ready) $fatal(1,"model raw group stalled");
                @(negedge clk);group_valid=0;in_group='1;in_group_last=group_index!=1;
                if(HARDWARE_PREDICTION==1) for(integer pass=0;pass<2;pass=pass+1) begin
                    for(strip=0;strip<256;strip=strip+1) begin
                        @(negedge clk);
                        if(pass==0) begin stats_valid=1;stats_last=strip==255;end
                        else begin replay_valid=1;replay_last=strip==255;end
                        for(lane=0;lane<8;lane=lane+1) begin
                            stats_data[lane*16+:16]=raw_residual[strip*8+lane];
                            replay_data[lane*16+:16]=raw_residual[strip*8+lane];
                        end
                        timeout=0;@(posedge clk);
                        while((pass==0?stats_ready:replay_ready)!==1'b1 && timeout<300000) begin
                            @(posedge clk);timeout=timeout+1;end
                        if((pass==0?stats_ready:replay_ready)!==1'b1)
                            $fatal(1,"model raw residual stream stalled");
                        @(negedge clk);stats_valid=0;replay_valid=0;
                        stats_data='1;replay_data='1;
                    end
                end
            end else begin
            for(strip=0;strip<256;strip=strip+1) begin
                @(negedge clk);in_valid=1;in_last=strip==255;
                in_group=groups[group_index][10:0];in_group_last=group_index==1;
                for(lane=0;lane<8;lane=lane+1) begin
                    norm_activations[lane*16+:16]=normalized[strip*8+lane];
                    for(row=0;row<32;row=row+1) begin
                        gate_weight_signs[row*8+lane]=gate_weights[(group_index*32+row)*2048+strip*8+lane][7];
                        up_weight_signs[row*8+lane]=up_weights[(group_index*32+row)*2048+strip*8+lane][7];
                    end
                end
                timeout=0;@(posedge clk);
                while(!in_ready && timeout<300000) begin @(posedge clk);timeout=timeout+1;end
                if(!in_ready) $fatal(1,"model prediction frame stalled");
                @(negedge clk);in_valid=0;
            end
            end
        end
        timeout=0;
        while(received<35 && timeout<300000) begin @(negedge clk);timeout=timeout+1;end
        if(received!=35 || requests==0) $fatal(1,"model output missing");
        if(gate_bytes!==(64-skipped)*2048 || up_bytes!==(64-skipped)*2048)
            $fatal(1,"kept-row weight traffic does not match predicted mask");
        if(HARDWARE_PREDICTION==2 && activation_bytes!=0)
            $fatal(1,"model activation traffic was not served locally");
        $display("WEIGHT_TRAFFIC: gate_bytes=%0d up_bytes=%0d dense_bytes_per_matrix=131072 skipped_channels=%0d activation_bytes=%0d down_bytes=%0d",gate_bytes,up_bytes,skipped,activation_bytes,down_bytes);
        if(HARDWARE_PREDICTION!=0)
            $display("HARDWARE_PREDICTION_TRAFFIC: sign_bytes=%0d",sign_bytes);
        repeat(10) @(negedge clk);
        $display("PASS: pinned TinyLLaVA-v1 layer0-derived input,64 original channels,2048 features,5632 down stride,35 output sums; cycles=%0d requests=%0d",cycle,requests);
        $finish;
    end
    initial begin #6000000;$fatal(1,"model fixture watchdog");end
endmodule
