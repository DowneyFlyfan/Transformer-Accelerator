`timescale 1ns/1ps

// The scalar client supplies its burst length, data and byte strobes. The
// vector client supplies one cache line, sent low word first with all strobes set.
// The downstream response belongs to the client that owns the current burst.
module tri_oracle_external_write_mux (
  input logic clk, rst_n,
  input logic scalar_req_valid,
  output logic scalar_req_ready,
  input logic [63:0] scalar_req_address,
  input logic [4:0] scalar_req_length,
  input logic scalar_data_valid,
  output logic scalar_data_ready,
  input logic scalar_data_last,
  input logic [63:0] scalar_data,
  input logic [7:0] scalar_strobe,
  output logic scalar_rsp_valid,
  input logic scalar_rsp_ready,
  output logic scalar_rsp_error,
  input logic vector_req_valid,
  output logic vector_req_ready,
  input logic [63:0] vector_req_address,
  input logic [511:0] vector_req_data,
  output logic vector_rsp_valid,
  input logic vector_rsp_ready,
  output logic vector_rsp_error,
  output logic mem_req_valid,
  input logic mem_req_ready,
  output logic [63:0] mem_req_address,
  output logic [4:0] mem_req_length,
  output logic mem_data_valid,
  input logic mem_data_ready,
  output logic mem_data_last,
  output logic [63:0] mem_data,
  output logic [7:0] mem_strobe,
  input logic mem_rsp_valid,
  output logic mem_rsp_ready,
  input logic mem_rsp_error
);
  typedef enum logic [2:0] {
    Idle, RequestPending, ScalarData, VectorData, ScalarResponse, VectorResponse
  } state_t;

  state_t state;
  logic prefer_vector, locked_vector, grant_vector;
  logic accepting_request, request_transfer;
  logic [2:0] vector_word;
  logic [511:0] vector_payload;

  always_comb begin
    accepting_request = state == Idle || state == RequestPending;
    if (state == RequestPending) begin
      grant_vector = locked_vector;
    end else begin
      grant_vector = vector_req_valid && (!scalar_req_valid || prefer_vector);
    end
    mem_req_valid = accepting_request && (grant_vector ? vector_req_valid : scalar_req_valid);
    mem_req_address = grant_vector ? vector_req_address : scalar_req_address;
    mem_req_length = grant_vector ? 5'd8 : scalar_req_length;
    scalar_req_ready = accepting_request && !grant_vector && mem_req_ready;
    vector_req_ready = accepting_request && grant_vector && mem_req_ready;
    request_transfer = mem_req_valid && mem_req_ready;

    scalar_data_ready = state == ScalarData && mem_data_ready;
    mem_data_valid = (state == ScalarData && scalar_data_valid) || state == VectorData;
    mem_data_last = state == VectorData ? vector_word == 7 : scalar_data_last;
    mem_data = state == VectorData ? vector_payload[vector_word*64 +: 64] : scalar_data;
    mem_strobe = state == VectorData ? 8'hff : scalar_strobe;

    scalar_rsp_valid = state == ScalarResponse && mem_rsp_valid;
    vector_rsp_valid = state == VectorResponse && mem_rsp_valid;
    scalar_rsp_error = mem_rsp_error;
    vector_rsp_error = mem_rsp_error;
    mem_rsp_ready = (state == ScalarResponse && scalar_rsp_ready)
                 || (state == VectorResponse && vector_rsp_ready);
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= Idle;
      prefer_vector <= 0;
      locked_vector <= 0;
      vector_word <= 0;
      vector_payload <= '0;
    end else begin
      case (state)
        Idle, RequestPending: begin
          if (request_transfer) begin
            prefer_vector <= !grant_vector;
            if (grant_vector) begin
              vector_word <= 0;
              vector_payload <= vector_req_data;
              state <= VectorData;
            end else begin
              state <= ScalarData;
            end
          end else if (state == Idle && mem_req_valid) begin
            locked_vector <= grant_vector;
            state <= RequestPending;
          end
        end
        ScalarData: begin
          if (mem_data_valid && mem_data_ready && mem_data_last) state <= ScalarResponse;
        end
        VectorData: begin
          if (mem_data_ready) begin
            if (vector_word == 7) begin
              state <= VectorResponse;
            end else begin
              vector_word <= vector_word + 1'b1;
            end
          end
        end
        ScalarResponse, VectorResponse: begin
          if (mem_rsp_valid && mem_rsp_ready) state <= Idle;
        end
        default: state <= Idle;
      endcase
    end
  end
endmodule
