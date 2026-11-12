`timescale 1ns/1ps

// Each 512-bit response contains eight consecutive output rows at one
// feature-word address. Lane zero is the lowest row in the selected group.
// The compute owner must discard staged weights if the burst reports an error.
module tri_oracle_wide_weight_loader (
  input  logic clk, rst_n,
  input  logic cfg_valid,
  output logic cfg_ready,
  input  logic [63:0] cfg_address,
  input  logic [4:0] cfg_core, cfg_first_word,
  input  logic [1:0] cfg_row_group,
  input  logic [7:0] cfg_row_enable,
  input  logic [5:0] cfg_words,
  output logic done_valid,
  input  logic done_ready,
  output logic done_error,

  output logic req_valid,
  input  logic req_ready,
  output logic [63:0] req_address,
  output logic [5:0] req_length,
  input  logic rsp_valid,
  output logic rsp_ready,
  input  logic rsp_last, rsp_error,
  input  logic [511:0] rsp_data,

  output logic load_valid,
  input  logic load_ready,
  output logic [4:0] load_core,
  output logic [9:0] load_addr,
  output logic [31:0] load_row_enable,
  output logic [2047:0] load_data
);
  typedef enum logic [2:0] {Idle, Request, Receive, Drain, Done} state_t;
  state_t state;
  logic [4:0] word_address;
  logic [5:0] words_remaining;
  logic [1:0] row_group;
  logic [7:0] row_enable;
  logic [6:0] end_word;
  logic [58:0] last_response_block;
  logic invalid_config, response_bad;

  assign end_word = {2'b0, cfg_first_word} + {1'b0, cfg_words};
  assign last_response_block = {1'b0, cfg_address[63:6]} + 59'(cfg_words) - 59'd1;
  assign invalid_config = cfg_words == 0 || end_word > 7'd32 || cfg_core >= 5'd20
                       || cfg_row_enable == 0 || cfg_address[5:0] != 0 || last_response_block[58];
  assign cfg_ready = rst_n && state == Idle;
  assign req_valid = rst_n && state == Request;
  assign done_valid = rst_n && state == Done;
  assign response_bad = rsp_valid && (rsp_error || rsp_last != (words_remaining == 6'd1));
  assign load_valid = rst_n && state == Receive && rsp_valid && !response_bad;
  assign rsp_ready = rst_n && (state == Drain || (state == Receive && (load_ready || response_bad)));
  assign load_addr = {5'b0, word_address};

  always_comb begin
    load_data = '0;
    load_data[{row_group, 9'b0} +: 512] = rsp_data;
    load_row_enable = '0;
    load_row_enable[{row_group, 3'b0} +: 8] = row_enable;
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= Idle;
      done_error <= 0;
      req_address <= 0;
      req_length <= 0;
      load_core <= 0;
      word_address <= 0;
      words_remaining <= 0;
      row_group <= 0;
      row_enable <= 0;
    end else begin
      case (state)
        Idle: if (cfg_valid) begin
          req_address <= cfg_address;
          req_length <= cfg_words;
          load_core <= cfg_core;
          word_address <= cfg_first_word;
          words_remaining <= cfg_words;
          row_group <= cfg_row_group;
          row_enable <= cfg_row_enable;
          done_error <= invalid_config;
          state <= invalid_config ? Done : Request;
        end
        Request: if (req_ready) state <= Receive;
        Receive: if (rsp_valid && rsp_ready) begin
          if (response_bad) begin
            done_error <= 1;
            state <= rsp_last ? Done : Drain;
          end else if (rsp_last) begin
            state <= Done;
          end else begin
            word_address <= word_address + 5'd1;
            words_remaining <= words_remaining - 6'd1;
          end
        end
        Drain: if (rsp_valid && rsp_last) state <= Done;
        Done: if (done_ready) state <= Idle;
        default: state <= Idle;
      endcase
    end
  end
endmodule
