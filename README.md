# Tri-Oracle accelerator reproduction

SystemVerilog reproduction of the [Tri-Oracle vision-language accelerator](https://doi.org/10.1109/ISSCC49663.2026.11408987) for Taiwan Semiconductor Manufacturing Company (TSMC) 28HPC+.

Xcelium verified two trained tokens through 32-head attention, output projection and residual addition using 20 shared arrays. A separate feed-forward run matched all 4,096 raw Down outputs. A connected prefix and corruption control also passed.

[Attention](records/tri_oracle_fixed_same_token_projection_residual_verified.json) · [Feed-forward](records/tri_oracle_native_attention_bytes_full_feedforward_verified.json) · [Connected prefix](records/tri_oracle_connected_attention_feedforward_prefix_verified.json)

Inputs include captured projected query, key and value vectors. Full connected execution, final writeback integration, full-model hardware, accuracy qualification, current mapping and routed timing remain unfinished. Paper performance is unverified.

The broader regression has 12 existing lint warnings.

```sh
bash syn/run_tri_oracle_simulation.sh
```

Generated data, libraries and logs stay in `.cache/`.
