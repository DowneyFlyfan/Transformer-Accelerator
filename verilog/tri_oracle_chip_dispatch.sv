`timescale 1ns/1ps

// One command owns the layer until its completion transfers. The host sends
// the header, then the descriptor words in increasing bit order.
module tri_oracle_chip_dispatch (
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
  output logic [5:0] layer_command_valid,
  input  logic [5:0] layer_command_ready,
  output logic [31:0] layer_command_tag,
  output logic [959:0] layer_command_payload,
  input  logic [5:0] layer_done_valid,
  output logic [5:0] layer_done_ready,
  input  logic [5:0] layer_done_error,
  input  logic [191:0] layer_done_tag
);
  localparam logic [2:0] FEEDFORWARD = 3'd0;
  localparam logic [2:0] PROJECTION = 3'd1;
  localparam logic [2:0] TOKEN_MERGE = 3'd2;
  localparam logic [2:0] TOKEN_RESTORE = 3'd3;
  localparam logic [2:0] HEAD_PREDICTION = 3'd4;
  localparam logic [2:0] ATTENTION_ROW = 3'd5;

  typedef enum logic [2:0] {Idle, Receive, Drain, Issue, Complete, FormatError} state_t;
  state_t state;
  logic [2:0] opcode;
  logic [3:0] word_index;
  logic [5:0] selected;
  logic expected_last, selected_done_valid, tag_error;

  function automatic logic [3:0] descriptor_words(input logic [2:0] operation);
    case (operation)
      FEEDFORWARD: return 4'd15;
      PROJECTION: return 4'd9;
      TOKEN_MERGE, TOKEN_RESTORE: return 4'd1;
      HEAD_PREDICTION, ATTENTION_ROW: return 4'd3;
      default: return 4'd0;
    endcase
  endfunction

  assign selected = 6'b1 << opcode;
  assign expected_last = word_index + 4'd1 == descriptor_words(opcode);
  assign selected_done_valid = |(layer_done_valid & selected);
  assign tag_error = opcode != TOKEN_MERGE && opcode != TOKEN_RESTORE
                  && layer_done_tag[{opcode, 5'b0} +: 32] != layer_command_tag;

  assign command_ready = state == Idle;
  assign payload_ready = state == Receive || state == Drain;
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
    end else begin
      case (state)
        Idle: if (command_valid) begin
          opcode <= command_opcode;
          layer_command_tag <= command_tag;
          word_index <= '0;
          state <= descriptor_words(command_opcode) == 0 ? FormatError : Receive;
        end
        Receive: if (payload_valid) begin
          if (payload_last)
            state <= expected_last ? Issue : FormatError;
          else if (expected_last)
            state <= Drain;
          else
            word_index <= word_index + 4'd1;
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
