`timescale 1ns/1ps

// One command owns the layer until its completion transfers. The host sends
// the header, then the descriptor words in increasing bit order.
// Fifteen words preserve scalar behavior; a final sixteenth word equal to one
// preserves indexed V1. Nonfinal format two/three adds a final scale-table
// address and selects channel scales with ordinary/indexed weights respectively.
module tri_oracle_channel_indexed_dispatch #(
  parameter bit GROUPED_BATCHES = 1,
  localparam int COMMANDS = GROUPED_BATCHES ? 8 : 6,
  localparam int PAYLOAD_BITS = GROUPED_BATCHES ? 1664 : 960,
  localparam int WORD_INDEX_BITS = GROUPED_BATCHES ? 5 : 4
) (
  input  logic clk, rst_n,
  input  logic command_valid,
  output logic command_ready,
  input  logic [2:0] command_opcode,
  input  logic [31:0] command_tag,
  input  logic payload_valid,
  output logic payload_ready,
  input  logic [63:0] payload_data,
  input  logic payload_last,
  output logic response_valid,
  input  logic response_ready,
  output logic response_error,
  output logic [2:0] response_opcode,
  output logic [31:0] response_tag,
  output logic [COMMANDS-1:0] layer_command_valid,
  input  logic [COMMANDS-1:0] layer_command_ready,
  output logic [31:0] layer_command_tag,
  output logic [PAYLOAD_BITS-1:0] layer_command_payload,
  output logic layer_feedforward_indexed,
  output logic layer_feedforward_channel_scales,
  output logic [63:0] layer_feedforward_scale_base,
  input  logic [COMMANDS-1:0] layer_done_valid,
  output logic [COMMANDS-1:0] layer_done_ready,
  input  logic [COMMANDS-1:0] layer_done_error,
  input  logic [COMMANDS*32-1:0] layer_done_tag
);
  localparam logic [2:0] FEEDFORWARD = 3'd0;
  localparam logic [2:0] PROJECTION = 3'd1;
  localparam logic [2:0] TOKEN_MERGE = 3'd2;
  localparam logic [2:0] TOKEN_RESTORE = 3'd3;
  localparam logic [2:0] HEAD_PREDICTION = 3'd4;
  localparam logic [2:0] ATTENTION_ROW = 3'd5;
  localparam logic [2:0] GROUPED_ATTENTION = 3'd6;
  localparam logic [2:0] GROUPED_ATTENTION_BATCH = 3'd7;

  typedef enum logic [2:0] {Idle, Receive, Drain, Issue, Complete, FormatError, FeedforwardFormat, FeedforwardScaleBase} state_t;
  state_t state;
  logic [2:0] opcode;
  logic [WORD_INDEX_BITS-1:0] word_index;
  logic [COMMANDS-1:0] selected;
  logic expected_last, selected_done_valid, tag_error, indexed_descriptor;
  logic channel_descriptor;
  logic [63:0] scale_table_base;
  localparam logic [63:0] CHANNEL_WEIGHT_FORMAT = 64'd2;
  localparam logic [63:0] CHANNEL_INDEXED_WEIGHT_FORMAT = 64'd3;
  // 128 aligned words hold 16 three-bit decrements each, with zero padding.
  localparam logic [63:0] LAST_SCALE_TABLE_BASE = 64'hfffffffffffffc00;
  localparam logic [63:0] INDEXED_WEIGHT_FORMAT_V1 = 64'h1;

  assign layer_feedforward_indexed = indexed_descriptor && (state == Issue || state == Complete);
  assign layer_feedforward_channel_scales = channel_descriptor && (state == Issue || state == Complete);
  assign layer_feedforward_scale_base = layer_feedforward_channel_scales ? scale_table_base : 64'd0;

  function automatic logic [WORD_INDEX_BITS-1:0] descriptor_words(input logic [2:0] operation);
    case (operation)
      FEEDFORWARD: return WORD_INDEX_BITS'(15);
      PROJECTION: return WORD_INDEX_BITS'(9);
      TOKEN_MERGE, TOKEN_RESTORE: return WORD_INDEX_BITS'(1);
      HEAD_PREDICTION, ATTENTION_ROW: return WORD_INDEX_BITS'(3);
      GROUPED_ATTENTION: return GROUPED_BATCHES ? WORD_INDEX_BITS'(5) : '0;
      GROUPED_ATTENTION_BATCH: return GROUPED_BATCHES ? WORD_INDEX_BITS'(26) : '0;
      default: return '0;
    endcase
  endfunction

  assign selected = COMMANDS'(1) << opcode;
  assign expected_last = word_index + WORD_INDEX_BITS'(1) == descriptor_words(opcode);
  assign selected_done_valid = |(layer_done_valid & selected);
  assign tag_error = opcode != TOKEN_MERGE && opcode != TOKEN_RESTORE
                  && layer_done_tag[{opcode, 5'b0} +: 32] != layer_command_tag;

  assign command_ready = state == Idle;
  assign payload_ready = state == Receive || state == Drain || state == FeedforwardFormat || state == FeedforwardScaleBase;
  assign response_valid = state == FormatError || (state == Complete && selected_done_valid);
  assign response_error = state == FormatError || (state == Complete && selected_done_valid &&
                           ((|(layer_done_error & selected)) || tag_error));
  assign response_opcode = opcode;
  assign response_tag = layer_command_tag;
  assign layer_command_valid = state == Issue ? selected : '0;
  assign layer_done_ready = state == Complete && response_ready ? selected : '0;

  // Every word used by an issued command was written during Receive.
  always_ff @(posedge clk) begin
    if (state == Receive && payload_valid)
      layer_command_payload[{word_index, 6'b0} +: 64] <= payload_data;
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= Idle;
      opcode <= FEEDFORWARD;
      layer_command_tag <= '0;
      word_index <= '0;
      indexed_descriptor <= 0;
      channel_descriptor <= 0;
      scale_table_base <= '0;
    end else begin
      case (state)
        Idle: if (command_valid) begin
          opcode <= command_opcode;
          indexed_descriptor <= 0;
          channel_descriptor <= 0;
          scale_table_base <= 0;
          layer_command_tag <= command_tag;
          word_index <= '0;
          state <= descriptor_words(command_opcode) == 0 ? FormatError : Receive;
        end
        Receive: if (payload_valid) begin
          if (payload_last)
            state <= expected_last ? Issue : FormatError;
          else if (expected_last)
            state <= opcode == FEEDFORWARD ? FeedforwardFormat : Drain;
          else
            word_index <= word_index + WORD_INDEX_BITS'(1);
        end
        // The extension is consumed separately. The prior 960 bits,
        // including write-back scales, remain the base descriptor.
        FeedforwardFormat: if (payload_valid) begin
          if (payload_last) begin
            if (payload_data != INDEXED_WEIGHT_FORMAT_V1)
              state <= FormatError;
            else begin
              indexed_descriptor <= 1;
              state <= Issue;
            end
          end else if (payload_data == CHANNEL_WEIGHT_FORMAT ||
                       payload_data == CHANNEL_INDEXED_WEIGHT_FORMAT) begin
            indexed_descriptor <= payload_data[0];
            state <= FeedforwardScaleBase;
          end else
            state <= Drain;
        end
        // Only a complete, valid address enables the per-channel mode.
        // The extension never writes the base descriptor or stale upper slots.
        FeedforwardScaleBase: if (payload_valid) begin
          if (!payload_last)
            state <= Drain;
          else if (payload_data[2:0] != 3'b000 || payload_data > LAST_SCALE_TABLE_BASE)
            state <= FormatError;
          else begin
            scale_table_base <= payload_data;
            channel_descriptor <= 1;
            state <= Issue;
          end
        end
        Drain: if (payload_valid && payload_last) state <= FormatError;
        Issue: if (|(layer_command_ready & selected)) state <= Complete;
        Complete: if (selected_done_valid && response_ready) state <= Idle;
        FormatError: if (response_ready) state <= Idle;
        default: state <= Idle;
      endcase
    end
  end
endmodule
