# Tri-Oracle accelerator reproduction

SystemVerilog reproduction of [Tri-Oracle](https://doi.org/10.1109/ISSCC49663.2026.11408987), adapting the design to Taiwan Semiconductor Manufacturing Company (TSMC) 28HPC+.

Verified with Cadence Xcelium:

- Projection and attention checked all 575,488 context values across 281 queries and 32 heads, including causal token sizes and memory transactions.
- One trained feed-forward row completed through residual storage and the next normalization stage on 20 compute arrays. All 176 prediction groups, 5,632 intermediate values, 2,048 outputs, 2,048 residual values and 2,048 normalized codes matched independent references. All 257 storage acknowledgments completed while the parent retained its 264-row frame.
- All 88 separate protocol controls passed, including producer completion before consumer drain.
- A layer-2 row verified 1,512 predicted skips. Observed gate and up matrix weight reads were 8,437,760 bytes each; the calculated, unexecuted all-KEEP reference is 11,534,336 bytes each.
- Shared-normalizer handoff preserved the 264-row frame and physical memory lease. Controls passed for early requests, released ownership and an unknown lease signal.
- The [reset-retention variant](verilog/native_persistent_reset/primitive_retention_tb_v1.sv) preserved merge/sign/token-size state across compute resets in 20 arrays; epoch reset invalidated it. [Compile separately](syn/tri_oracle_persistent_reset_sources.json).

[Native testbench](verilog/tri_oracle_raw32_residual_commit_tb.sv) · [Protocol controls](verilog/tri_oracle_raw32_residual_protocol_tb.sv) · [Numerical checker](syn/check_tri_oracle_raw32_residual_native.py)

[Handoff controls](verilog/tri_oracle_post_next_c_protocol_tb.sv) compile separately, with top `tri_oracle_normalized_image_compactor_tb` and the [memory witness](verilog/tri_oracle_post_next_c_memory_witness_tb.sv).

A host graphics-processor run completed one 22-layer integer-state prefill, retaining 278 of 616 rows. Independent checks covered cumulative merge maps, 704 head classifications and 66 sampled arithmetic chains. That state generated “Yes” and end-of-sequence through one verified decode pass, matching one reference answer. The merge threshold and tie-breaking policy are local choices.

The trained feed-forward tests replay prior normalized data. Continuous hardware integration, longer decoding, task accuracy, current mapping and routed timing remain unfinished. Paper performance is unverified.

Data, memory libraries, build outputs, logs and verification records stay in `.cache/`. Memory models and trained weights must be supplied locally.
