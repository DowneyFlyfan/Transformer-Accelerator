`timescale 1ns/1ps
// Normalize/scale once per token, commit local activations, reuse prediction metadata.
// Learned coefficients are streamed with raw replay; matrix/sign reads stay external.
// The local inferred cache is not a compiled foundry memory or a paper-area claim.
module tri_oracle_cached_feedforward_core (
    input logic clk,rst_n,cfg_valid,
    output logic cfg_ready,
    input logic [31:0] cfg_tag,cfg_epsilon_q16,
    input logic [63:0] cfg_activation_base,cfg_weight_base,cfg_up_weight_base,
    input logic [63:0] cfg_down_weight_base,cfg_gate_sign_base,cfg_up_sign_base,
    input logic [5:0] cfg_gate_shift,cfg_up_shift,cfg_down_shift,cfg_activation_shift,
    input logic [9:0] cfg_features,
    input logic [16:0] cfg_dense_features,
    input logic [15:0] cfg_output_start,
    input logic [8:0] cfg_output_count,
    input logic group_valid,
    output logic group_ready,
    input logic [10:0] group_id,
    input logic group_last,stats_valid,
    output logic stats_ready,
    input logic stats_last,
    input logic [127:0] stats_data,
    input logic replay_valid,
    output logic replay_ready,
    input logic replay_last,
    input logic [127:0] replay_data,replay_gamma,
    output logic out_valid,
    input logic out_ready,
    output logic out_last,out_fallback,out_error,
    output logic [31:0] out_tag,
    output logic [5:0] out_count,
    output logic [511:0] out_channels,
    output logic [1023:0] out_data,
    output logic req_valid,
    input logic req_ready,
    output logic [63:0] req_address,
    output logic [4:0] req_length,
    input logic rsp_valid,rsp_last,rsp_error,
    output logic rsp_ready,
    input logic [63:0] rsp_data
);
    typedef enum logic [2:0] {Idle,Prepare,Start,Run,Failed,Invalid} state_t;
    typedef enum logic [1:0] {None,Local,External} owner_t;
    state_t state;
    owner_t owner;
    logic [31:0] tag;
    logic [63:0] activation_base,weight_base,up_weight_base,down_weight_base;
    logic [63:0] gate_sign_base,up_sign_base;
    logic [5:0] gate_shift,up_shift,down_shift;
    logic [9:0] features;
    logic [16:0] dense_features;
    logic [15:0] output_start;
    logic [8:0] output_count;
    logic invalid_config;
    logic [64:0] incoming_act_bytes,incoming_matrix_bytes,incoming_sign_bytes;
    logic [64:0] incoming_act_last,incoming_gate_last,incoming_up_last;
    logic [64:0] incoming_gate_sign_last,incoming_up_sign_last;
    logic [64:0] incoming_down_first,incoming_down_last;
    logic prep_cfg_ready,prep_stats_ready,prep_replay_ready;
    logic prep_valid,prep_ready,prep_last,prep_error;
    logic [31:0] prep_tag;
    logic [9:0] prep_index;
    logic [3:0] prep_count;
    logic [127:0] prep_norm;
    logic [7:0] prep_outliers;
    logic [63:0] prep_activation;
    logic cache_cfg_ready,cache_input_ready,cache_done_valid,cache_done_error;
    logic [31:0] cache_done_tag;
    logic cache_release_valid,cache_release_ready,can_release;
    logic meta_active,meta_pending,meta_req_valid,meta_req_ready;
    logic [8:0] meta_index;
    logic meta_rsp_valid,meta_rsp_ready,meta_rsp_error;
    logic [8:0] meta_rsp_index;
    logic [31:0] meta_rsp_tag;
    logic [127:0] meta_rsp_norm;
    logic cache_read_req_valid,cache_read_req_ready,cache_read_rsp_valid;
    logic cache_read_rsp_ready,cache_read_rsp_last,cache_read_rsp_error;
    logic [63:0] cache_read_rsp_data;
    logic exec_cfg_ready,exec_group_ready,exec_norm_ready;
    logic exec_out_valid,exec_out_ready,exec_out_last,exec_out_error,exec_out_fallback;
    logic [31:0] exec_out_tag;
    logic [5:0] exec_out_count;
    logic [511:0] exec_out_channels;
    logic [1023:0] exec_out_data;
    logic exec_req_valid,exec_req_ready,exec_rsp_valid,exec_rsp_ready;
    logic exec_rsp_last,exec_rsp_error;
    logic [63:0] exec_req_address,exec_rsp_data;
    logic [4:0] exec_req_length;
    logic local_request;
    logic [63:0] local_offset;
    logic [64:0] local_bytes;

    function automatic logic overlaps(
        input logic [64:0] left_first,left_last,right_first,right_last
    );
        overlaps=left_first<=right_last && right_first<=left_last;
    endfunction
    always_comb begin
        incoming_act_bytes=65'(cfg_features) << 3;
        incoming_matrix_bytes=65'(cfg_dense_features)*incoming_act_bytes;
        incoming_sign_bytes=65'(cfg_dense_features)*65'(cfg_features);
        incoming_act_last={1'b0,cfg_activation_base}+incoming_act_bytes-65'd1;
        incoming_gate_last={1'b0,cfg_weight_base}+incoming_matrix_bytes-65'd1;
        incoming_up_last={1'b0,cfg_up_weight_base}+incoming_matrix_bytes-65'd1;
        incoming_gate_sign_last={1'b0,cfg_gate_sign_base}+incoming_sign_bytes-65'd1;
        incoming_up_sign_last={1'b0,cfg_up_sign_base}+incoming_sign_bytes-65'd1;
        incoming_down_first={1'b0,cfg_down_weight_base}+
            65'(cfg_output_start)*65'(cfg_dense_features);
        incoming_down_last=incoming_down_first+
            65'(cfg_output_count)*65'(cfg_dense_features)-65'd1;
        invalid_config=cfg_features==0 || cfg_features>10'd512 ||
            cfg_dense_features<17'd32 || cfg_dense_features>17'd65536 ||
            cfg_dense_features[4:0]!=0 || cfg_output_count==0 || cfg_output_count>9'd480 ||
            17'(cfg_output_start)+17'(cfg_output_count)>17'd65536 ||
            cfg_activation_base[2:0]!=0 || cfg_weight_base[2:0]!=0 ||
            cfg_up_weight_base[2:0]!=0 || cfg_down_weight_base[2:0]!=0 ||
            cfg_gate_sign_base[2:0]!=0 || cfg_up_sign_base[2:0]!=0 ||
            incoming_act_last[64] || incoming_gate_last[64] || incoming_up_last[64] ||
            incoming_gate_sign_last[64] || incoming_up_sign_last[64] ||
            incoming_down_last[64] ||
            overlaps({1'b0,cfg_activation_base},incoming_act_last,
                {1'b0,cfg_weight_base},incoming_gate_last) ||
            overlaps({1'b0,cfg_activation_base},incoming_act_last,
                {1'b0,cfg_up_weight_base},incoming_up_last) ||
            overlaps({1'b0,cfg_activation_base},incoming_act_last,
                {1'b0,cfg_gate_sign_base},incoming_gate_sign_last) ||
            overlaps({1'b0,cfg_activation_base},incoming_act_last,
                {1'b0,cfg_up_sign_base},incoming_up_sign_last) ||
            overlaps({1'b0,cfg_activation_base},incoming_act_last,
                incoming_down_first,incoming_down_last);
        cfg_ready=state==Idle && prep_cfg_ready && cache_cfg_ready && exec_cfg_ready;
        stats_ready=state==Prepare && prep_stats_ready;
        replay_ready=state==Prepare && prep_replay_ready;
        prep_ready=state==Prepare && cache_input_ready;
        group_ready=state==Run && !meta_active && exec_group_ready;
        meta_req_valid=state==Run && meta_active && !meta_pending;
        meta_rsp_ready=state==Run && meta_pending && exec_norm_ready;
        can_release=cache_release_ready && owner==None && !meta_active && !meta_pending;

        out_valid=state==Invalid || (state==Failed && can_release) ||
            (state==Run && exec_out_valid && (!exec_out_last || can_release));
        out_last=state!=Run || exec_out_last;
        out_error=state==Invalid || state==Failed || (state==Run && exec_out_error);
        out_fallback=state==Run && exec_out_fallback;
        out_tag=state==Run ? exec_out_tag : tag;
        out_count=state==Run ? exec_out_count : 6'd0;
        out_channels=state==Run ? exec_out_channels : 512'b0;
        out_data=state==Run ? exec_out_data : 1024'b0;
        cache_release_valid=(state==Run || state==Failed) && out_valid && out_ready && out_last;

        local_offset=exec_req_address-activation_base;
        local_bytes=65'(features) << 3;
        local_request=exec_req_address>=activation_base && {1'b0,local_offset}<local_bytes;
        cache_read_req_valid=state==Run && owner==None && exec_req_valid && local_request;
        req_valid=state==Run && owner==None && exec_req_valid && !local_request;
        req_address=exec_req_address;
        req_length=exec_req_length;
        exec_rsp_valid=state==Run && (owner==Local ? cache_read_rsp_valid :
            (owner==External && rsp_valid));
        exec_rsp_last=owner==Local ? cache_read_rsp_last : rsp_last;
        exec_rsp_error=owner==Local ? cache_read_rsp_error : rsp_error;
        exec_rsp_data=owner==Local ? cache_read_rsp_data : rsp_data;
        rsp_ready=state==Run && owner==External && exec_rsp_ready;
        cache_read_rsp_ready=state==Run && owner==Local && exec_rsp_ready;
    end
    always_comb exec_out_ready=state==Run && out_ready && (!exec_out_last || can_release);
    always_comb exec_req_ready=state==Run && owner==None &&
        (local_request ? cache_read_req_ready : req_ready);

    tri_oracle_rms_activation preparation (
        .clk(clk),.rst_n(rst_n),.cfg_valid(cfg_valid && cfg_ready && !invalid_config),
        .cfg_ready(prep_cfg_ready),.cfg_tag(cfg_tag),.cfg_epsilon_q16(cfg_epsilon_q16),
        .cfg_strips(cfg_features),.cfg_shift(cfg_activation_shift),
        .stats_valid(state==Prepare && stats_valid),.stats_ready(prep_stats_ready),
        .stats_last(stats_last),.stats_data(stats_data),
        .replay_valid(state==Prepare && replay_valid),.replay_ready(prep_replay_ready),
        .replay_last(replay_last),.replay_data(replay_data),.replay_gamma(replay_gamma),
        .out_valid(prep_valid),.out_ready(prep_ready),.out_last(prep_last),.out_error(prep_error),
        .out_tag(prep_tag),.out_index(prep_index),.out_count(prep_count),
        .out_norm_q8(prep_norm),.out_outlier_mask(prep_outliers),.out_activation(prep_activation)
    );
    tri_oracle_activation_cache cache (
        .clk(clk),.rst_n(rst_n),.cfg_valid(cfg_valid && cfg_ready && !invalid_config),
        .cfg_ready(cache_cfg_ready),.cfg_tag(cfg_tag),.cfg_strips(cfg_features),
        .in_valid(state==Prepare && prep_valid),.in_ready(cache_input_ready),
        .in_last(prep_last),.in_error(prep_error),.in_tag(prep_tag),.in_index(prep_index),
        .in_count(prep_count),.in_norm_q8(prep_norm),.in_outlier_mask(prep_outliers),
        .in_activation(prep_activation),.done_valid(cache_done_valid),.done_ready(state==Prepare),
        .done_error(cache_done_error),.done_tag(cache_done_tag),
        .release_valid(cache_release_valid),.release_ready(cache_release_ready),
        .meta_req_valid(meta_req_valid),.meta_req_ready(meta_req_ready),.meta_req_index(meta_index),
        .meta_rsp_valid(meta_rsp_valid),.meta_rsp_ready(meta_rsp_ready),.meta_rsp_error(meta_rsp_error),
        .meta_rsp_index(meta_rsp_index),.meta_rsp_tag(meta_rsp_tag),.meta_rsp_norm(meta_rsp_norm),
        .read_req_valid(cache_read_req_valid),.read_req_ready(cache_read_req_ready),
        .read_req_index(local_offset[11:3]),.read_req_length(exec_req_length),
        .read_rsp_valid(cache_read_rsp_valid),.read_rsp_ready(cache_read_rsp_ready),
        .read_rsp_last(cache_read_rsp_last),.read_rsp_error(cache_read_rsp_error),
        .read_rsp_data(cache_read_rsp_data)
    );
    tri_oracle_prediction_feedforward_core execution (
        .clk(clk),.rst_n(rst_n),.cfg_valid(state==Start),.cfg_ready(exec_cfg_ready),
        .cfg_tag(tag),.cfg_activation_base(activation_base),.cfg_weight_base(weight_base),
        .cfg_up_weight_base(up_weight_base),.cfg_down_weight_base(down_weight_base),
        .cfg_gate_sign_base(gate_sign_base),.cfg_up_sign_base(up_sign_base),
        .cfg_gate_shift(gate_shift),.cfg_up_shift(up_shift),.cfg_down_shift(down_shift),
        .cfg_features(features),.cfg_dense_features(dense_features),
        .cfg_output_start(output_start),.cfg_output_count(output_count),
        .group_valid(state==Run && !meta_active && group_valid),.group_ready(exec_group_ready),
        .group_id(group_id),.group_last(group_last),
        .norm_valid(state==Run && meta_pending && meta_rsp_valid),.norm_ready(exec_norm_ready),
        .norm_last({1'b0,meta_index}+10'd1==features),
        .norm_error(meta_rsp_error || meta_rsp_tag!=tag || meta_rsp_index!=meta_index),
        .norm_index({1'b0,meta_index}),.norm_data(meta_rsp_norm),
        .out_valid(exec_out_valid),.out_ready(exec_out_ready),.out_last(exec_out_last),
        .out_fallback(exec_out_fallback),.out_error(exec_out_error),.out_tag(exec_out_tag),
        .out_count(exec_out_count),.out_channels(exec_out_channels),.out_data(exec_out_data),
        .req_valid(exec_req_valid),.req_ready(exec_req_ready),
        .req_address(exec_req_address),.req_length(exec_req_length),
        .rsp_valid(exec_rsp_valid),.rsp_last(exec_rsp_last),.rsp_error(exec_rsp_error),
        .rsp_ready(exec_rsp_ready),.rsp_data(exec_rsp_data)
    );
    always_ff @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            state<=Idle;owner<=None;tag<='0;activation_base<='0;weight_base<='0;
            up_weight_base<='0;down_weight_base<='0;gate_sign_base<='0;up_sign_base<='0;
            gate_shift<='0;up_shift<='0;down_shift<='0;features<='0;dense_features<='0;
            output_start<='0;output_count<='0;meta_active<=0;meta_pending<=0;meta_index<='0;
        end else begin
            case(state)
                Idle: if(cfg_valid && cfg_ready) begin
                    tag<=cfg_tag;activation_base<=cfg_activation_base;weight_base<=cfg_weight_base;
                    up_weight_base<=cfg_up_weight_base;down_weight_base<=cfg_down_weight_base;
                    gate_sign_base<=cfg_gate_sign_base;up_sign_base<=cfg_up_sign_base;
                    gate_shift<=cfg_gate_shift;up_shift<=cfg_up_shift;down_shift<=cfg_down_shift;
                    features<=cfg_features;dense_features<=cfg_dense_features;
                    output_start<=cfg_output_start;output_count<=cfg_output_count;
                    if(invalid_config) state<=Invalid;
                    else state<=Prepare;
                end
                Prepare: if(cache_done_valid) begin
                    if(cache_done_error || cache_done_tag!=tag) state<=Failed;
                    else state<=Start;
                end
                Start: if(exec_cfg_ready) state<=Run;
                Run: if(out_valid && out_ready && out_last) state<=Idle;
                Failed,Invalid: if(out_valid && out_ready) state<=Idle;
                default: state<=Idle;
            endcase
            if(group_valid && group_ready) begin
                meta_active<=1;meta_index<='0;
            end
            if(meta_req_valid && meta_req_ready) meta_pending<=1;
            if(meta_rsp_valid && meta_rsp_ready) begin
                meta_pending<=0;
                if({1'b0,meta_index}+10'd1==features) meta_active<=0;
                else meta_index<=meta_index+9'd1;
            end
            if(exec_req_valid && exec_req_ready) begin
                if(local_request) owner<=Local;
                else owner<=External;
            end
            if(exec_rsp_valid && exec_rsp_ready && exec_rsp_last) owner<=None;
        end
    end
endmodule
