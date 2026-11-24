# Tri-Oracle accelerator reproduction

SystemVerilog reproduction of the [Tri-Oracle vision-language accelerator](https://doi.org/10.1109/ISSCC49663.2026.11408987) for Taiwan Semiconductor Manufacturing Company (TSMC) 28HPC+.

An independently reviewed Xcelium run computed query, key and value projections from supplied normalized activations and trained weights on 20 shared arrays. It verified 120 projected vectors, then two early token positions through 32-head attention, output projection, residual addition, feed-forward execution and final writeback. All 4,096 final values matched.

[Live projection result](records/tri_oracle_live_qkv_complete_frame_result.json) · [Complete testbench](verilog/live_qkv_frame/tb.sv) · [Source bundle](verilog/live_qkv_frame/bundle.sv)

The [input normalization component](records/tri_oracle_fused_input_normalization_result.json) separately matched 575,488 activation codes and 281 scales. Its hardware derives scales from residuals and trained coefficients.

[Connected result](records/tri_oracle_continuous_final_writeback_frame.json) · [Attention](records/tri_oracle_fixed_same_token_projection_residual_verified.json) · [Feed-forward](records/tri_oracle_native_attention_bytes_full_feedforward_verified.json)

[Residual read link](records/tri_oracle_residual_replay_link_result.json): 512-row statistics, replay and bypass delivery passed, including fault, stall and abort controls.

[Shared-memory bridge](records/tri_oracle_live_residual_memory_bridge_result.json): 512 live producer rows passed acknowledged write/readback, scalar contention and failed-capture release tests.

Inputs include normalized activation codes, rotary parameters and quantization units. Residual storage and writeback use modeled external memory. Full integration of input normalization, head prediction and token merging remains unfinished, along with longer contexts, complete model hardware, accuracy qualification, current mapping and routed timing. Paper performance is unverified.

The broader regression has 12 existing lint warnings.

```sh
bash syn/run_tri_oracle_simulation.sh
```

Generated data, libraries and logs stay in `.cache/`.
