`timescale 1ns/1ps
module tri_oracle_fabric_owner_mux_tb;
  import tri_oracle_fabric_owner_types::*;
  logic rst_n,projection_owned;
  request_t attention_request,projection_request,fabric_request;
  response_t attention_response,projection_response,fabric_response;
  request_t expected;
  tri_oracle_fabric_owner_mux dut(.*);
  task automatic check_owner(input bit owner);
    projection_owned=owner;
    expected=owner?projection_request:attention_request;
    expected.rst_n=rst_n && expected.rst_n;
    expected.load_valid=expected.load_valid && expected.rst_n;
    expected.cmd_valid=expected.cmd_valid && expected.rst_n;
    expected.out_ready=expected.out_ready & {5{expected.rst_n}};
    #1;
    if(fabric_request!==expected)$fatal(1,"OWNER_REQUEST_WRONG owner=%0d",owner);
    if(expected.rst_n)begin
      if(owner)begin
        if(projection_response!==fabric_response)$fatal(1,"PROJECTION_RESPONSE_WRONG");
        if(attention_response.load_error || attention_response.cmd_ready || attention_response.out_valid!=0)
          $fatal(1,"INACTIVE_ATTENTION_HANDSHAKE");
      end else begin
        if(attention_response!==fabric_response)$fatal(1,"ATTENTION_RESPONSE_WRONG");
        if(projection_response.load_error || projection_response.cmd_ready || projection_response.out_valid!=0)
          $fatal(1,"INACTIVE_PROJECTION_HANDSHAKE");
      end
    end else if(attention_response.load_error || attention_response.cmd_ready || attention_response.out_valid!=0 ||
                projection_response.load_error || projection_response.cmd_ready || projection_response.out_valid!=0)
      $fatal(1,"RESET_HANDSHAKE_EXPOSED");
  endtask
  initial begin
    rst_n=1;projection_owned=0;
    attention_request='0;projection_request='1;fabric_response='1;
    attention_request.rst_n=1;projection_request.rst_n=1;
    // Both producers remain active: only the granted one can reach the array.
    attention_request.load_valid=1;attention_request.cmd_valid=1;
    attention_request.out_ready=5'b10101;
    projection_request.out_ready=5'b01010;
    check_owner(0);check_owner(1);
    for(int trial=0;trial<64;trial++)begin
      for(int bit_index=0;bit_index<$bits(request_t);bit_index++)begin
        attention_request[bit_index]=1'($urandom);
        projection_request[bit_index]=1'($urandom);
      end
      for(int bit_index=0;bit_index<$bits(response_t);bit_index++)
        fabric_response[bit_index]=1'($urandom);
      attention_request.rst_n=1;projection_request.rst_n=1;
      check_owner(0);check_owner(1);
      rst_n=0;check_owner(0);check_owner(1);rst_n=1;
      attention_request.rst_n=0;check_owner(0);
      projection_request.rst_n=0;check_owner(1);
    end
    $display("FABRIC_OWNER_MUX_PASS checked_cases=386 request_bits=%0d response_bits=%0d",$bits(request_t),$bits(response_t));
    $finish;
  end
endmodule
