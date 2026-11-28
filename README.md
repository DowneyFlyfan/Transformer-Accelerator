# Tri-Oracle accelerator reproduction

SystemVerilog reproduction of [Tri-Oracle](https://doi.org/10.1109/ISSCC49663.2026.11408987), adapting the design to Taiwan Semiconductor Manufacturing Company (TSMC) 28HPC+.

Verified with Cadence Xcelium:

- Projection and attention checked all 575,488 context values across 281 queries and 32 heads, including causal token sizes and memory transactions.
- One trained feed-forward row completed through residual storage and the next normalization stage on 20 compute arrays. All 176 prediction groups, 5,632 intermediate values, 2,048 outputs, 2,048 residual values and 2,048 normalized codes matched independent references. All 257 storage acknowledgments completed while the parent retained its 264-row frame.
- All 88 separate protocol controls passed, including producer completion before consumer drain.

[Native testbench](verilog/tri_oracle_raw32_residual_commit_tb.sv) · [Protocol controls](verilog/tri_oracle_raw32_residual_protocol_tb.sv) · [Numerical checker](syn/check_tri_oracle_raw32_residual_native.py)

A host graphics-processor run completed one 22-layer integer-state prefill, retaining 278 of 616 rows. Independent checks covered cumulative merge maps, 704 head classifications and 66 sampled arithmetic chains. That state generated “Yes” and end-of-sequence through one verified decode pass, matching one reference answer. The merge threshold and tie-breaking policy are local choices.

The hardware tests replay prior normalized data. Continuous hardware integration, longer decoding, task accuracy, current mapping and routed timing remain unfinished. Paper performance is unverified.

Data, memory libraries, build outputs, logs and verification records stay in `.cache/`. Memory models and trained weights must be supplied locally.
