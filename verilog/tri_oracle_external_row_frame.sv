`timescale 1ns/1ps
// Prepared external controller; original algorithm/control preserved.
module tri_oracle_external_row_frame (
  input logic clk,rst_n,cfg_valid,
  input logic cfg_row_enable,cfg_correction_enable,
  input logic [63:0] cfg_row_units_base,
  output logic cfg_ready,
  input logic [31:0] cfg_tag,
  input logic [4:0] cfg_tokens,
  input logic [15:0] cfg_input_features,cfg_intermediate_features,
  input logic [16:0] cfg_output_features,
  input logic [63:0] cfg_activation_base,cfg_gate_base,cfg_up_base,cfg_down_base,cfg_intermediate_base,
  input logic [31:0] cfg_activation_stride,
  input logic [95:0] cfg_gate_shifts,cfg_up_shifts,cfg_down_shifts,
  input logic mask_valid,mask_last,
  output logic mask_ready,
  input logic [31:0] mask_tag,
  input logic [15:0] mask_start,
  input logic [6:0] mask_count,
  input logic [1279:0] mask_bits,
  output logic out_valid,
  input logic out_ready,
  output logic [31:0] out_tag,
  output logic [3:0] out_token,
  output logic [15:0] out_start,
  output logic [7:0] out_count,
  output logic out_last,
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
  output logic wr_req_valid,
  input logic wr_req_ready,
  output logic [63:0] wr_address,
  output logic [4:0] wr_length,
  output logic wr_data_valid,
  input logic wr_data_ready,
  output logic [63:0] wr_data,
  output logic [7:0] wr_strobe,
  output logic wr_data_last,
  input logic wr_rsp_valid,wr_rsp_error,
  output logic wr_rsp_ready,
  input logic attention_enable,
  tri_oracle_attention_tensor437.server attention,
  input tri_oracle_wac_softmax_types::request_t softmax_request,
  output tri_oracle_fabric_owner_types::request_t backend_request,
  input tri_oracle_fabric_owner_types::response_t backend_response
);
  logic row_enable;
  typedef enum logic [1:0] {MetaIdle,MetaFetch,MetaRun} meta_state_t;
  meta_state_t meta_state;
  logic descriptor_reject,controller_cfg_ready,frame_done_valid,frame_done_error;
  logic metadata_descriptor_bad,attention_owner;
  logic [31:0] descriptor_tag,frame_done_tag;
  logic [64:0] metadata_end,activation_end,gate_end,up_end,down_end,scratch_end;
  logic [5:0] gate_base_max,up_base_max;
  logic [2:0] gate_offset_max,up_offset_max;
  logic [6:0] gate_shift_max,up_shift_max;
  tri_oracle_wac_softmax_types::request_t tensor_mode;
  function automatic logic metadata_overlaps(input logic [63:0] base_address,input logic [64:0] end_address);
    return {1'b0,cfg_row_units_base}<=end_address && {1'b0,base_address}<=metadata_end;
  endfunction
  logic [63:0] row_base;
  logic [15:0] row_total;
  logic compute_cfg_valid,compute_cfg_paired,compute_cfg_packed_weights,compute_ready;
  logic [31:0] compute_cfg_tag,compute_cfg_activation_stride;
  logic [4:0] compute_cfg_tokens;
  logic [9:0] compute_cfg_feature_words;
  logic [16:0] compute_cfg_dense_rows;
  logic [7:0] compute_cfg_count;
  logic [2559:0] compute_cfg_channels,compute_cfg_keep;
  logic [63:0] compute_cfg_activation_base,compute_cfg_weight_base,compute_cfg_up_weight_base;
  logic [95:0] compute_cfg_gate_shifts,compute_cfg_up_shifts,compute_cfg_down_shifts;
  logic compute_hold_primary,compute_append_correction,compute_clear_context;
  logic compute_out_valid,compute_out_ready,compute_last;
  logic [31:0] compute_tag,compute_done_tag;
  logic [3:0] compute_token;
  logic [7:0] compute_count;
  logic [2559:0] compute_channels;
  logic [5119:0] compute_data;
  logic [639:0] compute_down;
  logic compute_done_valid,compute_done_ready,compute_done_error;
  logic shared_ready,shared_cfg_valid,shared_done_valid,shared_done_error;
  logic [31:0] shared_done_tag;
  logic shared_req_valid,shared_req_ready,shared_rsp_ready;
  logic [63:0] shared_req_address;
  logic [4:0] shared_req_length;
  logic metadata_active,metadata_needed,metadata_cfg_valid,metadata_cfg_ready;
  logic metadata_valid,metadata_ready,metadata_error,metadata_bad;
  logic metadata_req_valid,metadata_rsp_ready;
  logic [31:0] metadata_tag;
  logic [15:0] metadata_start;
  logic [6:0] metadata_count;
  logic [479:0] metadata_units;
  logic [63:0] metadata_req_address;
  logic [4:0] metadata_req_length;
  logic local_error;
  logic [31:0] local_error_tag;

  // The frame holds its gate descriptor until the packet has fully arrived.
  // Metadata and tensor traffic are mutually exclusive for the entire burst.
  // A failed fetch consumes the held command and returns one error terminal;
  // it never starts tensor or nonlinear computation.
  always_comb begin
    metadata_end={1'b0,cfg_row_units_base}+((65'(cfg_intermediate_features)+65'd79)/65'd80)*65'd64-65'd1;
    activation_end={1'b0,cfg_activation_base}+(65'(cfg_tokens)-65'd1)*65'(cfg_activation_stride)+65'(cfg_input_features)-65'd1;
    gate_end={1'b0,cfg_gate_base}+65'(cfg_intermediate_features)*65'(cfg_input_features)-65'd1;
    up_end={1'b0,cfg_up_base}+65'(cfg_intermediate_features)*65'(cfg_input_features)-65'd1;
    down_end={1'b0,cfg_down_base}+65'(cfg_output_features)*65'(cfg_intermediate_features)-65'd1;
    scratch_end={1'b0,cfg_intermediate_base}+(cfg_correction_enable ? 65'd2 : 65'd1)*65'(cfg_tokens)*65'(cfg_intermediate_features)-65'd1;
    metadata_descriptor_bad=cfg_row_enable && (cfg_row_units_base[5:0]!=0 || metadata_end[64] ||
      metadata_overlaps(cfg_activation_base,activation_end) || metadata_overlaps(cfg_gate_base,gate_end) ||
      metadata_overlaps(cfg_up_base,up_end) || metadata_overlaps(cfg_down_base,down_end) || metadata_overlaps(cfg_intermediate_base,scratch_end));
    cfg_ready=!descriptor_reject && controller_cfg_ready;
    done_valid=descriptor_reject || frame_done_valid;
    done_error=descriptor_reject || frame_done_error;
    done_tag=descriptor_reject ? descriptor_tag : frame_done_tag;
    gate_base_max=0;up_base_max=0;gate_offset_max=0;up_offset_max=0;
    for(int t=0;t<16;t++)if(t<int'(compute_cfg_tokens))begin
      if(compute_cfg_gate_shifts[t*6+:6]>gate_base_max)gate_base_max=compute_cfg_gate_shifts[t*6+:6];
      if(compute_cfg_up_shifts[t*6+:6]>up_base_max)up_base_max=compute_cfg_up_shifts[t*6+:6];
    end
    for(int c=0;c<80;c++)if(c<int'(compute_cfg_count))begin
      if(metadata_units[c*6+:3]>gate_offset_max)gate_offset_max=metadata_units[c*6+:3];
      if(metadata_units[c*6+3+:3]>up_offset_max)up_offset_max=metadata_units[c*6+3+:3];
    end
    gate_shift_max={1'b0,gate_base_max}+7'(gate_offset_max);
    up_shift_max={1'b0,up_base_max}+7'(up_offset_max);
    metadata_active=meta_state==MetaFetch && !metadata_valid;
    metadata_needed=compute_cfg_paired && row_enable;
    metadata_cfg_valid=compute_cfg_valid && metadata_needed && meta_state==MetaIdle && !local_error;
    metadata_bad=metadata_error || metadata_tag!=compute_cfg_tag ||
      metadata_start!=compute_cfg_channels[15:0] || metadata_count!=compute_cfg_count[6:0] || gate_shift_max[6] || up_shift_max[6];
    compute_ready=!local_error && (metadata_needed ?
      meta_state==MetaFetch && metadata_valid && (metadata_bad || shared_ready) : shared_ready);
    shared_cfg_valid=compute_cfg_valid && !local_error &&
      (!metadata_needed || (meta_state==MetaFetch && metadata_valid && !metadata_bad));
    metadata_ready=(meta_state==MetaFetch && compute_cfg_valid && compute_ready && metadata_bad) ||
      (meta_state==MetaRun && shared_done_valid && compute_done_ready);
    // A waiting attention client cannot lend score-mode bits to a feed-forward
    // command. Qualify those fields by the actual admission and ownership.
    tensor_mode=softmax_request;
    if(!(attention_owner || (attention.cfg_valid && attention.cfg_ready)))begin
      tensor_mode.score_tile=0;tensor_mode.score_core=0;tensor_mode.owner=0;
    end
    compute_done_valid=local_error || shared_done_valid;
    compute_done_error=local_error || shared_done_error;
    compute_done_tag=local_error ? local_error_tag : shared_done_tag;
    req_valid=metadata_active ? metadata_req_valid : shared_req_valid;
    req_address=metadata_active ? metadata_req_address : shared_req_address;
    req_length=metadata_active ? metadata_req_length : shared_req_length;
    shared_req_ready=!metadata_active && req_ready;
    rsp_ready=metadata_active ? metadata_rsp_ready : shared_rsp_ready;
  end

  always_ff @(posedge clk or negedge rst_n)begin
    if(!rst_n)begin
      row_enable<=0;row_base<=0;row_total<=0;meta_state<=MetaIdle;
      descriptor_reject<=0;descriptor_tag<=0;attention_owner<=0;
      local_error<=0;local_error_tag<=0;
    end else begin
      if(cfg_valid && cfg_ready)begin
        row_enable<=cfg_row_enable;row_base<=cfg_row_units_base;row_total<=cfg_intermediate_features;
        descriptor_reject<=metadata_descriptor_bad;descriptor_tag<=cfg_tag;
      end
      if(descriptor_reject && done_ready)descriptor_reject<=0;
      if(attention.cfg_valid && attention.cfg_ready)attention_owner<=1;
      else if(attention.done_valid && attention.done_ready)attention_owner<=0;
      if(metadata_cfg_valid && metadata_cfg_ready)meta_state<=MetaFetch;
      if(meta_state==MetaFetch && metadata_valid && compute_cfg_valid && compute_ready)begin
        if(metadata_bad)begin meta_state<=MetaIdle;local_error<=1;local_error_tag<=compute_cfg_tag;end
        else meta_state<=MetaRun;
      end
      if(meta_state==MetaRun && shared_done_valid && compute_done_ready)meta_state<=MetaIdle;
      if(local_error && compute_done_ready)local_error<=0;
    end
  end

  tri_oracle_row_metadata_reader metadata (
    .clk,.rst_n,.cfg_valid(metadata_cfg_valid),.cfg_ready(metadata_cfg_ready),
    .cfg_tag(compute_cfg_tag),.cfg_base(row_base),.cfg_total(row_total),.cfg_start(compute_cfg_channels[15:0]),
    .out_valid(metadata_valid),.out_ready(metadata_ready),.out_error(metadata_error),
    .out_tag(metadata_tag),.out_start(metadata_start),.out_count(metadata_count),.out_units(metadata_units),
    .req_valid(metadata_req_valid),.req_ready(metadata_active && req_ready),
    .req_address(metadata_req_address),.req_length(metadata_req_length),
    .rsp_valid(metadata_active && rsp_valid),.rsp_ready(metadata_rsp_ready),.rsp_last,.rsp_error,.rsp_data
  );

  tri_oracle_external_row_shared compute (
    .clk,.rst_n,.cfg_valid(shared_cfg_valid),.cfg_ready(shared_ready),.cfg_paired(compute_cfg_paired),
    .cfg_hold_primary(compute_hold_primary),.cfg_append_correction(compute_append_correction),
    .cfg_clear_context(compute_clear_context),.cfg_row_units(row_enable ? metadata_units : 480'b0),
    .cfg_tag(compute_cfg_tag),.cfg_tokens(compute_cfg_tokens),.cfg_feature_words(compute_cfg_feature_words),
    .cfg_dense_rows(compute_cfg_dense_rows),.cfg_count(compute_cfg_count),
    .cfg_channels(compute_cfg_channels),.cfg_keep(compute_cfg_keep),
    .cfg_activation_base(compute_cfg_activation_base),.cfg_weight_base(compute_cfg_weight_base),
    .cfg_up_weight_base(compute_cfg_up_weight_base),.cfg_activation_stride(compute_cfg_activation_stride),
    .cfg_gate_shifts(compute_cfg_gate_shifts),.cfg_up_shifts(compute_cfg_up_shifts),.cfg_down_shifts(compute_cfg_down_shifts),
    .out_valid(compute_out_valid),.out_ready(compute_out_ready),.out_tag(compute_tag),.out_token(compute_token),
    .out_last(compute_last),.out_count(compute_count),.out_channels(compute_channels),
    .out_data(compute_data),.out_down_input(compute_down),
    .done_valid(shared_done_valid),.done_ready(compute_done_ready && !local_error),
    .done_error(shared_done_error),.done_tag(shared_done_tag),
    .req_valid(shared_req_valid),.req_ready(shared_req_ready),.req_address(shared_req_address),.req_length(shared_req_length),
    .rsp_valid(!metadata_active && rsp_valid),.rsp_ready(shared_rsp_ready),.rsp_last,.rsp_error,.rsp_data,
    .softmax_request(tensor_mode),.backend_request,.backend_response
  );

  tri_oracle_correction_frame_control #(.PACKED_FEEDFORWARD_WEIGHTS(0)) controller (
    .clk,.rst_n,.cfg_valid(cfg_valid && !metadata_descriptor_bad && !descriptor_reject),.cfg_correction_enable,.cfg_ready(controller_cfg_ready),.cfg_tag,.cfg_tokens,
    .cfg_input_features,.cfg_intermediate_features,.cfg_output_features,
    .cfg_activation_base,.cfg_gate_base,.cfg_up_base,.cfg_down_base,.cfg_intermediate_base,
    .cfg_activation_stride,.cfg_gate_shifts,.cfg_up_shifts,.cfg_down_shifts,
    .mask_valid,.mask_last,.mask_ready,.mask_tag,.mask_start,.mask_count,.mask_bits,
    .out_valid,.out_ready,.out_tag,.out_token,.out_start,.out_count,.out_last,.out_data,
    .done_valid(frame_done_valid),.done_ready,.done_error(frame_done_error),.done_tag(frame_done_tag),
    .wr_req_valid,.wr_req_ready,.wr_address,.wr_length,.wr_data_valid,.wr_data_ready,
    .wr_data,.wr_strobe,.wr_data_last,.wr_rsp_valid,.wr_rsp_error,.wr_rsp_ready,
    .attention_enable(attention_enable && !descriptor_reject && !(cfg_valid && metadata_descriptor_bad)),.attention_cfg_valid(attention.cfg_valid),.attention_cfg_ready(attention.cfg_ready),
    .attention_cfg_tag(attention.cfg_tag),.attention_cfg_activation_stride(attention.cfg_activation_stride),
    .attention_cfg_tokens(attention.cfg_tokens),.attention_cfg_feature_words(attention.cfg_feature_words),
    .attention_cfg_dense_rows(attention.cfg_dense_rows),.attention_cfg_count(attention.cfg_count),
    .attention_cfg_channels(attention.cfg_channels),.attention_cfg_keep(attention.cfg_keep),
    .attention_cfg_activation_base(attention.cfg_activation_base),.attention_cfg_weight_base(attention.cfg_weight_base),
    .attention_out_ready(attention.out_ready),.attention_done_ready(attention.done_ready),
    .attention_out_valid(attention.out_valid),.attention_out_last(attention.out_last),
    .attention_out_tag(attention.out_tag),.attention_out_token(attention.out_token),
    .attention_out_count(attention.out_count),.attention_out_channels(attention.out_channels),.attention_out_data(attention.out_data),
    .attention_done_valid(attention.done_valid),.attention_done_error(attention.done_error),.attention_done_tag(attention.done_tag),
    .compute_cfg_valid,.compute_cfg_paired,.compute_cfg_packed_weights,.compute_ready,
    .compute_cfg_tag,.compute_cfg_activation_stride,.compute_cfg_tokens,.compute_cfg_feature_words,
    .compute_cfg_dense_rows,.compute_cfg_count,.compute_cfg_channels,.compute_cfg_keep,
    .compute_cfg_activation_base,.compute_cfg_weight_base,.compute_cfg_up_weight_base,
    .compute_cfg_gate_shifts,.compute_cfg_up_shifts,.compute_cfg_down_shifts,
    .compute_hold_primary,.compute_append_correction,.compute_clear_context,
    .compute_out_valid,.compute_last,.compute_out_ready,.compute_tag,.compute_token,.compute_count,.compute_channels,
    .compute_data,.compute_down,.compute_done_valid,.compute_done_error,.compute_done_ready,.compute_done_tag
  );
endmodule
