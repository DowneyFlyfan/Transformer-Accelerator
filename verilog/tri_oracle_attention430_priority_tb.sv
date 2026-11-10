`timescale 1ns/1ps
module tri_oracle_attention430_priority_tb;
    logic clk=0,rst_n=0;
    always #5 clk=~clk;
    logic projection_valid=0,projection_done_ready=0;
    logic frame_valid=0,head_valid=0,row_valid=0;
    wire projection_ready,projection_done_valid,projection_done_error;
    wire frame_ready,head_ready,row_ready,restore_ready;
    wire tensor_cfg_valid,cache_write_valid,angle_ready;
    wire [31:0] projection_done_tag;
    localparam logic [31:0] TAG=32'h430055aa;

    tri_oracle_attention_pipeline430 dut (
        .clk,.rst_n,.projection_valid,.projection_ready,.projection_tag(TAG),
        .projection_tokens(5'd2),.projection_first_head(6'd0),.projection_heads(6'd1),
        .projection_slot(10'd1023),.projection_activation_base(64'd0),.projection_weight_base(64'd0),
        .projection_cache_base(64'd0),.projection_shifts(240'd0),.projection_shift_biases(96'd0),
        .angle_valid(1'b0),.angle_last(1'b0),.angle_ready,.angle_cos(512'd0),.angle_sin(512'd0),
        .projection_done_valid,.projection_done_error,.projection_done_ready,.projection_done_tag,
        .cache_write_valid,.cache_write_ready(1'b0),.cache_write_rsp_valid(1'b0),.cache_write_rsp_error(1'b0),
        .frame_valid,.frame_new_image(1'b1),.frame_layer(5'd0),.frame_ready,
        .frame_minimum_matches(12'd1536),.frame_image_start(10'd0),.sign_valid(1'b0),.sign_data(2048'd0),
        .map_ready(1'b0),.frame_done_ready(1'b0),
        .restore_valid(1'b1),.restore_layer(5'd0),.restore_ready,.restore_done_ready(1'b0),
        .head_valid,.head_ready,.head_id(5'd0),.head_tag(32'd0),.head_alpha(32'd0),.head_tokens(11'd0),
        .head_ratio_num(8'd8),.head_ratio_den(8'd1),.head_query_base(64'd0),.head_key_base(64'd0),
        .head_done_ready(1'b0),.row_valid,.row_ready,.row_head(5'd0),.row_position(11'd0),.row_key_count(11'd0),
        .row_tag(32'd0),.row_score_shift(7'sd0),.row_query_addr(64'd0),.row_key_base(64'd0),.result_ready(1'b0),
        .tensor_cfg_valid,.tensor_cfg_ready(1'b0),.tensor_out_valid(1'b0),.tensor_out_last(1'b0),
        .tensor_out_tag(32'd0),.tensor_out_token(4'd0),.tensor_out_count(8'd0),.tensor_out_channels(2560'd0),
        .tensor_out_data(5120'd0),.tensor_done_valid(1'b0),.tensor_done_error(1'b0),.tensor_done_tag(32'd0),
        .value_req_ready(1'b0),.value_rsp_valid(1'b0),.value_rsp_error(1'b0),.value_rsp_data(512'd0)
    );

    initial begin
        repeat (3) @(negedge clk);
        rst_n=1;
        projection_valid=1;
        @(posedge clk);
        if (projection_ready!==1'b1 || restore_ready!==1'b0)
            $fatal(1,"COMPOSE430_DISABLED_RESTORE_BLOCKS_PROJECTION");
        @(negedge clk);
        projection_valid=0;
        frame_valid=1;
        head_valid=1;
        row_valid=1;
        repeat (3) begin
            @(posedge clk);
            if (!projection_done_valid || !projection_done_error || projection_done_tag!==TAG ||
                frame_ready || head_ready || row_ready || restore_ready || tensor_cfg_valid ||
                cache_write_valid || angle_ready || dut.attention.frame_valid ||
                dut.attention.head_valid || dut.attention.row_valid)
                $fatal(1,"COMPOSE430_PRIORITY_OWNER");
        end
        @(negedge clk);
        projection_done_ready=1;
        @(posedge clk);
        @(negedge clk);
        if (!frame_ready || head_ready || row_ready || projection_done_valid)
            $fatal(1,"COMPOSE430_PRIORITY_RELEASE");
        $display("COMPOSE430_PRIORITY_PASS rejected_hold_cycles=3");
        $finish;
    end
endmodule
