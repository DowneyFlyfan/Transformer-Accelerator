`timescale 1ns/1ps
// Source candidate. The asynchronous reset is the genuine COUPLED epoch reset.
// No parent aggregate fault is copied combinationally into a child abort.
module tri_oracle_FF_registered_poison_v1 #(
  parameter int unsigned FaultBits=8
)(
  input logic clk,rst_n,active,owner_held,
  input logic external_cancel_q,
  input logic [FaultBits-1:0] fault_observations,
  output logic poison_q,abort_registered,fresh_work_permitted
);
  // external_cancel_q is an independent already-registered cancellation from
  // the stage owner. It must never be wired to a child's combinational fault.
  // Required unknowns are converted to known failure, rather than healed by
  // returning to0. Only a real coupled epoch reset may clear poison_q.
  always_ff @(posedge clk or negedge rst_n)begin
    if(rst_n===1'b0)poison_q<=1'b0;
    else if(rst_n!==1'b1 || external_cancel_q!==1'b0 ||
      fault_observations!=={FaultBits{1'b0}} || (active && owner_held!==1'b1))poison_q<=1'b1;
  end
  assign abort_registered=poison_q || (external_cancel_q!==1'b0);
  // Use this ONLY to create/accept fresh work or fence receiver grants. Never
  // AND it into an already-exposed registered request/data/Done valid signal.
  assign fresh_work_permitted=(rst_n===1'b1) && !poison_q &&
    (external_cancel_q===1'b0) && (fault_observations==={FaultBits{1'b0}}) &&
    (!active || owner_held===1'b1);
endmodule
