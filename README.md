# Tri-Oracle accelerator reproduction

SystemVerilog reproduction of the [Tri-Oracle vision-language accelerator](https://doi.org/10.1109/ISSCC49663.2026.11408987) for Taiwan Semiconductor Manufacturing Company (TSMC) 28HPC+.

Xcelium verified two tokens through 32-head attention, trained output projection and residual addition on 20 shared arrays. A separate feed-forward run consumed those native output bytes and matched all 4,096 raw Down outputs. [Attention results](records/tri_oracle_fixed_same_token_projection_residual_verified.json) · [Feed-forward results](records/tri_oracle_native_attention_bytes_full_feedforward_verified.json)

Inputs include captured projected query, key and value vectors. Continuous decoder integration, full-model hardware execution, accuracy qualification, current mapping and routed timing remain unfinished. Paper performance is unverified.

The broader regression has 12 existing lint warnings.

```sh
bash syn/run_tri_oracle_simulation.sh
```

Generated data, libraries and logs stay in `.cache/`.
