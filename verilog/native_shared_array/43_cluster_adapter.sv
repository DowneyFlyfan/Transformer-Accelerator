module tri_oracle_partitioned_cluster #(
  parameter int MERGE_FEATURES=0,
  parameter bit AGGREGATOR_MERGE_TABLE=0,
  parameter bit LOCAL_TOKEN_SIZES=0, LOCAL_TOKEN_MERGE=0,
  parameter int MERGE_TABLE_ENTRIES=128, MERGE_TABLE_START=0,
  parameter bit CORE_STRIP_PREDICTOR=0,
  parameter bit CORE_HEAD_PREDICTOR=0,
  localparam int SIGN_WIDTH=MERGE_FEATURES==0 ? 1 : MERGE_FEATURES
) (
  input logic clk,
  input logic rst_n,
  input logic load_valid,
  input logic [1:0] load_core,
  input logic [1:0] load_kind,
  input logic [9:0] load_addr,
  input logic [2047:0] load_data,
  input logic [31:0] load_row_enable,
  output logic load_error,
  input logic cmd_valid,
  output logic cmd_ready,
  input logic [4:0] cmd_weight,
  input logic [4:0] cmd_mask,
  input logic [9:0] cmd_activation,
  input logic [3:0] cmd_output,
  input logic cmd_accumulate,
  input logic [1:0] cmd_reduce,
  output logic out_valid,
  input logic out_ready,
  output logic [3:0] out_output,
  output logic [1023:0] out_data,
  input logic [SIGN_WIDTH-1:0] merge_sign_data,
  input logic [12:0] merge_sign_control,
  output logic [23:0] merge_sign_counts,
  input logic [18:0] merge_table_request,
  output logic [79:0] merge_table_word,
  input tri_oracle_token_size_types::bank_command_t token_size_bank_command,
  output tri_oracle_token_size_types::bank_result_t token_size_bank_result,
  input tri_oracle_wac_softmax_types::request_t softmax_request,
  output tri_oracle_wac_softmax_types::response_t softmax_response,
  input logic activation_reloaded,
  input logic [2:0] core_score_select,
  input tri_oracle_merge_range_types::range_command_t merge_range_command,
  output tri_oracle_merge_range_types::range_result_t merge_range_result,
  input logic [79:0] global_merge_word,
  input logic [119:0] global_sign_counts,
  input logic strip_rst_n,
  input logic [530:0] strip_request,
  output logic [111:0] strip_response,
  input logic [396:0] head_request,
  output logic [72:0] head_response
);
  if (MERGE_FEATURES == 512 && AGGREGATOR_MERGE_TABLE == 1 && MERGE_TABLE_ENTRIES == 128 && MERGE_TABLE_START == 0 && LOCAL_TOKEN_SIZES == 1 && LOCAL_TOKEN_MERGE == 1 && CORE_STRIP_PREDICTOR == 1 && CORE_HEAD_PREDICTOR == 1) begin : selected_bank0
    tri_oracle_native_cluster0 block_instance (.*);
  end else if (MERGE_FEATURES == 384 && AGGREGATOR_MERGE_TABLE == 1 && MERGE_TABLE_ENTRIES == 128 && MERGE_TABLE_START == 128 && LOCAL_TOKEN_SIZES == 1 && LOCAL_TOKEN_MERGE == 1 && CORE_STRIP_PREDICTOR == 1 && CORE_HEAD_PREDICTOR == 1) begin : selected_bank1
    tri_oracle_native_cluster1 block_instance (.*);
  end else if (MERGE_FEATURES == 384 && AGGREGATOR_MERGE_TABLE == 1 && MERGE_TABLE_ENTRIES == 128 && MERGE_TABLE_START == 256 && LOCAL_TOKEN_SIZES == 1 && LOCAL_TOKEN_MERGE == 1 && CORE_STRIP_PREDICTOR == 1 && CORE_HEAD_PREDICTOR == 1) begin : selected_bank2
    tri_oracle_native_cluster2 block_instance (.*);
  end else if (MERGE_FEATURES == 384 && AGGREGATOR_MERGE_TABLE == 1 && MERGE_TABLE_ENTRIES == 128 && MERGE_TABLE_START == 384 && LOCAL_TOKEN_SIZES == 1 && LOCAL_TOKEN_MERGE == 1 && CORE_STRIP_PREDICTOR == 1 && CORE_HEAD_PREDICTOR == 1) begin : selected_bank3
    tri_oracle_native_cluster3 block_instance (.*);
  end else if (MERGE_FEATURES == 384 && AGGREGATOR_MERGE_TABLE == 1 && MERGE_TABLE_ENTRIES == 64 && MERGE_TABLE_START == 512 && LOCAL_TOKEN_SIZES == 1 && LOCAL_TOKEN_MERGE == 1 && CORE_STRIP_PREDICTOR == 1 && CORE_HEAD_PREDICTOR == 1) begin : selected_bank4
    tri_oracle_native_cluster4 block_instance (.*);
  end else begin : unsupported_configuration
    tri_oracle_invalid_cluster_partition invalid();
  end
endmodule
