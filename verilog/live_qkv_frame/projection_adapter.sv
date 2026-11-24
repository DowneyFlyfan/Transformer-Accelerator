`timescale 1ns/1ps
module tri_oracle_metadata_projection_adapter (
  input logic clk,rst_n,cfg_valid,cfg_paired,
  input logic metadata_block,
  output logic metadata_idle,metadata_rebuilt,
  output logic [1:0] metadata_ce_n,metadata_we_n,
  output logic [17:0] metadata_address,
  output logic [127:0] metadata_write_data,
  input logic [127:0] metadata_read_data,
  output logic cfg_ready,
  input logic [31:0] cfg_tag,
  input logic [4:0] cfg_tokens,
  input logic [9:0] cfg_feature_words,
  input logic [16:0] cfg_dense_rows,
  input logic [7:0] cfg_count,
  input logic [2559:0] cfg_channels,cfg_keep,
  input logic [63:0] cfg_activation_base,cfg_weight_base,cfg_up_weight_base,
  input logic [31:0] cfg_activation_stride,
  output logic out_valid,
  input logic out_ready,
  output logic [31:0] out_tag,
  output logic [3:0] out_token,
  output logic out_last,
  output logic [7:0] out_count,
  output logic [2559:0] out_channels,
  output logic [5119:0] out_data,
  output logic done_valid,
  input logic done_ready,
  output logic done_error,
  output logic [31:0] done_tag,
  output logic req_valid,
  input logic req_ready,
  output logic [63:0] req_address,
  output logic [4:0] req_length,
  input logic rsp_valid,
  output logic rsp_ready,
  input logic rsp_last,rsp_error,
  input logic [63:0] rsp_data,
  input tri_oracle_wac_softmax_types::request_t softmax_request,
  output logic backend_rst_n,
  output logic load_valid,
  input logic load_error,
  output logic [4:0] load_core,
  output logic [1:0] load_kind,
  output logic [9:0] load_addr,
  output logic [2047:0] load_data,
  output logic [31:0] load_row_enable,
  output logic backend_cmd_valid,
  input logic backend_cmd_ready,
  output logic [4:0] backend_clusters,backend_cmd_weight,backend_cmd_mask,
  output logic [9:0] backend_cmd_activation,
  output logic [3:0] backend_cmd_output,
  output logic backend_cmd_accumulate,
  output logic [1:0] backend_cmd_reduce,
  output logic [2:0] backend_core_select,
  output logic [4:0] backend_activation_reloaded,
  input logic [4:0] backend_out_valid,
  output logic [4:0] backend_out_ready,
  input logic [19:0] backend_out_output,
  input logic [5119:0] backend_out_data
);
  // Compatibility-test adapter: a poisoned feed-forward descriptor is held
  // while context blocks its acceptance. Raw projection must still progress.
  // Raw projection commands use its existing attention.server interface.
  // No second array, payload buffer, or numerical operation is introduced here.
  tri_oracle_attention_tensor437 attention();
  tri_oracle_fabric_owner_types::request_t request;
  tri_oracle_fabric_owner_types::response_t response;
  logic ff_write_request,ff_write_data,ff_result_valid,ff_terminal_valid,ff_cfg_ready;
  always_comb begin
    attention.cfg_valid=cfg_valid && !cfg_paired;
    attention.cfg_tag=cfg_tag;attention.cfg_activation_stride=cfg_activation_stride;
    attention.cfg_tokens=cfg_tokens;attention.cfg_feature_words=cfg_feature_words;
    attention.cfg_dense_rows=cfg_dense_rows;attention.cfg_count=cfg_count;
    attention.cfg_channels=cfg_channels;attention.cfg_keep=cfg_keep;
    attention.cfg_activation_base=cfg_activation_base;attention.cfg_weight_base=cfg_weight_base;
    attention.out_ready=out_ready;attention.done_ready=done_ready;
    cfg_ready=attention.cfg_ready && !cfg_paired;
    out_valid=attention.out_valid;out_tag=attention.out_tag;out_token=attention.out_token;
    out_last=attention.out_last;out_count=attention.out_count;out_channels=attention.out_channels;
    out_data=attention.out_data;done_valid=attention.done_valid;done_error=attention.done_error;done_tag=attention.done_tag;
    backend_rst_n=request.rst_n;load_valid=request.load_valid;load_core=request.load_core;
    load_kind=request.load_kind;load_addr=request.load_addr;load_data=request.load_data;load_row_enable=request.load_rows;
    backend_cmd_valid=request.cmd_valid;backend_clusters=request.cmd_clusters;backend_cmd_weight=request.cmd_weight;
    backend_cmd_mask=request.cmd_mask;backend_cmd_activation=request.cmd_activation;backend_cmd_output=request.cmd_output;
    backend_cmd_accumulate=request.cmd_accumulate;backend_cmd_reduce=request.cmd_reduce;backend_core_select=request.core_select;
    backend_activation_reloaded=request.activation_reloaded;backend_out_ready=request.out_ready;
    response.load_error=load_error;response.cmd_ready=backend_cmd_ready;
    response.out_valid=backend_out_valid;response.out_output=backend_out_output;response.out_data=backend_out_data;
  end
  tri_oracle_external_metadata_row_learned #(.CORE_STRIP_PREDICTOR(1)) datapath (
    .metadata_block,.metadata_idle,.metadata_rebuilt,
    .metadata_ce_n,.metadata_we_n,.metadata_address,.metadata_write_data,.metadata_read_data,
    .clk,.rst_n,.attention,.softmax_request,.backend_request(request),.backend_response(response),
    .cfg_valid(metadata_block),.cfg_ready(ff_cfg_ready),.cfg_row_enable(1'b0),.cfg_correction_enable(1'b0),.cfg_row_units_base(64'b0),
    .cfg_tag(32'b0),.cfg_tokens(5'b0),.cfg_input_features(16'b0),.cfg_intermediate_features(16'b0),.cfg_output_features(17'b0),
    .cfg_activation_base(64'b0),.cfg_gate_base(64'b0),.cfg_up_base(64'b0),.cfg_down_base(64'b0),.cfg_intermediate_base(64'b0),
    .cfg_activation_stride(32'b0),.cfg_gate_shifts(96'b0),.cfg_up_shifts(96'b0),.cfg_down_shifts(96'b0),.cfg_activation_shifts(96'b0),
    .cfg_gate_sign_base(64'b0),.cfg_up_sign_base(64'b0),.cfg_epsilon_q16(32'b0),.residual_token(),
    .stats_valid(1'b0),.stats_last(1'b0),.stats_ready(),.stats_data(128'b0),
    .replay_valid(1'b0),.replay_last(1'b0),.replay_ready(),.replay_data(128'b0),.replay_gamma(128'b0),
    .out_valid(ff_result_valid),.out_ready(1'b1),.out_tag(),.out_token(),.out_start(),.out_count(),.out_last(),.out_data(),
    .done_valid(ff_terminal_valid),.done_ready(1'b1),.done_error(),.done_tag(),
    .req_valid,.req_ready,.req_address,.req_length,.rsp_valid,.rsp_ready,.rsp_last,.rsp_error,.rsp_data,
    .wr_req_valid(ff_write_request),.wr_req_ready(1'b0),.wr_address(),.wr_length(),.wr_data_valid(ff_write_data),.wr_data_ready(1'b0),
    .wr_data(),.wr_strobe(),.wr_data_last(),.wr_rsp_valid(1'b0),.wr_rsp_error(1'b0),.wr_rsp_ready(),
    .strip_request(),.strip_response(112'b0)
  );
endmodule
