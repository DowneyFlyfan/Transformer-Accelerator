`timescale 1ns/1ps
// Memory-backed one-row producer. All outputs are provisional until successful
// tagged completion; row_fault invalidates even a previously offered terminal.
module tri_oracle_memory_input_normalizer_wide_v1 (
  input logic clk,
  input logic rst_n,
  input logic cfg_valid,
  output logic cfg_ready,
  input logic [31:0] cfg_tag,
  input logic [9:0] cfg_strips,
  input logic [63:0] cfg_raw_base,
  input logic [63:0] cfg_gamma_base,
  input logic abort_valid,
  input logic [63:0] cfg_epsilon_q16,
  input logic signed [7:0] cfg_gamma_exponent,
  output logic out_valid,
  input logic out_ready,
  output logic out_last,
  output logic out_error,
  output logic [31:0] out_tag,
  output logic [9:0] out_index,
  output logic [3:0] out_count,
  output logic [63:0] out_activation,
  output logic signed [8:0] out_exponent,
  output logic [7:0] out_outlier_mask,
  output logic [7:0] out_outlier_negative,
  output logic [7:0] out_normalized_negative,
  output logic req_valid,
  input logic req_ready,
  output logic [63:0] req_address,
  output logic [4:0] req_length,
  input logic rsp_valid,
  output logic rsp_ready,
  input logic rsp_last,
  input logic rsp_error,
  input logic [63:0] rsp_data,
  output logic port_idle,
  output logic idle,
  output logic row_fault,
  output logic done_valid,
  input logic done_ready,
  output logic done_error,
  output logic [31:0] done_tag
);
  typedef enum logic [2:0] {Idle,Run,FaultDrain,CoreReset,WaitQuiescent,Done} state_t;
  state_t state;
  logic [31:0] tag;
  logic fault_latched, fault_now, reader_abort_fault, cfg_fire;
  logic reader_stats_valid, reader_stats_ready, reader_stats_last;
  logic reader_replay_valid, reader_replay_ready, reader_replay_last;
  logic [255:0] reader_stats_data, reader_replay_data;
  logic [191:0] reader_stats_gamma, reader_replay_gamma;
  logic reader_cfg_ready, reader_abort, reader_port_idle, reader_idle, reader_fault;
  logic reader_done_valid, reader_done_ready, reader_done_error;
  logic [31:0] reader_done_tag;
  logic reader_clear_valid, reader_clear_ready;
  logic reader_success, reader_success_now;
  logic core_rst_n, core_cfg_ready, core_out_valid, core_out_ready;
  logic core_out_last, core_out_error;
  logic [31:0] core_out_tag;
  logic [9:0] core_out_index;
  logic [3:0] core_out_count;
  logic [63:0] core_out_activation;
  logic signed [8:0] core_out_exponent;
  logic [7:0] core_out_outlier_mask, core_out_outlier_negative, core_out_normalized_negative;
  logic [144:0] skid_payload;
  logic skid_valid, core_fire, external_fire, terminal_accepted;

  assign cfg_ready = rst_n && state == Idle && reader_cfg_ready && core_cfg_ready &&
    reader_port_idle && !core_out_valid && !skid_valid && !abort_valid && !rsp_valid;
  assign cfg_fire = cfg_valid && cfg_ready;
  assign fault_now = reader_fault || ((state != Idle) && (abort_valid ||
    (core_out_valid && core_out_error) ||
    (reader_done_valid && (reader_done_error || reader_done_tag != tag))));
  assign row_fault = fault_latched || fault_now;
  // Reader bus faults already stop its own creation immediately. Feeding that
  // immediate return path into its abort input would form a combinational loop.
  assign reader_abort_fault = abort_valid || fault_latched ||
    (core_out_valid && core_out_error) ||
    (reader_done_valid && (reader_done_error || reader_done_tag != tag));
  assign reader_abort = (state == Run || state == FaultDrain) && reader_abort_fault;
  assign core_rst_n = rst_n && state != CoreReset;
  assign reader_clear_valid = state == CoreReset && !reader_idle && !reader_done_valid;
  assign reader_done_ready = rst_n && state != Idle;
  assign reader_success_now = reader_success || (reader_done_valid && reader_done_ready &&
    !reader_done_error && reader_done_tag == tag && !reader_fault && !abort_valid && !row_fault);
  assign core_out_ready = rst_n && state == Run && (!skid_valid || out_ready) &&
    !row_fault && !core_out_error && (!core_out_last || reader_success_now);
  assign core_fire = core_out_valid && core_out_ready;
  assign out_valid = rst_n && skid_valid;
  assign {out_last,out_error,out_tag,out_index,out_count,out_activation,out_exponent,
          out_outlier_mask,out_outlier_negative,out_normalized_negative} = skid_payload;
  assign external_fire = out_valid && out_ready;
  assign port_idle = reader_port_idle;
  assign idle = rst_n && state == Idle && reader_idle && core_cfg_ready &&
    !core_out_valid && !skid_valid && !cfg_valid && !abort_valid && !rsp_valid;
  assign done_valid = rst_n && state == Done;
  assign done_tag = tag;

  tri_oracle_raw32_gamma24_reader_v1 reader (
    .clk,.rst_n,.cfg_valid(cfg_fire),.cfg_ready(reader_cfg_ready),
    .cfg_tag,.cfg_strips,.cfg_raw_base,.cfg_gamma_base,.abort_valid(reader_abort),
    .stats_valid(reader_stats_valid),.stats_ready(reader_stats_ready),.stats_last(reader_stats_last),
    .stats_data(reader_stats_data),.stats_gamma(reader_stats_gamma),
    .replay_valid(reader_replay_valid),.replay_ready(reader_replay_ready),.replay_last(reader_replay_last),
    .replay_data(reader_replay_data),.replay_gamma(reader_replay_gamma),
    .req_valid,.req_ready,.req_address,.req_length,.rsp_valid,.rsp_ready,.rsp_last,.rsp_error,.rsp_data,
    .port_idle(reader_port_idle),.idle(reader_idle),.row_fault(reader_fault),
    .done_valid(reader_done_valid),.done_ready(reader_done_ready),
    .done_error(reader_done_error),.done_tag(reader_done_tag),
    .clear_valid(reader_clear_valid),.clear_ready(reader_clear_ready)
  );
  // Direct pair/ready connections persist through FaultDrain. Private reset,
  // rather than a fabricated ready, is the only way to cancel a blocked pair.
  tri_oracle_fused_input_sign_normalizer_wide_v1 #(.GAMMA_BITS(24)) normalizer (
    .clk,.rst_n(core_rst_n),.cfg_valid(cfg_fire),.cfg_ready(core_cfg_ready),
    .cfg_tag,.cfg_strips,.cfg_epsilon_q16,.cfg_gamma_exponent,
    .stats_valid(reader_stats_valid),.stats_ready(reader_stats_ready),.stats_last(reader_stats_last),
    .stats_data(reader_stats_data),.stats_gamma(reader_stats_gamma),
    .replay_valid(reader_replay_valid),.replay_ready(reader_replay_ready),.replay_last(reader_replay_last),
    .replay_data(reader_replay_data),.replay_gamma(reader_replay_gamma),
    .out_valid(core_out_valid),.out_ready(core_out_ready),.out_last(core_out_last),.out_error(core_out_error),
    .out_tag(core_out_tag),.out_index(core_out_index),.out_count(core_out_count),
    .out_activation(core_out_activation),.out_exponent(core_out_exponent),
    .out_outlier_mask(core_out_outlier_mask),.out_outlier_negative(core_out_outlier_negative),
    .out_normalized_negative(core_out_normalized_negative)
  );

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= Idle; tag <= 0; fault_latched <= 0; reader_success <= 0;
      skid_payload <= 0; skid_valid <= 0; terminal_accepted <= 0; done_error <= 0;
    end else if (cfg_fire) begin
      state <= Run; tag <= cfg_tag; fault_latched <= 0; reader_success <= 0;
      terminal_accepted <= 0; done_error <= 0;
    end else begin
      if (fault_now) fault_latched <= 1;
      if (reader_done_valid && reader_done_ready && !reader_done_error &&
          reader_done_tag == tag && !reader_fault && !abort_valid && !row_fault)
        reader_success <= 1;
      if (external_fire) begin
        skid_valid <= 0;
        if (out_last && !out_error) terminal_accepted <= 1;
      end
      if (core_fire) begin
        skid_valid <= 1;
        skid_payload <= {core_out_last,core_out_error,core_out_tag,core_out_index,core_out_count,
          core_out_activation,core_out_exponent,core_out_outlier_mask,
          core_out_outlier_negative,core_out_normalized_negative};
      end
      case (state)
        Idle: begin end
        Run: begin
          if (row_fault) state <= FaultDrain;
          else if (reader_success && terminal_accepted && reader_idle && reader_port_idle &&
                   core_cfg_ready && !core_out_valid && !skid_valid) begin
            done_error <= 0; state <= Done;
          end
        end
        FaultDrain: if (reader_port_idle && !req_valid && !rsp_valid && !skid_valid)
          state <= CoreReset;
        // The external skid and memory are already drained. An internal core
        // Search/Output/Error is unexposed and may be cancelled here.
        CoreReset: if (reader_idle || reader_done_valid || (reader_clear_valid && reader_clear_ready))
          state <= WaitQuiescent;
        WaitQuiescent: if (reader_idle && reader_port_idle && core_cfg_ready &&
                          !core_out_valid && !skid_valid && !req_valid && !rsp_valid) begin
          done_error <= 1; state <= Done;
        end
        // Late faults do not rewrite an already offered completion tuple.
        Done: if (done_ready) state <= Idle;
        default: state <= FaultDrain;
      endcase
    end
  end
endmodule
