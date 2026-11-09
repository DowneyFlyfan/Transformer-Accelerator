# Nonlinear/down shared-fabric owner implementation plan

Goal: alternate paired gate/up nonlinear execution and sparse down contributions on the same qualified twenty-core shared fabric90. Preserve down contexts through successful nonlinear packets; invalidate them on every fatal owner packet, including gate/up configurations rejected before a backend transaction.

Architecture: add a control-only owner with Idle/Gated/Down/Flush/Result states. Reuse unchanged fabric_gated_executor for two full projections and local Q8 SiLU/gate arithmetic. Reuse shared_fabric90 for both projection transactions and down requests. Accept one top packet, select one owner until completion, capture one bounded result packet, and hold it under backpressure. A dedicated registered reset drives both children; a fatal result is captured before two reset cycles. All accepted/advertised memory work has drained at child result boundaries. Successful handoff does not reset either child or its twenty cores. Readiness waits for both children and the registered reset release.

Interface: shared_fabric90 ports plus up-weight base and separate gate/up shifts. Mode0 now returns nonlinear160-lane results; mode1 retains at most32 selected IDs/codes broadcast to at most160 output rows. Projection requests use the gated controller's captured fields; direct down acceptance goes to the backend on the same handshake. No additional arithmetic core, compiled memory or full hidden-tensor cache.

Files: verilog/tri_oracle_gated_down_fabric.sv; verilog/tri_oracle_gated_down_fabric_tb.sv; syn/run_tri_oracle_gated_down_fabric_validation.py. Original37 physical-flow sources, core44 and models68 remain unchanged.

- [ ] Write independent actual-memory interleaving tests before production code: retain thirteen contexts covering2048 output rows; feed bounded nonlinear output packets through down gathers and compare all returned scalar sums; verify stalls, captured fields, range errors, invalid up configuration, up-phase memory faults, global invalidation/recovery and external reset.
- [ ] Observe the native missing-production-module failure.
- [ ] Implement the owner using existing arithmetic and shared backend; run focused/full cases and deliberately wrong dot/down references. Retain original600 real memory models and exactly20 core instances.
- [ ] Run unchanged prediction/nonlinear sixty-case regression through the new owner using only recorded adapter/observer changes; review actual evidence.
- [ ] Build the production full-frame scheduler to iterate all selected subgroups and thirteen output rounds without an external hidden-tensor cache; then integrate the remaining paper blocks and synthesize/route the complete processor. This final task remains outside the owner-only proof.

The testbench may act as the producer and scalar oracle. Its output-round loop does not establish that a production scheduler exists. Local quantization/SiLU settings remain explicit implementation choices; original paper accuracy/energy/performance are unproven.
