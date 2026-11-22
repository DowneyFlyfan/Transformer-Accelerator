`timescale 1ns/1ps
// Stateless wiring only. The commit controller retains projection_owned
// until both the accepted projection command and its transport have drained.
// Inactive producers never observe a ready/valid/error handshake. Payload
// readback fans out without extra payload gates or storage.
module tri_oracle_fabric_owner_mux (
  input logic rst_n,projection_owned,
  input tri_oracle_fabric_owner_types::request_t attention_request,projection_request,
  output tri_oracle_fabric_owner_types::request_t fabric_request,
  input tri_oracle_fabric_owner_types::response_t fabric_response,
  output tri_oracle_fabric_owner_types::response_t attention_response,projection_response
);
  always_comb begin
    fabric_request=projection_owned ? projection_request : attention_request;
    fabric_request.rst_n=rst_n && fabric_request.rst_n;
    fabric_request.load_valid=fabric_request.load_valid && fabric_request.rst_n;
    fabric_request.cmd_valid=fabric_request.cmd_valid && fabric_request.rst_n;
    fabric_request.out_ready=fabric_request.out_ready & {5{fabric_request.rst_n}};
    attention_response=fabric_response;
    projection_response=fabric_response;
    attention_response.load_error=fabric_response.load_error && fabric_request.rst_n && !projection_owned;
    attention_response.cmd_ready=fabric_response.cmd_ready && fabric_request.rst_n && !projection_owned;
    attention_response.out_valid=fabric_response.out_valid & {5{fabric_request.rst_n && !projection_owned}};
    projection_response.load_error=fabric_response.load_error && fabric_request.rst_n && projection_owned;
    projection_response.cmd_ready=fabric_response.cmd_ready && fabric_request.rst_n && projection_owned;
    projection_response.out_valid=fabric_response.out_valid & {5{fabric_request.rst_n && projection_owned}};
  end
endmodule
