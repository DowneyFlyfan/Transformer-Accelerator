`timescale 1ns/1ps

// The scalar client supplies its own burst length. The vector client supplies
// a byte address and receives eight consecutive words, lowest address first.
// A grant remains owned until the last beat and the client response handshake.
module tri_oracle_external_read_mux (
  input logic clk, rst_n,
  input logic scalar_req_valid,
  output logic scalar_req_ready,
  input logic [63:0] scalar_req_address,
  input logic [4:0] scalar_req_length,
  output logic scalar_rsp_valid,
  input logic scalar_rsp_ready,
  output logic scalar_rsp_last, scalar_rsp_error,
  output logic [63:0] scalar_rsp_data,
  input logic vector_req_valid,
  output logic vector_req_ready,
  input logic [63:0] vector_req_address,
  output logic vector_rsp_valid,
  input logic vector_rsp_ready,
  output logic vector_rsp_error,
  output logic [511:0] vector_rsp_data,
  output logic mem_req_valid,
  input logic mem_req_ready,
  output logic [63:0] mem_req_address,
  output logic [4:0] mem_req_length,
  input logic mem_rsp_valid,
  output logic mem_rsp_ready,
  input logic mem_rsp_last, mem_rsp_error,
  input logic [63:0] mem_rsp_data
);
  typedef enum logic [2:0] {
    Idle, RequestPending, ScalarResponse, VectorResponse, VectorDrain, VectorResult
  } state_t;

  state_t state;
  logic prefer_vector, locked_vector, grant_vector;
  logic accepting_request, request_transfer;
  logic [2:0] vector_word;
  logic [511:0] vector_data;
  logic vector_error;

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

    scalar_rsp_valid = state == ScalarResponse && mem_rsp_valid;
    scalar_rsp_last = mem_rsp_last;
    scalar_rsp_error = mem_rsp_error;
    scalar_rsp_data = mem_rsp_data;
    mem_rsp_ready = (state == ScalarResponse && scalar_rsp_ready)
                 || state == VectorResponse || state == VectorDrain;
    vector_rsp_valid = state == VectorResult;
    vector_rsp_error = vector_error;
    vector_rsp_data = vector_error ? '0 : vector_data;
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= Idle;
      prefer_vector <= 0;
      locked_vector <= 0;
      vector_word <= 0;
      vector_data <= '0;
      vector_error <= 0;
    end else begin
      case (state)
        Idle, RequestPending: begin
          if (request_transfer) begin
            prefer_vector <= !grant_vector;
            if (grant_vector) begin
              vector_word <= 0;
              vector_error <= 0;
              state <= VectorResponse;
            end else begin
              state <= ScalarResponse;
            end
          end else if (state == Idle && mem_req_valid) begin
            locked_vector <= grant_vector;
            state <= RequestPending;
          end
        end
        ScalarResponse: begin
          if (mem_rsp_valid && mem_rsp_ready && mem_rsp_last) state <= Idle;
        end
        VectorResponse: begin
          if (mem_rsp_valid && mem_rsp_ready) begin
            vector_data[vector_word*64 +: 64] <= mem_rsp_data;
            vector_error <= vector_error || mem_rsp_error || (mem_rsp_last != (vector_word == 7));
            if (mem_rsp_last) begin
              state <= VectorResult;
            end else if (vector_word == 7) begin
              state <= VectorDrain;
            end else begin
              vector_word <= vector_word + 1'b1;
            end
          end
        end
        VectorDrain: begin
          if (mem_rsp_valid && mem_rsp_last) state <= VectorResult;
        end
        VectorResult: begin
          if (vector_rsp_ready) state <= Idle;
        end
        default: state <= Idle;
      endcase
    end
  end
endmodule
