`timescale 1ns/1ps
// Verification-only display configuration. It does not drive the bench or chip.
module tri_oracle_head_trace_clock_format;
    initial begin
        // Vendor memory formatters run at time zero; first clock is at 5 ns.
        #1;
        $timeformat(-9, 0, "", 0);
        $display("TRACE_CLOCK_FORMAT unit=ns precision=0 configured_ns=%0t first_rising_ns=5 period_ns=10",$time);
    end
endmodule

// Passive observations of accepted transfers and actual held result wires.
// Invalid configuration payload and inactive output payload are not sampled.
module tri_oracle_head_trace_probe (
    input logic clk, rst_n,
    input logic cfg_valid, cfg_ready,
    input logic [4:0] cfg_head_id,
    input logic [12:0] cfg_tokens,
    input logic [31:0] cfg_tag, cfg_alpha,
    input logic [7:0] cfg_ratio_num, cfg_ratio_den,
    input logic [63:0] cfg_query_base, cfg_key_base,
    input logic tensor_cfg_valid, tensor_cfg_ready,
    input logic [31:0] tensor_cfg_tag,
    input logic [4:0] tensor_cfg_tokens,
    input logic [16:0] tensor_cfg_dense_rows,
    input logic [2559:0] tensor_cfg_channels, tensor_cfg_keep,
    input logic [63:0] tensor_cfg_activation_base, tensor_cfg_weight_base,
    input logic req_valid, req_ready,
    input logic [63:0] req_address,
    input logic [4:0] req_length,
    input logic rsp_valid, rsp_ready, rsp_last, rsp_error,
    input logic [63:0] rsp_data,
    input logic tensor_out_valid, tensor_out_ready, tensor_out_last,
    input logic [31:0] tensor_out_tag,
    input logic [3:0] tensor_out_token,
    input logic [7:0] tensor_out_count,
    input logic out_valid, out_ready, out_error, out_streaming,
    input logic [31:0] out_tag,
    input logic [17:0] out_inner, out_outer
);
    always @(posedge clk) if (rst_n === 1'b1) begin
        if (cfg_valid === 1'b1 && cfg_ready === 1'b1)
            $display("TRACE_HEAD_CONFIG tick=%0t head=%0d tokens=%0d tag=%08h alpha=%0d numerator=%0d denominator=%0d query_base=%016h key_base=%016h",
                     $time,cfg_head_id,cfg_tokens,cfg_tag,cfg_alpha,cfg_ratio_num,cfg_ratio_den,cfg_query_base,cfg_key_base);
        if (tensor_cfg_valid === 1'b1 && tensor_cfg_ready === 1'b1)
            $display("TRACE_HEAD_TENSOR_CONFIG tick=%0t tag=%08h tokens=%0d rows=%0d query_base=%016h key_base=%016h channels=%0640h keep=%0640h",
                     $time,tensor_cfg_tag,tensor_cfg_tokens,tensor_cfg_dense_rows,tensor_cfg_activation_base,tensor_cfg_weight_base,tensor_cfg_channels,tensor_cfg_keep);
        if (req_valid === 1'b1 && req_ready === 1'b1)
            $display("TRACE_HEAD_REQUEST tick=%0t address=%016h length=%0d",$time,req_address,req_length);
        if (rsp_valid === 1'b1 && rsp_ready === 1'b1)
            $display("TRACE_HEAD_RESPONSE tick=%0t last=%0b error=%0b data=%016h",$time,rsp_last,rsp_error,rsp_data);
        // The raw-descriptor negative control terminates in the original bench.
        // Do not add a scheduling-dependent unknown descriptor record here.
        if (tensor_out_valid === 1'b1 && tensor_out_ready === 1'b1 &&
            !$isunknown({tensor_out_tag,tensor_out_token,tensor_out_last,tensor_out_count}))
            $display("TRACE_HEAD_PACKET_ACCEPT tick=%0t tag=%08h token=%0d last=%0b count=%0d",
                     $time,tensor_out_tag,tensor_out_token,tensor_out_last,tensor_out_count);
        if (out_valid === 1'b1)
            $display("TRACE_HEAD_RESULT tick=%0t ready=%0b tag=%08h inner=%0d recent=%0d streaming=%0b error=%0b",
                     $time,out_ready,out_tag,out_inner,out_outer,out_streaming,out_error);
    end
endmodule
bind tri_oracle_trained_head_prediction_tb tri_oracle_head_trace_probe trace_observation(.*);
