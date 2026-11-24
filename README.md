# Tri-Oracle accelerator reproduction

SystemVerilog reproduction of the [Tri-Oracle vision-language accelerator](https://doi.org/10.1109/ISSCC49663.2026.11408987) for Taiwan Semiconductor Manufacturing Company (TSMC) 28HPC+.

An independently reviewed Xcelium run normalized three captured residual tokens, then computed query, key and value projections on 20 shared arrays. It checked 6,144 normalization codes and 120 projected vectors, followed two early token positions through attention, output projection, residual addition and feed-forward execution, and matched all 4,096 final values.

[Normalized-input frame result](records/tri_oracle_native_input_normalization_frame_result.json) · [Testbench](verilog/live_native_input_norm_frame/tb.sv) · [Source bundle](verilog/live_native_input_norm_frame/bundle.sv)

The exported source passed a separate cold elaboration check with the same 623 compiled memories. Include-path changes are checked against the functional source.

The [standalone input normalizer](records/tri_oracle_fused_input_normalization_result.json) separately matched 575,488 activation codes and 281 scales.

[Residual link](records/tri_oracle_residual_replay_link_result.json) · [Shared-memory bridge](records/tri_oracle_live_residual_memory_bridge_result.json) · [Previous projection frame](records/tri_oracle_live_qkv_complete_frame_result.json)

Inputs include captured residuals, trained coefficients, rotary parameters and quantization units. Earlier context operands are supplied; residual storage and writeback use modeled external memory. Head prediction, token merging and longer-context integration remain unfinished, along with complete model hardware, accuracy qualification, current mapping and routed timing. Paper performance is unverified.

Run unit regressions in the existing container:

```sh
docker exec -w "$PWD" tri-oracle-eda bash syn/run_tri_oracle_simulation.sh
```

Generated data, libraries and logs stay in `.cache/`.
