`timescale 1ns/1ps
module tri_oracle_projection_error_burst_probe (
 input logic clk,rst_n,req_valid,req_ready,rsp_valid,rsp_ready,rsp_error,rsp_last,
 input logic [63:0] req_address,
 input logic [4:0] req_length,
 input logic done_valid,done_ready,done_error,out_valid
);
 logic owned=0,saw_error=0;
 logic [63:0] address=0;
 int expected=0,accepted=0;
 always @(posedge clk)begin
  if(!rst_n)begin owned=0;saw_error=0;expected=0;accepted=0;address=0;end
  else begin
   if(out_valid)$fatal(1,"PROJECTION_OUTPUT_PRESENT_DURING_FAULT_CASE");
   if(req_valid && req_ready)begin
    if(owned)$fatal(1,"PROJECTION_REPLACED_OWNED_BURST");
    owned=1;address=req_address;expected=int'(req_length);accepted=0;saw_error=0;
   end
   if(rsp_valid && rsp_ready)begin
    if(!owned)$fatal(1,"PROJECTION_UNOWNED_RESPONSE");
    accepted++;
    if(rsp_error)saw_error=1;
    if(saw_error)$display("SHARED_ERROR_RESPONSE beat=%0d last=%0d error=%0d",accepted,rsp_last,rsp_error);
    if(rsp_last)begin
     if(accepted!=expected)$fatal(1,"PROJECTION_ERROR_DRAIN_LENGTH");
     owned=0;
     if(saw_error)$display("SHARED_ERROR_ACCEPTED_LAST address=%016h length=%0d",address,accepted);
    end
   end
   if(done_valid && done_ready && done_error)begin
    if(owned || !saw_error || address!=64'h200000 || expected!=16 || accepted!=16)
     $fatal(1,"PROJECTION_ERROR_COMPLETION_BEFORE_DRAIN");
    $display("SHARED_ERROR_TENSOR_COMPLETION drained_beats=16 error=1");
   end
  end
 end
endmodule
bind tri_oracle_metadata_projection_adapter tri_oracle_projection_error_burst_probe error_burst_witness(.*);
