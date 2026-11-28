`timescale 1ns/1ps
`default_nettype none

// Test-only shared fixture. The tensor-dot boundary uses two captured trained
// rows; rotary/recode, acknowledged writer, membership and reads are actual RTL.
// External storage is updated ONLY by successful actual write responses.
module tri_oracle_qkv_cache_path_fixture_v1 (
    input wire logic clk, rst_n, start, cancel,
    input wire logic [31:0] start_tag, start_generation,
    input wire logic [15:0] start_epoch,
    input wire logic [3:0] scenario,
    output logic initialized,
    output wire logic committed, busy, fault, reset_required,
    input wire logic retire_valid,
    output wire logic retire_ready,
    input wire logic read_valid,
    output wire logic read_ready,
    input wire logic [31:0] read_tag, read_generation,
    input wire logic [4:0] read_layer,
    input wire logic [15:0] read_epoch,
    input wire logic [5:0] read_head,
    input wire logic [9:0] read_slot,
    output wire logic read_result_valid,
    input wire logic read_result_ready,
    output wire logic read_result_error,
    output wire logic [31:0] read_result_tag, read_result_generation,
    output wire logic [4:0] read_result_layer,
    output wire logic [15:0] read_result_epoch,
    output wire logic [5:0] read_result_head,
    output wire logic [9:0] read_result_slot,
    output wire logic signed [8:0] read_result_unit,
    output wire logic [511:0] read_result_data,
    output logic finished, finished_error
);
    localparam logic [63:0] ACTIVATION_BASE=64'h10000000, WEIGHT_BASE=64'h20000000;
    localparam logic [63:0] CACHE_BASE=64'h30000000, CACHE_BYTES=64'd2621440;
    string fixture_dir;
    logic [2047:0] raw_vectors[80];
    logic [511:0] expected_vectors[80], cosine[2], sine[2];
    logic [359:0] configuration[3];
    logic [511:0] storage[80];
    logic storage_valid[80];
    logic [31:0] tag, generation;
    logic [15:0] epoch;
    logic [3:0] mode;
    logic started, cfg_valid, cfg_ready, cfg_seen, angle_owned;
    logic angle_valid, angle_ready;
    logic tensor_cfg_valid, tensor_cfg_ready;
    logic [31:0] tensor_cfg_tag;
    logic [4:0] tensor_cfg_tokens;
    logic [7:0] tensor_cfg_count;
    logic [2559:0] tensor_cfg_channels, tensor_cfg_keep;
    logic [63:0] tensor_cfg_activation_base, tensor_cfg_weight_base;
    logic tensor_out_valid, tensor_out_ready, tensor_out_last;
    logic [31:0] tensor_out_tag;
    logic [3:0] tensor_out_token;
    logic [7:0] tensor_out_count;
    logic [2559:0] tensor_out_channels;
    logic [4095:0] tensor_out_data;
    logic tensor_done_valid, tensor_done_ready;
    logic [31:0] held_tensor_tag;
    logic [2559:0] held_channels;
    integer angle_index, tensor_state, tensor_token, tensor_head, tensor_delay;
    integer cycles, tensor_jobs, tensor_packets, write_requests, write_acks, read_headers;
    logic write_valid, write_ready, write_rsp_valid, write_rsp_error, write_rsp_ready;
    logic [63:0] write_address;
    logic [511:0] write_data, pending_write_data;
    logic [4:0] write_length;
    logic write_pending;
    integer write_delay, pending_write_index;
    logic [63:0] pending_write_address;
    logic memory_read_valid, memory_read_ready, memory_rsp_valid, memory_rsp_ready;
    logic memory_rsp_last, memory_rsp_error;
    logic [63:0] memory_read_address, memory_rsp_data;
    logic [4:0] memory_read_length;
    logic read_pending, inject_read_error;
    logic logical_read_pending, logical_read_valid, logical_memory_issued;
    logic [5:0] logical_head;
    logic [9:0] logical_slot;
    logic [511:0] read_payload;
    integer memory_beat, memory_delay;
    logic done_valid, done_ready, done_error;
    logic [31:0] done_tag, done_generation;
    logic [9:0] committed_first_slot;
    logic [4:0] committed_tokens;
    integer done_stalls;
    logic done_ack_seen, reported;
    logic prior_write_stall, prior_read_stall, prior_done_stall;
    logic [580:0] held_write;
    logic [622:0] held_read;
    logic [64:0] held_done;

    task automatic check(input logic condition, input string message);
        if (condition !== 1'b1)
            $fatal(1,"QKV_CACHE_PATH_ASSERT cycle=%0d scenario=%0d %s",cycles,mode,message);
    endtask
    function automatic integer storage_index(input logic [63:0] address);
        logic [63:0] offset;
        integer head, slot;
        if ($isunknown(address) || address<CACHE_BASE || address>=CACHE_BASE+CACHE_BYTES) return -1;
        offset=address-CACHE_BASE;head=int'(offset/65536);slot=int'((offset%65536)/64);
        if (offset%64!=0 || head>=40 || slot>=2) return -1;
        return head*2+slot;
    endfunction

    initial begin
        initialized=0;
        if (!$value$plusargs("QKV_FIXTURE_DIR=%s",fixture_dir))
            $fatal(1,"+QKV_FIXTURE_DIR=<closed two-slot trained fixture> required");
        $readmemh({fixture_dir,"/raw32.hex"},raw_vectors);
        $readmemh({fixture_dir,"/expected.hex"},expected_vectors);
        $readmemh({fixture_dir,"/cos.hex"},cosine);
        $readmemh({fixture_dir,"/sin.hex"},sine);
        $readmemh({fixture_dir,"/config.hex"},configuration);
        foreach (raw_vectors[i]) check(!$isunknown({raw_vectors[i],expected_vectors[i]}),"complete trained raw/expected vectors");
        foreach (cosine[i]) check(!$isunknown({cosine[i],sine[i]}),"complete captured rotary coefficients");
        foreach (configuration[i]) check(!$isunknown(configuration[i]),"complete typed shift/unit metadata");
        initialized=1;
    end

    assign tensor_cfg_ready=rst_n && tensor_state==0 && cycles%5!=1;
    assign tensor_out_valid=tensor_state==1 && tensor_delay==0;
    assign tensor_out_last=tensor_token==1;
    assign tensor_out_tag=held_tensor_tag ^ ((mode==1 && tensor_jobs==1 && tensor_token==0)?32'd1:32'd0);
    assign tensor_out_token=4'(tensor_token);
    assign tensor_out_count=8'd128;
    assign tensor_out_channels=held_channels;
    assign tensor_out_data={raw_vectors[(tensor_head+1)*2+tensor_token],raw_vectors[tensor_head*2+tensor_token]};
    assign tensor_done_valid=tensor_state==2;
    assign write_ready=rst_n && !write_pending && !write_rsp_valid && cycles%7!=2;
    assign memory_read_ready=rst_n && !read_pending && !memory_rsp_valid && cycles%6!=1;
    assign memory_rsp_last=memory_beat==7;
    assign memory_rsp_data=read_payload[memory_beat*64+:64];
    assign memory_rsp_error=inject_read_error && memory_beat==3;

    tri_oracle_attention_post_qkv_path_v1 dut (
        .clk,.rst_n,.cancel,.cfg_valid,.cfg_ready,.cfg_tag(tag),.cfg_generation(generation),
        .cfg_layer(5'd19),.cfg_tokens(5'd2),.cfg_epoch(epoch),.cfg_slot(10'd0),
        .cfg_activation_base(ACTIVATION_BASE),.cfg_activation_bytes(64'd4096),
        .cfg_weight_base(WEIGHT_BASE),.cfg_weight_bytes(64'd5242880),
        .cfg_cache_base(CACHE_BASE),.cfg_cache_bytes(mode==7?64'd0:CACHE_BYTES),
        .cfg_shifts(configuration[0][239:0]),.cfg_shift_biases(configuration[1][95:0]),
        .cfg_head_units(configuration[2]),.angle_valid,.angle_last(angle_index==1),.angle_ready,
        .angle_cos(cosine[angle_index%2]),.angle_sin(sine[angle_index%2]),
        .tensor_cfg_valid,.tensor_cfg_ready,.tensor_cfg_tag,.tensor_cfg_tokens,.tensor_cfg_count,
        .tensor_cfg_channels,.tensor_cfg_keep,.tensor_cfg_activation_base,.tensor_cfg_weight_base,
        .tensor_out_valid,.tensor_out_last,.tensor_out_ready,.tensor_out_tag,.tensor_out_token,.tensor_out_count,
        .tensor_out_channels,.tensor_out_data,.tensor_done_valid,.tensor_done_error(1'b0),.tensor_done_ready,.tensor_done_tag(held_tensor_tag),
        .cache_write_valid(write_valid),.cache_write_ready(write_ready),.cache_write_address(write_address),
        .cache_write_data(write_data),.cache_write_length(write_length),.cache_write_rsp_valid(write_rsp_valid),
        .cache_write_rsp_error(write_rsp_error),.cache_write_rsp_ready(write_rsp_ready),
        .done_valid,.done_error,.done_ready,.done_tag,.done_generation,.committed_valid(committed),
        .committed_first_slot,.committed_tokens,.retire_valid,.retire_ready,
        .read_valid,.read_ready,.read_tag,.read_generation,.read_layer,.read_epoch,.read_head,.read_slot,
        .read_result_valid,.read_result_ready,.read_result_error,.read_result_tag,.read_result_generation,
        .read_result_layer,.read_result_epoch,.read_result_head,.read_result_slot,.read_result_unit,.read_result_data,
        .memory_read_valid,.memory_read_ready,.memory_read_address,.memory_read_length,
        .memory_rsp_valid,.memory_rsp_last,.memory_rsp_error,.memory_rsp_data,.memory_rsp_ready,
        .fault,.reset_required,.busy
    );

    always @(posedge clk) begin : models_and_observers
        integer head, token, index;
        if (!rst_n) begin
            cycles<=0;tag<=0;generation<=0;epoch<=0;mode<=0;started<=0;
            cfg_valid<=0;cfg_seen<=0;angle_owned<=0;angle_valid<=0;angle_index<=0;
            tensor_state<=0;tensor_token<=0;tensor_head<=0;tensor_delay<=0;
            held_tensor_tag<=0;held_channels<=0;tensor_jobs<=0;tensor_packets<=0;
            write_pending<=0;write_rsp_valid<=0;write_rsp_error<=0;write_delay<=0;
            pending_write_index<=0;pending_write_data<=0;pending_write_address<=0;write_requests<=0;write_acks<=0;
            read_pending<=0;memory_rsp_valid<=0;memory_beat<=0;memory_delay<=0;read_payload<=0;inject_read_error<=0;read_headers<=0;
            logical_read_pending<=0;logical_read_valid<=0;logical_memory_issued<=0;logical_head<=0;logical_slot<=0;
            done_ready<=0;done_stalls<=0;done_ack_seen<=0;reported<=0;finished<=0;finished_error<=0;
            prior_write_stall<=0;prior_read_stall<=0;prior_done_stall<=0;held_write<=0;held_read<=0;held_done<=0;
            foreach (storage_valid[i]) begin storage_valid[i]<=0;storage[i]<=0;end
        end else begin
            cycles<=cycles+1;check(cycles<2000000,"bounded fixture progress");
            if (start===1'b1) begin
                check(initialized && !started && !$isunknown({start_tag,start_generation,start_epoch,scenario}),"one known start generation");
                started<=1;tag<=start_tag;generation<=start_generation;epoch<=start_epoch;mode<=scenario;cfg_valid<=1;
            end
            if (cfg_valid && cfg_ready) begin cfg_valid<=0;cfg_seen<=1;end
            if (cfg_seen && angle_ready) angle_owned<=1;
            if (angle_valid && angle_ready) begin angle_valid<=0;angle_index<=angle_index+1;end
            else if (!angle_valid && angle_owned && angle_index<2 && cycles%4!=1) angle_valid<=1;
            if (tensor_cfg_valid && tensor_cfg_ready) begin
                check(tensor_jobs<20 && tensor_cfg_tag===tag && tensor_cfg_tokens===5'd2 && tensor_cfg_count===8'd128,
                      "actual two-head/two-token tensor job");
                check(tensor_cfg_activation_base===ACTIVATION_BASE && tensor_cfg_weight_base===WEIGHT_BASE
                      && tensor_cfg_keep==='1,"actual operand bases and resident keep mask");
                for (int lane=0;lane<160;lane++)
                    check(tensor_cfg_channels[lane*16+:16] === (lane<128?16'(tensor_jobs*128+lane):16'd0),"exact output channel IDs/padding");
                held_tensor_tag<=tensor_cfg_tag;held_channels<=tensor_cfg_channels;
                tensor_head<=tensor_jobs*2;tensor_token<=0;tensor_delay<=2;tensor_state<=1;tensor_jobs<=tensor_jobs+1;
            end
            if (tensor_state==1 && tensor_delay>0) tensor_delay<=tensor_delay-1;
            if (tensor_out_valid && tensor_out_ready) begin
                tensor_packets<=tensor_packets+1;
                if (tensor_token==1) tensor_state<=2;
                else begin tensor_token<=1;tensor_delay<=2;end
            end
            if (tensor_done_valid && tensor_done_ready) tensor_state<=0;
            if (write_valid && write_ready) begin
                head=(write_requests/4)*2+write_requests%2;token=(write_requests%4)/2;
                index=storage_index(write_address);
                check(!write_pending && write_requests<80 && write_length===5'd8
                      && write_address===CACHE_BASE+64'(head)*65536+64'(token)*64,"exact actual writer address/order/range");
                check(index==head*2+token && write_data===expected_vectors[index],"all actual rotary/recode bytes independently checked");
                pending_write_index<=index;pending_write_data<=write_data;pending_write_address<=write_address;
                write_pending<=1;write_delay<=2+write_requests%3;write_rsp_error<=mode==2 && write_requests==2;
                write_requests<=write_requests+1;
            end
            if (write_pending && !write_rsp_valid) begin
                if (write_delay>0) write_delay<=write_delay-1;
                else write_rsp_valid<=1;
            end
            if (write_rsp_valid && write_rsp_ready) begin
                check(write_pending,"response has actual owned header");
                if (!write_rsp_error) begin
                    storage[pending_write_index]<=pending_write_data;storage_valid[pending_write_index]<=1;
                    $display("QKV_CACHE_WRITE_ACK index=%0d head=%0d slot=%0d address=%016h generation=%08h data=%0128h",
                             write_acks,pending_write_index/2,pending_write_index%2,pending_write_address,generation,pending_write_data);
                end
                write_acks<=write_acks+1;write_rsp_valid<=0;write_pending<=0;
            end
            if (read_valid && read_ready) begin
                check(!logical_read_pending,"one public logical cache read owner");
                logical_read_pending<=1;logical_memory_issued<=0;logical_head<=read_head;logical_slot<=read_slot;
                logical_read_valid<=!$isunknown({read_tag,read_generation,read_layer,read_epoch,read_head,read_slot})
                    && read_generation===generation && read_layer===5'd19 && read_epoch===epoch && read_head<40 && read_slot<2;
            end
            if (memory_read_valid && memory_read_ready) begin
                index=storage_index(memory_read_address);
                check(committed && logical_read_pending && logical_read_valid && !logical_memory_issued
                      && memory_read_address===CACHE_BASE+64'(logical_head)*65536+64'(logical_slot)*64
                      && index>=0 && storage_valid[index] && memory_read_length===5'd8,
                      "physical read exactly matches accepted public head/slot and acknowledged storage");
                logical_memory_issued<=1;
                $display("QKV_CACHE_MEMORY_RQ index=%0d head=%0d slot=%0d address=%016h length=8 generation=%08h",
                         read_headers,logical_head,logical_slot,memory_read_address,generation);
                read_payload<=storage[index];read_pending<=1;memory_beat<=0;memory_delay<=2;
                inject_read_error<=mode==3 && read_headers==1;read_headers<=read_headers+1;
            end
            if (read_pending && !memory_rsp_valid) begin
                if (memory_delay>0) memory_delay<=memory_delay-1;
                else memory_rsp_valid<=1;
            end
            if (memory_rsp_valid && memory_rsp_ready) begin
                memory_rsp_valid<=0;
                if (memory_beat==7) read_pending<=0;
                else begin memory_beat<=memory_beat+1;memory_delay<=1+memory_beat%2;end
            end
            if (read_result_valid && read_result_ready) begin
                check(logical_read_pending,"actual reply has one accepted logical owner");
                if (!read_result_error) check(logical_read_valid && logical_memory_issued
                    && read_result_head===logical_head && read_result_slot===logical_slot,
                    "healthy reply follows matching physical read");
                logical_read_pending<=0;
            end
            if (done_valid && !done_ready) begin
                done_stalls<=done_stalls+1;
                if (done_stalls==7) done_ready<=1;
            end
            if (done_valid && done_ready) begin
                check(done_tag===tag && done_generation===generation && done_stalls>=8,"actual held Done identity/ACK");
                finished<=1;finished_error<=done_error;done_ack_seen<=1;
                if (!done_error) check(write_requests==80 && write_acks==80 && !write_pending
                    && tensor_jobs==20 && tensor_packets==40 && angle_index==2,"complete trained producer and 80 actual ACKs before success");
            end
            if (committed) begin
                check(done_ack_seen && !finished_error && committed_first_slot===10'd0 && committed_tokens===5'd2
                      && write_requests==80 && write_acks==80,"one actual committed generation");
                if (!reported) begin
                    $display("QKV_CACHE_GENERATION_COMMITTED tag=%08h generation=%08h layer=19 epoch=%04h writes=80 acks=80 tensor_packets=40 jobs=20 angles=2",tag,generation,epoch);
                    reported<=1;
                end
            end
            if (prior_write_stall) check(write_valid && {write_address,write_data,write_length}===held_write,"held physical write offer");
            if (prior_read_stall) check(read_result_valid && {read_result_tag,read_result_generation,read_result_layer,
                read_result_epoch,read_result_head,read_result_slot,read_result_unit,read_result_data,read_result_error}===held_read,"held actual read result");
            if (prior_done_stall) check(done_valid && {done_tag,done_generation,done_error}===held_done,"held actual Done tuple");
            prior_write_stall<=write_valid && !write_ready;held_write<={write_address,write_data,write_length};
            prior_read_stall<=read_result_valid && !read_result_ready;
            held_read<={read_result_tag,read_result_generation,read_result_layer,read_result_epoch,read_result_head,read_result_slot,read_result_unit,read_result_data,read_result_error};
            prior_done_stall<=done_valid && !done_ready;held_done<={done_tag,done_generation,done_error};
        end
    end
endmodule

// Standalone finite component exerciser. Joined tests instantiate the fixture
// above and connect the SAME actual cache read port to their actual broker.
module qkv_cache_path_tb;
    logic clk=0, rst_n=0, start=0, cancel=0, retire_valid=0;
    logic initialized,committed,busy,fault,reset_required,retire_ready,finished,finished_error;
    logic read_valid=0,read_ready,read_result_valid,read_result_ready=0,read_result_error;
    logic [31:0] read_tag=32'h8d2c0000,read_generation=32'h19000001,read_result_tag,read_result_generation;
    logic [4:0] read_layer=5'd19,read_result_layer;
    logic [15:0] read_epoch=16'h42f1,read_result_epoch;
    logic [5:0] read_head=0,read_result_head;
    logic [9:0] read_slot=0,read_result_slot;
    logic signed [8:0] read_result_unit;
    logic [511:0] read_result_data;
    logic [3:0] scenario;
    integer selected_case;
    tri_oracle_qkv_cache_path_fixture_v1 fixture (
        .clk,.rst_n,.start,.cancel,.start_tag(32'h8d2c0000),.start_generation(32'h19000001),.start_epoch(16'h42f1),
        .scenario,.initialized,.committed,.busy,.fault,.reset_required,.retire_valid,.retire_ready,
        .read_valid,.read_ready,.read_tag,.read_generation,.read_layer,.read_epoch,.read_head,.read_slot,
        .read_result_valid,.read_result_ready,.read_result_error,.read_result_tag,.read_result_generation,
        .read_result_layer,.read_result_epoch,.read_result_head,.read_result_slot,.read_result_unit,.read_result_data,
        .finished,.finished_error
    );
    always #5 clk=~clk;
    task automatic check(input logic condition,input string message);
        if (condition!==1'b1) $fatal(1,"QKV_CACHE_COMPONENT_ASSERT case=%0d %s",selected_case,message);
    endtask
    task automatic fetch(input integer head,slot,input logic expect_error);
        logic [622:0] snapshot;
        @(negedge clk);read_head=6'(head);read_slot=10'(slot);read_valid=1;
        do @(posedge clk);while (read_ready!==1'b1);
        @(negedge clk);read_valid=0;
        wait(read_result_valid===1'b1);#1ps;
        check(read_result_error===expect_error,"known read result status");
        if (!expect_error) begin
            check({read_result_tag,read_result_generation,read_result_layer,read_result_epoch,read_result_head,read_result_slot}
                  ==={read_tag,read_generation,read_layer,read_epoch,6'(head),10'(slot)},"exact read identity");
            check(read_result_unit===$signed(fixture.configuration[2][head*9+:9])
                  && read_result_data===fixture.expected_vectors[head*2+slot],"exact cached bytes and signed9 unit");
        end
        snapshot={read_result_tag,read_result_generation,read_result_layer,read_result_epoch,read_result_head,read_result_slot,read_result_unit,read_result_data,read_result_error};
        repeat(4) begin @(posedge clk);#1ps;check(read_result_valid && {read_result_tag,read_result_generation,
            read_result_layer,read_result_epoch,read_result_head,read_result_slot,read_result_unit,read_result_data,read_result_error}===snapshot,"response held under stall");end
        @(negedge clk);retire_valid=1;#1ps;check(retire_ready===1'b0,"read reply fences retire");
        @(negedge clk);retire_valid=0;read_result_ready=1;
        @(posedge clk);@(negedge clk);read_result_ready=0;
    endtask
    initial begin
        selected_case=0;
        if ($value$plusargs("CASE=%d",selected_case)) begin end
        check(selected_case>=0 && selected_case<=7,"declared finite case");scenario=4'(selected_case);
        wait(initialized);repeat(4) @(posedge clk);@(negedge clk);rst_n=1;
        repeat(2) @(posedge clk);@(negedge clk);start=1;@(negedge clk);start=0;
        if (selected_case==1 || selected_case==2 || selected_case==7) begin
            wait(finished);#1ps;check(finished_error && fault && reset_required && !committed,"failed provisional generation never visible");
            repeat(16) begin @(posedge clk);#1ps;check(!committed && !retire_ready,"failed generation remains fenced");end
        end else begin
            wait(committed);#1ps;check(!fault && !reset_required,"healthy trained generation");
            if (selected_case==0) begin
                for(int head=0;head<40;head++) for(int slot=0;slot<2;slot++) fetch(head,slot,0);
                @(negedge clk);retire_valid=1;do @(posedge clk);while(retire_ready!==1'b1);
                @(negedge clk);retire_valid=0;#1ps;check(!committed && !busy && !fault,"healthy actual retire removes membership");
                read_valid=1;repeat(8) begin @(posedge clk);#1ps;check(!read_ready && !read_result_valid,"no read membership after retire");end
                @(negedge clk);read_valid=0;
            end else begin
                if(selected_case==3) begin fetch(0,0,0);fetch(39,1,1);end
                if(selected_case==4) begin read_generation=32'h19000002;fetch(0,0,1);end
                if(selected_case==5) fetch(40,0,1);
                if(selected_case==6) fetch(0,2,1);
                #1ps;check(fault && reset_required && !committed,"known bad read poisons membership");
                repeat(16) begin @(posedge clk);#1ps;check(fault && !retire_ready,"read failure remains fenced");end
            end
        end
        $display("QKV_CACHE_PATH_COMPONENT_PASS case=%0d tensor_boundary=saved_trained_integer_dot full_model=0",selected_case);
        $finish;
    end
endmodule
`default_nettype wire
