`timescale 1ns/1ps
`default_nettype none
// Actual projection producer -> actual acknowledged cache writer -> guarded
// external-memory reader. The tensor engine and physical memory remain caller
// owned. Read membership means this ONE committed contiguous job, not a full
// retained frame, causal Size truth, attention completion, or POST completion.
module tri_oracle_attention_post_qkv_path_v1 (
  input logic clk,rst_n,cancel,
  input logic cfg_valid,output logic cfg_ready,
  input logic [31:0] cfg_tag,cfg_generation,
  input logic [4:0] cfg_layer,cfg_tokens,
  input logic [15:0] cfg_epoch,
  input logic [9:0] cfg_slot,
  input logic [63:0] cfg_activation_base,cfg_activation_bytes,
  input logic [63:0] cfg_weight_base,cfg_weight_bytes,cfg_cache_base,cfg_cache_bytes,
  input logic [239:0] cfg_shifts,input logic [95:0] cfg_shift_biases,
  input logic [359:0] cfg_head_units,
  input logic angle_valid,angle_last,output logic angle_ready,
  input logic [511:0] angle_cos,angle_sin,
  output logic tensor_cfg_valid,input logic tensor_cfg_ready,
  output logic [31:0] tensor_cfg_tag,output logic [4:0] tensor_cfg_tokens,
  output logic [7:0] tensor_cfg_count,
  output logic [2559:0] tensor_cfg_channels,tensor_cfg_keep,
  output logic [63:0] tensor_cfg_activation_base,tensor_cfg_weight_base,
  input logic tensor_out_valid,tensor_out_last,output logic tensor_out_ready,
  input logic [31:0] tensor_out_tag,input logic [3:0] tensor_out_token,
  input logic [7:0] tensor_out_count,input logic [2559:0] tensor_out_channels,
  input logic [4095:0] tensor_out_data,
  input logic tensor_done_valid,tensor_done_error,output logic tensor_done_ready,
  input logic [31:0] tensor_done_tag,
  output logic cache_write_valid,input logic cache_write_ready,
  output logic [63:0] cache_write_address,output logic [511:0] cache_write_data,
  output logic [4:0] cache_write_length,
  input logic cache_write_rsp_valid,cache_write_rsp_error,output logic cache_write_rsp_ready,
  output logic done_valid,done_error,input logic done_ready,
  output logic [31:0] done_tag,done_generation,
  output logic committed_valid,output logic [9:0] committed_first_slot,
  output logic [4:0] committed_tokens,
  input logic retire_valid,output logic retire_ready,
  input logic read_valid,output logic read_ready,
  input logic [31:0] read_tag,read_generation,input logic [4:0] read_layer,
  input logic [15:0] read_epoch,input logic [5:0] read_head,input logic [9:0] read_slot,
  output logic read_result_valid,input logic read_result_ready,
  output logic read_result_error,output logic [31:0] read_result_tag,read_result_generation,
  output logic [4:0] read_result_layer,output logic [15:0] read_result_epoch,
  output logic [5:0] read_result_head,output logic [9:0] read_result_slot,
  output logic signed [8:0] read_result_unit,output logic [511:0] read_result_data,
  output logic memory_read_valid,input logic memory_read_ready,
  output logic [63:0] memory_read_address,output logic [4:0] memory_read_length,
  input logic memory_rsp_valid,memory_rsp_last,memory_rsp_error,
  input logic [63:0] memory_rsp_data,output logic memory_rsp_ready,
  output logic fault,reset_required,busy
);
  logic producer_cfg_valid,producer_cfg_ready,producer_enabled;
  logic [31:0] producer_cfg_tag;
  logic [4:0] producer_cfg_tokens;
  logic [63:0] producer_cfg_activation_base,producer_cfg_weight_base;
  logic [239:0] producer_cfg_shifts;
  logic [95:0] producer_cfg_shift_biases;
  logic source_valid,source_last,source_ready,source_done_valid,source_done_error,source_done_ready;
  logic [31:0] source_tag,source_done_tag;
  logic [5:0] source_head;
  logic [3:0] source_token;
  logic [511:0] source_data;
  logic producer_active,producer_fault_q,core_cancel;
  logic unknown_angle;
  logic unknown_tensor_packet;
  logic unknown_tensor_completion;

  // These four-state tests have no physical unknown detector.
  always_comb begin
    unknown_angle = 1'b0;
    unknown_tensor_packet = 1'b0;
    unknown_tensor_completion = 1'b0;
    // synthesis translate_off
    unknown_angle = $isunknown({angle_last,angle_cos,angle_sin});
    unknown_tensor_packet = $isunknown({tensor_out_last,tensor_out_tag,tensor_out_token,
          tensor_out_count,tensor_out_channels,tensor_out_data});
    unknown_tensor_completion = $isunknown({tensor_done_error,tensor_done_tag});
    // synthesis translate_on
  end

  always_comb core_cancel=(cancel!==1'b0) || producer_fault_q;

  // This wrapper does not gate already-offered tensor/producer payloads with a
  // returning fault or ready. Legacy transport remains owned and drainable.
  // Four-state errors missed by the legacy arithmetic controller invalidate the
  // entire cache generation; they cannot become a committed membership claim.
  always_ff @(posedge clk or negedge rst_n)begin
    if(rst_n===1'b0)begin producer_active<=0;producer_fault_q<=0;end
    else if(rst_n!==1'b1)producer_fault_q<=1;
    else begin
      if(producer_cfg_valid && producer_cfg_ready)producer_active<=1;
      if(source_done_valid && source_done_ready)producer_active<=0;
      if(producer_active)begin
        if(angle_valid!==1'b0 && angle_valid!==1'b1)producer_fault_q<=1;
        if(angle_valid===1'b1 && angle_ready && unknown_angle)producer_fault_q<=1;
        if(tensor_cfg_valid && tensor_cfg_ready!==1'b0 && tensor_cfg_ready!==1'b1)producer_fault_q<=1;
        if(tensor_out_valid!==1'b0 && tensor_out_valid!==1'b1)producer_fault_q<=1;
        if(tensor_out_valid===1'b1 && unknown_tensor_packet)producer_fault_q<=1;
        if(tensor_done_valid!==1'b0 && tensor_done_valid!==1'b1)producer_fault_q<=1;
        if(tensor_done_valid===1'b1 && unknown_tensor_completion)producer_fault_q<=1;
      end else if(tensor_out_valid!==1'b0 || tensor_done_valid!==1'b0)producer_fault_q<=1;
    end
  end

  tri_oracle_qkv429 producer (
    .clk,.rst_n,.cfg_valid(producer_cfg_valid),.cfg_ready(producer_cfg_ready),.cfg_tokens(producer_cfg_tokens),
    .cfg_start_head(6'd0),.cfg_heads(6'd40),.cfg_tag(producer_cfg_tag),
    .cfg_activation_base(producer_cfg_activation_base),.cfg_weight_base(producer_cfg_weight_base),
    .cfg_shifts(producer_cfg_shifts),.cfg_shift_biases(producer_cfg_shift_biases),
    .angle_valid,.angle_last,.angle_ready,.angle_cos,.angle_sin,
    .out_valid(source_valid),.out_last(source_last),.out_ready(source_ready),
    .out_tag(source_tag),.out_head(source_head),.out_token(source_token),.out_data(source_data),
    .done_valid(source_done_valid),.done_error(source_done_error),.done_ready(source_done_ready),.done_tag(source_done_tag),
    .tensor_cfg_valid,.tensor_cfg_ready,.tensor_cfg_tag,.tensor_cfg_tokens,.tensor_cfg_count,
    .tensor_cfg_channels,.tensor_cfg_keep,.tensor_cfg_activation_base,.tensor_cfg_weight_base,
    .tensor_out_valid,.tensor_out_last,.tensor_out_ready,.tensor_out_tag,.tensor_out_token,.tensor_out_count,
    .tensor_out_channels,.tensor_out_data,.tensor_done_valid,.tensor_done_error,.tensor_done_ready,.tensor_done_tag
  );
  tri_oracle_committed_qkv_cache_v1 cache (
    .clk,.rst_n,.cancel(core_cancel),.cfg_valid,.cfg_ready,.cfg_tag,.cfg_generation,.cfg_layer,.cfg_tokens,.cfg_epoch,.cfg_slot,
    .cfg_activation_base,.cfg_activation_bytes,.cfg_weight_base,.cfg_weight_bytes,.cfg_cache_base,.cfg_cache_bytes,
    .cfg_shifts,.cfg_shift_biases,.cfg_head_units,
    .producer_cfg_valid,.producer_cfg_ready,.producer_cfg_tag,.producer_cfg_tokens,
    .producer_cfg_activation_base,.producer_cfg_weight_base,.producer_cfg_shifts,.producer_cfg_shift_biases,.producer_enabled,
    .source_valid,.source_last,.source_ready,.source_tag,.source_head,.source_token,.source_data,
    .source_done_valid,.source_done_error,.source_done_ready,.source_done_tag,
    .cache_write_valid,.cache_write_ready,.cache_write_address,.cache_write_data,.cache_write_length,
    .cache_write_rsp_valid,.cache_write_rsp_error,.cache_write_rsp_ready,
    .done_valid,.done_error,.done_ready,.done_tag,.done_generation,
    .committed_valid,.committed_first_slot,.committed_tokens,.retire_valid,.retire_ready,
    .read_valid,.read_ready,.read_tag,.read_generation,.read_layer,.read_epoch,.read_head,.read_slot,
    .read_result_valid,.read_result_ready,.read_result_error,.read_result_tag,.read_result_generation,
    .read_result_layer,.read_result_epoch,.read_result_head,.read_result_slot,.read_result_unit,.read_result_data,
    .memory_read_valid,.memory_read_ready,.memory_read_address,.memory_read_length,
    .memory_rsp_valid,.memory_rsp_last,.memory_rsp_error,.memory_rsp_data,.memory_rsp_ready,
    .fault,.reset_required,.busy
  );
endmodule
`default_nettype wire
