`timescale 1ns / 1ps
// Streams frame metadata before the existing raw32/gain24 row normalizer.
// Frame faults remain authoritative through retirement; recovery is coupled.
module tri_oracle_raw32_frame_source_v1 (
    input logic clk,
    input logic rst_n,
    input logic abort_valid,
    input logic cfg_valid,
    output logic cfg_ready,
    input logic cfg_new_image,
    input logic [31:0] cfg_tag_base,
    input logic [4:0] cfg_layer,
    input logic [15:0] cfg_epoch,
    input logic [9:0] cfg_image_start,
    input logic [9:0] cfg_input_rows,
    input logic [63:0] cfg_raw_frame_base,
    input logic [63:0] cfg_raw_frame_bytes,
    input logic [63:0] cfg_metadata_base,
    input logic [63:0] cfg_metadata_bytes,
    input logic [63:0] cfg_gamma_base,
    input logic [63:0] cfg_gamma_bytes,
    input logic signed [7:0] cfg_gamma_exponent,
    input logic row_request_valid,
    output logic row_request_ready,
    input logic [9:0] row_request_original_root,
    input logic [9:0] row_request_input_rank,
    input logic [31:0] row_request_tag,
    input logic [4:0] row_request_layer,
    input logic [15:0] row_request_epoch,
    output logic out_valid,
    output logic out_last,
    output logic out_error,
    input logic out_ready,
    output logic [31:0] out_tag,
    output logic [9:0] out_index,
    output logic [3:0] out_count,
    output logic [63:0] out_activation,
    output logic signed [8:0] out_exponent,
    output logic [7:0] out_outlier_mask,
    output logic [7:0] out_outlier_negative,
    output logic [7:0] out_normalized_negative,
    output logic read_req_valid,
    input logic read_req_ready,
    output logic [63:0] read_req_address,
    output logic [4:0] read_req_length,
    input logic read_rsp_valid,
    input logic read_rsp_last,
    input logic read_rsp_error,
    output logic read_rsp_ready,
    input logic [63:0] read_rsp_data,
    input logic retire_valid,
    output logic retire_ready,
    output logic row_source_error,
    output logic producer_idle,
    output logic port_idle,
    output logic idle,
    output logic [9:0] accepted_rows,
    output logic [9:0] completed_rows
);

  localparam int unsigned RowStrips = 256;
  localparam logic [63:0] RawRowBytes = 64'd8192;
  localparam logic [63:0] GainBytes = 64'd6144;
  localparam logic [63:0] MetadataBytes = 64'd16;
  localparam int unsigned MaximumRows = 576;
  typedef enum logic [3:0] {
    Idle,
    AwaitDemand,
    MetadataOffer,
    MetadataReceive,
    ValidateMetadata,
    ConfigureRow,
    RunRow,
    RetireRow,
    FaultDrain,
    ProtocolQuarantine
  } state_t;
  state_t state;
  logic frame_active, frame_fault;
  logic saved_new_image;
  logic [31:0] saved_tag_base;
  logic [4:0] saved_layer;
  logic [15:0] saved_epoch;
  logic [9:0] saved_image_start, saved_input_rows;
  logic [63:0] saved_raw_base, saved_metadata_base, saved_gamma_base;
  logic signed [7:0] saved_gamma_exponent;
  logic [9:0] row_root, row_rank;
  logic [31:0] row_tag;
  logic [ 4:0] row_layer;
  logic [15:0] row_epoch;
  logic [63:0] row_raw_address, metadata_address;
  logic [127:0] metadata_packet;
  logic [  1:0] metadata_beats;
  logic metadata_offered, metadata_owned;
  logic row_active, row_done_acknowledged;
  logic configuration_legal, demand_legal, metadata_legal;
  logic cfg_fire, demand_fire, metadata_request_fire, metadata_response_fire;
  logic row_cfg_valid, row_cfg_ready, row_cfg_fire;
  logic row_req_valid, row_req_ready, row_rsp_valid, row_rsp_ready;
  logic [63:0] row_req_address;
  logic [ 4:0] row_req_length;
  logic row_idle, row_port_idle, row_fault;
  logic row_done_valid, row_done_ready, row_done_error, row_done_fire;
  logic [31:0] row_done_tag;
  logic unknown_response, metadata_beat_fault, metadata_validation_fault;
  logic row_completion_fault, immediate_fault, quiet_row, retire_fire;
  logic [64:0] raw_last, metadata_last, gamma_last, needed_raw_bytes;
  logic [32:0] tag_last, requested_tag;
  logic [10:0] last_position, metadata_position;
  logic signed [7:0] metadata_raw_exponent;

  function automatic logic [63:0] physical_epsilon(input logic signed [7:0] exponent);
    logic [80:0] numerator, quotient;
    int signed shift;
    if (exponent >= 1 || exponent < -32) return 64'd0;
    shift = 16 - 2 * int'($signed(exponent));
    numerator = 81'd1 << shift;
    quotient = (numerator + 81'd50000) / 81'd100000;
    return quotient[63:0];
  endfunction

  always_comb begin
    raw_last = {1'b0, cfg_raw_frame_base} + {1'b0, cfg_raw_frame_bytes} - 65'd1;
    metadata_last = {1'b0, cfg_metadata_base} + {1'b0, cfg_metadata_bytes} - 65'd1;
    gamma_last = {1'b0, cfg_gamma_base} + {1'b0, cfg_gamma_bytes} - 65'd1;
    needed_raw_bytes = (65'(cfg_image_start) + 65'(cfg_input_rows)) * 65'(RawRowBytes);
    tag_last = {1'b0, cfg_tag_base} + 33'(MaximumRows - 1);
    last_position = {1'b0, cfg_image_start} + 11'(MaximumRows - 1);
    configuration_legal = cfg_input_rows != 0 && cfg_input_rows <= MaximumRows &&
      (!cfg_new_image || cfg_input_rows == MaximumRows) && !last_position[10] && !tag_last[32] &&
      cfg_raw_frame_base[5:0] == 0 && cfg_raw_frame_bytes != 0 && cfg_raw_frame_bytes[5:0] == 0 &&
      {1'b0,cfg_raw_frame_bytes} >= needed_raw_bytes && !raw_last[64] &&
      cfg_metadata_base[3:0] == 0 && cfg_metadata_bytes[3:0] == 0 &&
      {1'b0,cfg_metadata_bytes} >= 65'(cfg_input_rows) * 65'(MetadataBytes) && !metadata_last[64] &&
      cfg_gamma_base[2:0] == 0 && cfg_gamma_bytes == GainBytes && !gamma_last[64];

    requested_tag = {1'b0, saved_tag_base} + 33'(row_request_input_rank);
    demand_legal = row_request_input_rank == accepted_rows && row_request_input_rank < saved_input_rows &&
      row_request_original_root < MaximumRows && !requested_tag[32] &&
      row_request_tag == requested_tag[31:0] && row_request_layer == saved_layer &&
      row_request_epoch == saved_epoch && (!saved_new_image || row_request_original_root == row_request_input_rank);
    metadata_raw_exponent = $signed(metadata_packet[71:64]);
    metadata_position = {1'b0, saved_image_start} + {1'b0, row_root};
    metadata_legal = metadata_beats == 2 && metadata_packet[127:123] == 0 &&
      metadata_raw_exponent >= -32 && metadata_packet[81:72] == row_root &&
      metadata_packet[91:82] == row_rank && !metadata_position[10] &&
      metadata_packet[101:92] == metadata_position[9:0] && metadata_packet[106:102] == row_layer &&
      metadata_packet[122:107] == row_epoch &&
      metadata_packet[63:0] == physical_epsilon(metadata_raw_exponent);

    // Frame-configuration offers do not suppress row quiescence: the compactor
    // requires producer_idle on the very edge of atomic frame admission.
    unknown_response = rst_n && read_rsp_valid && !metadata_owned && !row_active;
    row_cfg_valid = rst_n && state == ConfigureRow && row_cfg_ready && !frame_fault &&
      !abort_valid && !unknown_response && !row_fault;
    row_cfg_fire = row_cfg_valid && row_cfg_ready;
    cfg_ready = rst_n && state == Idle && !frame_active && !frame_fault && row_idle && row_port_idle &&
      !abort_valid && !read_rsp_valid && !row_fault;
    cfg_fire = cfg_valid && cfg_ready;
    row_request_ready = rst_n && state == AwaitDemand && frame_active && !frame_fault &&
      !abort_valid && !read_rsp_valid && row_idle && row_port_idle && !row_active &&
      !metadata_offered && !metadata_owned && !row_fault;
    demand_fire = row_request_valid && row_request_ready;

    read_req_valid = rst_n && (metadata_offered || (row_active && row_req_valid));
    read_req_address = metadata_offered ? metadata_address : row_req_address;
    read_req_length = metadata_offered ? 5'd2 : row_req_length;
    row_req_ready = rst_n && row_active && !metadata_offered && !metadata_owned && read_req_ready;
    row_rsp_valid = rst_n && row_active && read_rsp_valid;
    read_rsp_ready = rst_n && (row_active ? row_rsp_ready : metadata_owned && state != ProtocolQuarantine);
    metadata_request_fire = metadata_offered && read_req_valid && read_req_ready;
    metadata_response_fire = metadata_owned && !row_active && read_rsp_valid && read_rsp_ready;
    metadata_beat_fault = metadata_response_fire &&
      (read_rsp_error || read_rsp_last != (metadata_beats == 1));
    metadata_validation_fault = state == ValidateMetadata && !metadata_legal;
    row_done_ready = rst_n && row_active;
    row_done_fire = row_done_valid && row_done_ready;
    row_completion_fault = row_done_fire && (row_done_error || row_done_tag != row_tag);
    immediate_fault = (frame_active && abort_valid) || unknown_response || metadata_beat_fault ||
      metadata_validation_fault || row_fault || row_completion_fault;
    row_source_error = frame_fault || immediate_fault;

    quiet_row = !metadata_offered && !metadata_owned && !row_active && !read_rsp_valid &&
      row_idle && row_port_idle && !row_cfg_valid && state != ProtocolQuarantine;
    producer_idle = rst_n && quiet_row && (state == Idle || state == AwaitDemand || state == FaultDrain);
    port_idle = rst_n && !metadata_offered && !metadata_owned && !read_rsp_valid && row_port_idle &&
      state != ProtocolQuarantine;
    retire_ready = rst_n && frame_active && producer_idle;
    retire_fire = retire_valid && retire_ready;
    idle = rst_n && state == Idle && !frame_active && producer_idle && !cfg_valid &&
      !row_request_valid && !retire_valid;
  end

  tri_oracle_memory_input_normalizer_wide_v1 row (
      .clk,
      .rst_n,
      .cfg_valid(row_cfg_valid),
      .cfg_ready(row_cfg_ready),
      .cfg_tag(row_tag),
      .cfg_strips(10'(RowStrips)),
      .cfg_raw_base(row_raw_address),
      .cfg_gamma_base(saved_gamma_base),
      .abort_valid(row_active && !row_done_acknowledged && (abort_valid || frame_fault)),
      .cfg_epsilon_q16(metadata_packet[63:0]),
      .cfg_gamma_exponent(saved_gamma_exponent),
      .out_valid,
      .out_ready,
      .out_last,
      .out_error,
      .out_tag,
      .out_index,
      .out_count,
      .out_activation,
      .out_exponent,
      .out_outlier_mask,
      .out_outlier_negative,
      .out_normalized_negative,
      .req_valid(row_req_valid),
      .req_ready(row_req_ready),
      .req_address(row_req_address),
      .req_length(row_req_length),
      .rsp_valid(row_rsp_valid),
      .rsp_ready(row_rsp_ready),
      .rsp_last(read_rsp_last),
      .rsp_error(read_rsp_error),
      .rsp_data(read_rsp_data),
      .port_idle(row_port_idle),
      .idle(row_idle),
      .row_fault,
      .done_valid(row_done_valid),
      .done_ready(row_done_ready),
      .done_error(row_done_error),
      .done_tag(row_done_tag)
  );

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= Idle;
      frame_active <= 0;
      frame_fault <= 0;
      saved_new_image <= 0;
      saved_tag_base <= 0;
      saved_layer <= 0;
      saved_epoch <= 0;
      saved_image_start <= 0;
      saved_input_rows <= 0;
      saved_raw_base <= 0;
      saved_metadata_base <= 0;
      saved_gamma_base <= 0;
      saved_gamma_exponent <= 0;
      row_root <= 0;
      row_rank <= 0;
      row_tag <= 0;
      row_layer <= 0;
      row_epoch <= 0;
      row_raw_address <= 0;
      metadata_address <= 0;
      metadata_packet <= 0;
      metadata_beats <= 0;
      metadata_offered <= 0;
      metadata_owned <= 0;
      row_active <= 0;
      row_done_acknowledged <= 0;
      accepted_rows <= 0;
      completed_rows <= 0;
    end else begin
      if (metadata_request_fire) begin
        metadata_offered <= 0;
        metadata_owned   <= 1;
        metadata_beats   <= 0;
      end
      if (metadata_response_fire) begin
        if (metadata_beats == 0) metadata_packet[63:0] <= read_rsp_data;
        if (metadata_beats == 1) metadata_packet[127:64] <= read_rsp_data;
        if (metadata_beats < 2) metadata_beats <= metadata_beats + 1'b1;
        if (read_rsp_last) metadata_owned <= 0;
      end
      if (row_done_fire) begin
        row_done_acknowledged <= 1;
        if (!row_done_error && row_done_tag == row_tag && !row_source_error)
          completed_rows <= completed_rows + 1'b1;
      end
      case (state)
        Idle:
        if (cfg_fire) begin
          saved_new_image <= cfg_new_image;
          saved_tag_base <= cfg_tag_base;
          saved_layer <= cfg_layer;
          saved_epoch <= cfg_epoch;
          saved_image_start <= cfg_image_start;
          saved_input_rows <= cfg_input_rows;
          saved_raw_base <= cfg_raw_frame_base;
          saved_metadata_base <= cfg_metadata_base;
          saved_gamma_base <= cfg_gamma_base;
          saved_gamma_exponent <= cfg_gamma_exponent;
          frame_active <= 1;
          accepted_rows <= 0;
          completed_rows <= 0;
          if (configuration_legal) state <= AwaitDemand;
          else begin
            frame_fault <= 1;
            state <= FaultDrain;
          end
        end
        AwaitDemand:
        if (demand_fire) begin
          accepted_rows <= accepted_rows + 1'b1;
          row_root <= row_request_original_root;
          row_rank <= row_request_input_rank;
          row_tag <= row_request_tag;
          row_layer <= row_request_layer;
          row_epoch <= row_request_epoch;
          if (demand_legal) begin
            row_raw_address <= saved_raw_base + (64'(saved_image_start) + 64'(row_request_input_rank)) * RawRowBytes;
            metadata_address <= saved_metadata_base + 64'(row_request_input_rank) * MetadataBytes;
            metadata_packet <= 0;
            metadata_beats <= 0;
            metadata_offered <= 1;
            state <= MetadataOffer;
          end else begin
            frame_fault <= 1;
            state <= FaultDrain;
          end
        end
        MetadataOffer: if (metadata_request_fire) state <= MetadataReceive;
        MetadataReceive:
        if (metadata_response_fire && read_rsp_last)
          state <= metadata_beat_fault ? FaultDrain : ValidateMetadata;
        ValidateMetadata:
        if (metadata_legal) state <= ConfigureRow;
        else begin
          frame_fault <= 1;
          state <= FaultDrain;
        end
        ConfigureRow:
        if (row_cfg_fire) begin
          row_active <= 1;
          row_done_acknowledged <= 0;
          state <= RunRow;
        end
        RunRow: if (row_done_fire) state <= RetireRow;
        RetireRow:
        if (row_idle && row_port_idle && !row_req_valid && !read_rsp_valid && !out_valid) begin
          row_active <= 0;
          state <= AwaitDemand;
        end
        FaultDrain:
        if (row_active && row_done_acknowledged && row_idle && row_port_idle &&
                       !row_req_valid && !read_rsp_valid && !out_valid)
          row_active <= 0;
        ProtocolQuarantine: begin
        end
        default: begin
          frame_fault <= 1;
          state <= ProtocolQuarantine;
        end
      endcase
      if (immediate_fault) begin
        frame_fault <= 1;
        if (state != ProtocolQuarantine) state <= FaultDrain;
      end
      if (retire_fire) begin
        frame_active <= 0;
        state <= Idle;
        if (!frame_fault && (accepted_rows != saved_input_rows || completed_rows != saved_input_rows))
          frame_fault <= 1;
      end
      // An unknown association is not made safe by observing an arbitrary LAST.
      // Retain an already offered request; only coupled reset clears quarantine.
      if (unknown_response) begin
        frame_fault <= 1;
        state <= ProtocolQuarantine;
      end
    end
  end
endmodule
