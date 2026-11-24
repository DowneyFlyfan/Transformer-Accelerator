`timescale 1ns / 1ps

// Verification harness for the existing hardware writeback controller.
// Bypass words come only from accepted native attention-residual writes.
// External scale-memory behavior and expected-output observation live here;
// this harness does not establish physical storage or external-bus integration.
module tri_oracle_connected_writeback_checker #(
    parameter bit PREFIX_ONLY = 0
) (
    input logic clk,
    rst_n,
    enable,
    input logic raw_valid,
    raw_last,
    sink_ready,
    output logic raw_ready,
    input logic [31:0] raw_tag,
    input logic [3:0] raw_token,
    input logic [15:0] raw_start,
    input logic [7:0] raw_count,
    input logic [5119:0] raw_data,
    input logic frame_fault,
    output logic external_bank_read_valid,
    input logic external_bank_read_ready,
    output logic[8:0] external_bank_read_row,
    input logic external_bank_response_valid,external_bank_response_error,
    output logic external_bank_response_ready,
    input logic[231:0] external_bank_response_data,
    output logic external_scale_req_valid,
    input logic external_scale_req_ready,
    output logic[63:0] external_scale_req_address,
    output logic[4:0] external_scale_req_length,
    input logic external_scale_rsp_valid,external_scale_rsp_last,external_scale_rsp_error,
    output logic external_scale_rsp_ready,
    input logic[63:0] external_scale_rsp_data,
    input logic[63:0] scale_server_address,
    output logic[63:0] scale_server_data,
    output logic complete = 0,
    output logic idle
);
  localparam logic [63:0] ScaleBase = 64'h4000;
  logic configured = 0, frame_cfg_valid, frame_cfg_ready, frame_active, packet_error;
  logic bank_read_valid, bank_read_ready, bank_response_valid, bank_response_ready;
  logic [  8:0] bank_read_row;
  logic [231:0] bank_response_data;
  logic req_valid, req_ready, rsp_valid, rsp_ready, rsp_last, rsp_error;
  logic [63:0] req_address, rsp_data;
  logic [4:0] req_length;
  logic out_valid, out_last;
  logic [31:0] out_tag;
  logic [3:0] out_token, out_count;
  logic [15:0] out_start;
  logic [127:0] out_data;
  logic [9:0] bases[1];
  logic [63:0] scales[128];
  logic [127:0] expected[512];
  logic [511:0] seen = '0;
  logic [184:0] prior_output;
  logic [68:0] prior_scale_request;
  bit held_output = 0, held_scale_request = 0, corrupt_bypass;
  bit bank_busy = 0, scale_busy = 0;
  bit bank_request_fire, bank_response_fire, scale_request_fire, scale_response_fire;
  logic [ 8:0] requested_row;
  logic [63:0] requested_address;
  int cycle = 0, bank_delay = 0, scale_delay = 0;
  int output_words = 0, raw_packets = 0, bank_requests = 0, scale_requests = 0;
  int held_cycles = 0, final_file;
  string fixture;

  always_comb begin
    frame_cfg_valid = enable && !PREFIX_ONLY && !configured;
    external_bank_read_valid=bank_read_valid;external_bank_read_row=bank_read_row;
    external_bank_response_ready=bank_response_ready;
    bank_read_ready=external_bank_read_ready;bank_response_valid=external_bank_response_valid;
    bank_response_data=external_bank_response_data;
    external_scale_req_valid=req_valid;external_scale_req_address=req_address;external_scale_req_length=req_length;
    external_scale_rsp_ready=rsp_ready;req_ready=external_scale_req_ready;rsp_valid=external_scale_rsp_valid;
    rsp_data=external_scale_rsp_data;rsp_last=external_scale_rsp_last;rsp_error=external_scale_rsp_error;
    scale_server_data=scales[7'($unsigned((scale_server_address-ScaleBase)>>3))];
    idle = !frame_cfg_valid && !frame_active && !bank_busy && !scale_busy &&
           !bank_response_valid && !rsp_valid && !out_valid && !req_valid && !bank_read_valid;
  end

  tri_oracle_decoder_channel_writeback writeback (
      .clk,
      .rst_n,
      .lease_granted(enable),
      .frame_cfg_valid,
      .frame_abort(frame_fault),
      .frame_down_shifts(bases[0]),
      .frame_scale_base(ScaleBase),
      .frame_cfg_ready,
      .frame_active,
      .in_valid(raw_valid),
      .in_ready(raw_ready),
      .packet_error,
      .in_tag(raw_tag),
      .in_token(raw_token),
      .in_start(raw_start),
      .in_count(raw_count),
      .in_last(raw_last),
      .in_data(raw_data),
      .bank_read_valid,
      .bank_read_ready,
      .bank_read_row,
      .bank_response_valid,
      .bank_response_ready,
      .bank_response_data,
      .req_valid,
      .req_ready,
      .req_address,
      .req_length,
      .rsp_valid,
      .rsp_ready,
      .rsp_last,
      .rsp_error,
      .rsp_data,
      .out_valid,
      .out_ready(sink_ready),
      .out_tag,
      .out_token,
      .out_start,
      .out_count,
      .out_last,
      .out_data
  );

  always @(posedge clk) begin : observe
    int token, start, word_index;
    cycle <= !rst_n ? 0 : cycle + 1;
    bank_request_fire   = rst_n && bank_read_valid && bank_read_ready;
    bank_response_fire  = rst_n && bank_response_valid && bank_response_ready;
    scale_request_fire  = rst_n && req_valid && req_ready;
    scale_response_fire = rst_n && rsp_valid && rsp_ready;
    if (bank_request_fire) requested_row = bank_read_row;
    if (scale_request_fire) requested_address = req_address;
    if (!rst_n) begin
      configured <= 0;
      complete   <= 0;
      seen = '0;
      output_words = 0;
      raw_packets = 0;
      bank_requests = 0;
      scale_requests = 0;
      held_output = 0;
      held_scale_request = 0;
      held_cycles = 0;bank_busy<=0;scale_busy<=0;
    end else begin
      if (frame_cfg_valid && frame_cfg_ready) configured <= 1;
      if(bank_request_fire)bank_busy<=1;
      if(bank_response_fire)begin
        bank_busy<=0;
        if(external_bank_response_error)$fatal(1,"CONNECTED_WRITEBACK_BUS_BANK_ERROR");
        $display("CONNECTED_WRITEBACK_BYPASS_READ word=%0d data=%058h",requested_row,bank_response_data);
      end
      if(scale_request_fire)scale_busy<=1;
      if(scale_response_fire)scale_busy<=0;
      if ($isunknown(
              {
                raw_ready,
                frame_cfg_ready,
                frame_active,
                packet_error,
                bank_read_valid,
                bank_response_ready,
                req_valid,
                rsp_ready,
                out_valid
              }
          ))
        $fatal(1, "CONNECTED_WRITEBACK_UNKNOWN_PROTOCOL");
      if (PREFIX_ONLY && (raw_valid || frame_active || bank_busy || scale_busy))
        $fatal(1, "CONNECTED_WRITEBACK_PREFIX_NOT_IDLE");
      if (packet_error) $fatal(1, "CONNECTED_WRITEBACK_PACKET_ERROR");
      if (raw_valid && raw_ready) raw_packets++;
      if (bank_request_fire) bank_requests++;
      if (scale_request_fire) begin
        scale_requests++;
        if (req_length !== 5'd1 || req_address < ScaleBase ||
            req_address >= ScaleBase + 64'd1024 || req_address[2:0] !== 3'd0)
          $fatal(1, "CONNECTED_WRITEBACK_SCALE_REQUEST");
      end
      if (held_output && (!out_valid ||
          {out_tag, out_token, out_start, out_count, out_last, out_data} !== prior_output))
        $fatal(1, "CONNECTED_WRITEBACK_HELD_OUTPUT_CHANGED");
      held_output = out_valid && !sink_ready;
      if (held_output) begin
        prior_output = {out_tag, out_token, out_start, out_count, out_last, out_data};
        held_cycles++;
      end
      if (held_scale_request && (!req_valid || {req_address, req_length} !== prior_scale_request))
        $fatal(1, "CONNECTED_WRITEBACK_HELD_SCALE_REQUEST_CHANGED");
      held_scale_request = req_valid && !req_ready;
      if (held_scale_request) prior_scale_request = {req_address, req_length};
      if (out_valid && sink_ready) begin
        if (complete || output_words >= 512) $fatal(1, "CONNECTED_WRITEBACK_EXTRA_OUTPUT");
        if (output_words < 480) begin
          token = (output_words % 40) / 20;
          start = (output_words / 40) * 160 + (output_words % 20) * 8;
        end else begin
          token = (output_words - 480) / 16;
          start = 1920 + ((output_words - 480) % 16) * 8;
        end
        word_index = token * 256 + start / 8;
        if (out_tag !== 32'h3930_0001 || out_token !== 4'(token) ||
            out_start !== 16'(start) || out_count !== 4'd8 ||
            out_last !== (output_words == 511) || seen[word_index])
          $fatal(1, "CONNECTED_WRITEBACK_OUTPUT_COORDINATE");
        if (out_data !== expected[word_index])
          $fatal(
              1,
              "CONNECTED_WRITEBACK_VALUE token=%0d start=%0d got=%h expected=%h",
              token,
              start,
              out_data,
              expected[word_index]
          );
        seen[word_index] = 1;
        output_words++;
        $display("CONNECTED_WRITEBACK_TRACE token=%0d start=%0d data=%032h", token, start,
                 out_data);
        $fdisplay(final_file, "@%03h %032h", word_index, out_data);
        $fflush();
        if (out_last) begin
          if (seen !== {512{1'b1}} || output_words != 512 || raw_packets != 26 ||
              bank_requests != 512 || scale_requests != 256 || held_cycles == 0)
            $fatal(1, "CONNECTED_WRITEBACK_FINAL_INVENTORY");
          complete <= 1;
          $fclose(final_file);
          $display("CONNECTED_WRITEBACK_PASS words=512 values=4096 raw_packets=26");
        end
      end
    end
  end

  initial begin
    if (!$value$plusargs("WRITEBACK_ROOT=%s", fixture))
      $fatal(1, "CONNECTED_WRITEBACK_NO_METADATA");
    if($test$plusargs("CORRUPT_WRITEBACK_BYPASS"))$fatal(1,"WRITEBACK_CORRUPTION_MUST_TARGET_BUS_STORAGE");
    $readmemh({fixture, "/base_shifts.hex"}, bases);
    $readmemh({fixture, "/scale_words.hex"}, scales);
    $readmemh({fixture, "/expected.hex"}, expected);
    if ($isunknown(bases[0])) $fatal(1, "CONNECTED_WRITEBACK_UNKNOWN_BASE");
    foreach (scales[i]) if ($isunknown(scales[i])) $fatal(1, "CONNECTED_WRITEBACK_UNKNOWN_SCALE");
    foreach (expected[i])
    if ($isunknown(expected[i])) $fatal(1, "CONNECTED_WRITEBACK_UNKNOWN_ORACLE");
    final_file = $fopen("computed_final_q13.hex", "w");
    if (final_file == 0) $fatal(1, "CONNECTED_WRITEBACK_FILE_OPEN");
  end
endmodule
