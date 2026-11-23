# Tri-Oracle accelerator reproduction

SystemVerilog reproduction of the [Tri-Oracle vision-language accelerator](https://doi.org/10.1109/ISSCC49663.2026.11408987) for Taiwan Semiconductor Manufacturing Company (TSMC) 28HPC+.

One Xcelium run verified two early token positions through 32-head attention, output projection, residual addition, feed-forward execution and final residual writeback using 20 shared arrays. All 4,096 final values matched; independent review passed.

[Connected result](records/tri_oracle_continuous_final_writeback_frame.json) · [Attention](records/tri_oracle_fixed_same_token_projection_residual_verified.json) · [Feed-forward](records/tri_oracle_native_attention_bytes_full_feedforward_verified.json)

[Residual read link](records/tri_oracle_residual_replay_link_result.json): 512-row statistics, replay and bypass delivery passed, including fault, stall and abort controls.

Inputs include captured projected query, key and value vectors. Writeback uses modeled external bypass and scale memory. Production bus integration, longer-context execution, full-model hardware, accuracy qualification, current mapping and routed timing remain unfinished. Paper performance is unverified.

The broader regression has 12 existing lint warnings.

```sh
bash syn/run_tri_oracle_simulation.sh
```

Generated data, libraries and logs stay in `.cache/`.
