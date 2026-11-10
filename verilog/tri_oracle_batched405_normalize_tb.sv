`timescale 1ns/1ps
module tri_oracle_batched405_normalize_tb;
    localparam int TOKENS = 16;
    localparam int STRIPS = 256;
    localparam int FEATURES = STRIPS * 8;
    localparam int GROUPS = 176;
    localparam int PAIRS = STRIPS * 4;
    localparam int STRIDE = FEATURES + 64;
    localparam int BURSTS = TOKENS * STRIPS / 16;
    localparam logic [31:0] TAG = 32'h4050cafe;
    localparam logic [63:0] ACT_BASE = 64'h00000001fffff800;
    localparam logic [63:0] GATE_BASE = 64'h00000003ffffe000;
    localparam logic [63:0] UP_BASE = 64'h00000005ffffe000;

    logic clk = 0;
    always #5 clk = ~clk;
    logic rst_n = 0, cfg_valid = 0, done_ready = 0;
    wire cfg_ready, done_valid, done_error;
    wire [31:0] done_tag;
    logic [31:0] cfg_tag = 0;
    logic [4:0] cfg_tokens = 0;
    logic [9:0] cfg_strips = 0;
    logic [7:0] cfg_groups = 0;
    logic [31:0] cfg_epsilon_q16 = 0, cfg_activation_stride = 0;
    logic [63:0] cfg_gate_sign_base = 0, cfg_up_sign_base = 0, cfg_activation_base = 0;
    logic [95:0] cfg_activation_shifts = 0;
    logic stats_valid = 0, stats_last = 0, replay_valid = 0, replay_last = 0;
    logic [127:0] stats_data = 0, replay_data = 0, replay_gamma = 0;
    wire stats_ready, replay_ready;
    wire [3:0] residual_token;
    logic out_ready = 0;
    wire out_valid, out_last;
    wire [31:0] out_tag, gate_nearzero_mask, up_nearzero_mask, skip_mask;
    wire [7:0] out_group;
    wire [3:0] out_token;
    wire [12:0] outlier_count;
    wire req_valid, rsp_ready;
    wire [63:0] req_address;
    wire [4:0] req_length;
    logic rsp_valid = 0;
    logic [63:0] rsp_data = 0;
    wire wr_req_valid, wr_data_valid, wr_data_last, wr_rsp_ready;
    wire [63:0] wr_address, wr_data;
    wire [4:0] wr_length;
    wire [7:0] wr_strobe;
    logic write_active = 0, wr_rsp_valid = 0;
    int ack_delay = 0, cycle = 0;
    wire req_ready = !rsp_valid && cycle % 7 >= 3;
    wire wr_req_ready = !write_active && !wr_rsp_valid && ack_delay == 0 && cycle % 7 >= 4;
    wire wr_data_ready = write_active && cycle % 5 != 0;
    int fault, group_limit, frame_tokens, frame_strips;
    int write_requests, written_words, committed_words, sign_requests, burst_words, burst_seen;
    int read_token, read_group, read_pair, normalizer_starts, masks_seen;
    bit inject_fault, read_up, failed_ack, held_write_req, held_write_data;
    logic [68:0] prior_write_req;
    logic [72:0] prior_write_data;
    wire wr_rsp_error = inject_fault && ((fault == 1 && write_requests == 1) ||
                                         (fault == 2 && write_requests == BURSTS));
    logic [127:0] raw_words [TOKENS * STRIPS];
    logic [15:0] gamma_words [FEATURES], expected_counts [TOKENS];
    logic [7:0] expected_activation [TOKENS * FEATURES], shifts [TOKENS];
    logic [63:0] gate_words [GROUPS * PAIRS], up_words [GROUPS * PAIRS];
    logic [95:0] branch_masks [TOKENS * GROUPS];
    logic [PAIRS-1:0] outlier_pairs [TOKENS];
    string input_dir, activation_dir;

    tri_oracle_batched_normalize405 dut (.rsp_last(rsp_valid), .rsp_error(1'b0), .strip_request(), .strip_response('0), .*);

    always @(posedge clk) if (rst_n) begin : memory_peer
        int index, left_in_token;
        logic [63:0] wanted;
        cycle <= cycle + 1;
        if (dut.activation_path.cfg_valid && dut.activation_path.cfg_ready) normalizer_starts++;
        if (held_write_req && (!wr_req_valid || {wr_address, wr_length} !== prior_write_req))
            $fatal(1, "BATCH405_WRITE_REQUEST_CHANGED");
        held_write_req = wr_req_valid && !wr_req_ready;
        prior_write_req = {wr_address, wr_length};
        if (held_write_data && (!wr_data_valid || {wr_data, wr_strobe, wr_data_last} !== prior_write_data))
            $fatal(1, "BATCH405_WRITE_DATA_CHANGED");
        held_write_data = wr_data_valid && !wr_data_ready;
        prior_write_data = {wr_data, wr_strobe, wr_data_last};
        if (wr_req_valid && wr_req_ready) begin
            wanted = ACT_BASE + 64'(written_words / frame_strips) * STRIDE + 64'(written_words % frame_strips) * 8;
            left_in_token = frame_strips - written_words % frame_strips;
            burst_words = left_in_token < 16 ? left_in_token : 16;
            burst_seen = 0;
            if ((written_words % frame_strips) % 16 != 0 || wr_length !== 5'(burst_words) || wr_address !== wanted)
                $fatal(1, "BATCH405_WRITE_ADDRESS index=%0d got=%h expected=%h", written_words, wr_address, wanted);
            write_active <= 1;
            write_requests++;
        end
        if (wr_data_valid && wr_data_ready) begin
            if (wr_strobe !== 8'hff || wr_data_last !== (burst_seen + 1 == burst_words))
                $fatal(1, "BATCH405_WRITE_METADATA");
            for (int lane = 0; lane < 8; lane++)
                if (wr_data[8*lane +: 8] !== (fault==4 ? 8'd64 : expected_activation[written_words*8 + lane]))
                    $fatal(1, "BATCH405_ACTIVATION_BYTE index=%0d lane=%0d", written_words, lane);
            written_words++;
            burst_seen++;
            if (wr_data_last) begin write_active <= 0; ack_delay <= 6; end
        end
        if (ack_delay != 0) begin
            ack_delay <= ack_delay - 1;
            if (ack_delay == 1) wr_rsp_valid <= 1;
        end
        if (wr_rsp_valid && wr_rsp_ready) begin
            wr_rsp_valid <= 0;
            if (wr_rsp_error) failed_ack = 1;
            else committed_words += burst_words;
        end
        if (rsp_valid && rsp_ready) rsp_valid <= 0;
        if (req_valid && req_ready) begin
            if (fault==4 || committed_words != frame_tokens * frame_strips || inject_fault || read_group >= group_limit)
                $fatal(1, "BATCH405_SIGN_BEFORE_COMMIT");
            while (read_pair < PAIRS && !outlier_pairs[read_token][read_pair]) read_pair++;
            if (read_pair == PAIRS) $fatal(1, "BATCH405_EXTRA_SIGN");
            index = read_group * PAIRS + read_pair;
            wanted = (read_up ? UP_BASE : GATE_BASE) + 64'(index) * 8;
            if (req_address !== wanted || req_length !== 5'd1)
                $fatal(1, "BATCH405_SIGN_ADDRESS got=%h expected=%h", req_address, wanted);
            rsp_data <= read_up ? up_words[index] : gate_words[index];
            rsp_valid <= 1;
            if (read_up) begin
                read_pair++;
                while (read_pair < PAIRS && !outlier_pairs[read_token][read_pair]) read_pair++;
                if (read_pair == PAIRS) begin
                    read_pair = 0;
                    if (read_token == TOKENS - 1) begin read_token = 0; read_group++; end
                    else read_token++;
                end
            end
            read_up = !read_up;
            sign_requests++;
        end
        if (inject_fault && out_valid) $fatal(1, "BATCH405_FAULT_PUBLISHED_MASK");
    end

    task automatic configure;
        @(negedge clk);
        write_requests=0; written_words=0; committed_words=0; sign_requests=0;
        read_token=0; read_group=0; read_pair=0; read_up=0;
        normalizer_starts=0; masks_seen=0; failed_ack=0;
        cfg_tag=TAG; cfg_tokens=5'(frame_tokens); cfg_strips=10'(frame_strips); cfg_groups=8'(group_limit);
        cfg_gate_sign_base=GATE_BASE; cfg_up_sign_base=UP_BASE;
        cfg_activation_base=ACT_BASE; cfg_activation_stride=STRIDE; cfg_epsilon_q16=32'd43980465;
        for (int token = 0; token < frame_tokens; token++)
            cfg_activation_shifts[6*token +: 6]=fault==4 ? 6'd15 : shifts[token][5:0];
        cfg_valid=1;
        @(posedge clk);
        if (cfg_ready !== 1'b1) $fatal(1, "BATCH405_CONFIG");
        @(negedge clk);
        cfg_valid=0; cfg_tag='1; cfg_tokens='1; cfg_strips='1; cfg_groups='1;
        cfg_gate_sign_base='1; cfg_up_sign_base='1;
        cfg_activation_base='1; cfg_activation_stride='1; cfg_epsilon_q16='1; cfg_activation_shifts='1;
    endtask

    task automatic send_frame;
        for (int token = 0; token < frame_tokens; token++) begin
            for (int strip = 0; strip < frame_strips; strip++) begin
                stats_valid=1; stats_last=strip==frame_strips-1;
                stats_data=fault==4 ? {8{16'd8192}} : raw_words[token*STRIPS+strip];
                while (!stats_ready) begin
                    if (done_valid) begin stats_valid=0; return; end
                    @(negedge clk);
                end
                @(posedge clk);
                if (residual_token !== 4'(token)) $fatal(1, "BATCH405_STATS_TOKEN");
                @(negedge clk);
            end
            stats_valid=0; stats_data='1;
            for (int strip = 0; strip < frame_strips; strip++) begin
                replay_valid=1; replay_last=strip==frame_strips-1;
                replay_data=fault==4 ? {8{16'd8192}} : raw_words[token*STRIPS+strip];
                if (inject_fault && fault==3 && token==0 && replay_last) replay_data[15:0]=16'sd32000;
                for (int lane = 0; lane < 8; lane++)
                    replay_gamma[16*lane +: 16]=fault==4 ? 16'd8192 : gamma_words[strip*8+lane];
                while (!replay_ready) begin
                    if (done_valid) begin replay_valid=0; return; end
                    @(negedge clk);
                end
                @(posedge clk);
                if (residual_token !== 4'(token)) $fatal(1, "BATCH405_REPLAY_TOKEN");
                @(negedge clk);
            end
            replay_valid=0; replay_data='1; replay_gamma='x;
        end
    endtask

    task automatic receive_masks;
        logic [95:0] expected;
        for (int group_index = 0; group_index < group_limit; group_index++)
            for (int token = 0; token < frame_tokens; token++) begin
                expected=fault==4 ? '0 : branch_masks[token*GROUPS+group_index];
                while (out_valid !== 1'b1) begin
                    if (done_valid) $fatal(1, "BATCH405_EARLY_DONE");
                    @(negedge clk);
                end
                repeat (4) begin
                    if (out_valid !== 1'b1 || out_tag !== TAG || out_group !== 8'(group_index) ||
                        out_token !== 4'(token) || out_last !== (token==frame_tokens-1 && group_index==group_limit-1) ||
                        {gate_nearzero_mask,up_nearzero_mask,skip_mask} !== expected ||
                        outlier_count !== (fault==4 ? 13'd0 : 13'(expected_counts[token])))
                        $fatal(1, "BATCH405_MASK token=%0d group=%0d", token, group_index);
                    @(negedge clk);
                end
                out_ready=1;
                @(negedge clk);
                out_ready=0;
                masks_seen++;
            end
    endtask

    task automatic finish_frame(input bit expected_error);
        while (done_valid !== 1'b1) @(negedge clk);
        repeat (4) begin
            if (!done_valid || done_error !== expected_error || done_tag !== TAG ||
                cfg_ready || req_valid || rsp_valid || wr_req_valid || wr_data_valid ||
                wr_rsp_valid || write_active || ack_delay!=0 || out_valid)
                $fatal(1, "BATCH405_TERMINAL");
            @(negedge clk);
        end
        done_ready=1;
        @(negedge clk);
        done_ready=0;
        if (!cfg_ready) $fatal(1, "BATCH405_OWNER_NOT_RELEASED");
    endtask

    initial begin : stimulus
        int wanted_reads, wanted_bursts;
        if (!$value$plusargs("INPUT=%s",input_dir) || !$value$plusargs("EXPECTED=%s",activation_dir))
            $fatal(1,"BATCH405_FIXTURES_REQUIRED");
        if (!$value$plusargs("FAULT=%d",fault)) fault=0;
        group_limit=fault==0 ? GROUPS : 2;
        frame_tokens=fault==4 ? 2 : TOKENS;
        frame_strips=fault==4 ? 17 : STRIPS;
        $readmemh({input_dir,"/raw.hex"},raw_words);
        $readmemh({input_dir,"/gate_sign.hex"},gate_words);
        $readmemh({input_dir,"/up_sign.hex"},up_words);
        $readmemh({input_dir,"/branch_masks.hex"},branch_masks);
        $readmemh({input_dir,"/outlier_pairs.hex"},outlier_pairs);
        $readmemh({input_dir,"/outlier_counts.hex"},expected_counts);
        $readmemh({activation_dir,"/gamma.hex"},gamma_words);
        $readmemh({activation_dir,"/activation.hex"},expected_activation);
        $readmemh({activation_dir,"/shifts.hex"},shifts);
        repeat (3) @(negedge clk);
        rst_n=1;
        if (fault>0 && fault<4) begin
            inject_fault=1;
            configure();
            send_frame();
            finish_frame(1);
            if (sign_requests!=0 || masks_seen!=0 ||
                (fault==1 && (!failed_ack || write_requests!=1 || committed_words!=0 || normalizer_starts!=1)) ||
                (fault==2 && (!failed_ack || write_requests!=BURSTS || committed_words!=TOKENS*STRIPS-16 ||
                              normalizer_starts!=TOKENS)) ||
                (fault==3 && (failed_ack || write_requests!=STRIPS/16-1 || committed_words!=STRIPS-16 ||
                              normalizer_starts!=1)))
                $fatal(1,"BATCH405_FAULT_INVENTORY");
            $display("BATCH405_FAULT_DRAINED fault=%0d committed_words=%0d sign_reads=0",fault,committed_words);
            inject_fault=0;
        end
        configure();
        fork send_frame(); receive_masks(); join
        finish_frame(0);
        wanted_reads=0;
        if (fault!=4)
            for (int token=0;token<frame_tokens;token++) wanted_reads+=2*group_limit*$countones(outlier_pairs[token]);
        wanted_bursts=frame_tokens*((frame_strips+15)/16);
        if (normalizer_starts!=frame_tokens || write_requests!=wanted_bursts || written_words!=frame_tokens*frame_strips ||
            committed_words!=written_words || sign_requests!=wanted_reads ||
            read_group!=(fault==4 ? 0 : group_limit) || read_token!=0 || read_up || masks_seen!=frame_tokens*group_limit)
            $fatal(1,"BATCH405_FINAL_INVENTORY");
        $display("BATCH405_PASS fault=%0d normalizations=%0d activation_bytes=%0d writes=%0d mask_bits=%0d sign_reads=%0d",
            fault,normalizer_starts,committed_words*8,write_requests,masks_seen*32,sign_requests);
        $finish;
    end

    initial begin #40000000; $fatal(1,"BATCH405_WATCHDOG"); end
endmodule
