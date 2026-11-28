# Tri-Oracle accelerator reproduction

SystemVerilog reproduction of [Tri-Oracle](https://doi.org/10.1109/ISSCC49663.2026.11408987), adapting the design to Taiwan Semiconductor Manufacturing Company (TSMC) 28HPC+.

Verified with Cadence Xcelium:

- Projection and attention matched 575,488 context values across 281 queries and 32 heads, including causal token sizes and memory transactions.
- One trained feed-forward row matched prediction, intermediate values, outputs, residual storage and next normalization on 20 arrays, completing 257 write acknowledgments.
- A layer-2 row verified 1,512 predicted skips. Gate and up matrix reads were 8,437,760 bytes each; the calculated, unexecuted all-KEEP reference is 11,534,336 bytes each.
- Shared-normalizer handoff retained the 264-row frame and memory lease. Separate component tests passed 88 protocol controls.
- The [reset-retention variant](verilog/native_persistent_reset/primitive_retention_tb_v1.sv) preserved merge, sign and token-size state across compute resets in 20 arrays. [Compile separately](syn/tri_oracle_persistent_reset_sources.json).
- The [batch adapter](verilog/retained_frame_ff/row_unit_batch_adapter_component_tb_v1.sv) passed 20 component scenarios: 16-token batches, an 8-token tail, stalls and faults. Its memory endpoints are mocked. [Compile separately](syn/tri_oracle_FF_batch_adapter_sources.json).

[Native testbench](verilog/tri_oracle_raw32_residual_commit_tb.sv) · [Protocol controls](verilog/tri_oracle_raw32_residual_protocol_tb.sv) · [Numerical checker](syn/check_tri_oracle_raw32_residual_native.py)

The trained feed-forward tests replay prior normalized data. Continuous hardware integration, task accuracy, current mapping and routed timing remain unfinished. Paper performance is unverified.

Data, memory libraries, build outputs, logs and verification records stay in `.cache/`. Memory models and trained weights must be supplied locally.
