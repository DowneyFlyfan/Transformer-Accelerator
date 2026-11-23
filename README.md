# Tri-Oracle accelerator reproduction

SystemVerilog reproduction of the [Tri-Oracle vision-language accelerator](https://doi.org/10.1109/ISSCC49663.2026.11408987) for Taiwan Semiconductor Manufacturing Company (TSMC) 28HPC+.

Xcelium verified two tokens through 32-head attention, trained output projection and residual addition on 20 shared arrays. [Results](records/tri_oracle_fixed_same_token_projection_residual_verified.json)

Inputs are captured projected query, key and value vectors. Complete decoder integration, feed-forward execution in this connected test, model accuracy, mapping and routed timing remain unfinished.

The broader regression has 12 existing lint warnings.

```sh
bash syn/run_tri_oracle_simulation.sh
```

Generated data, libraries and logs stay in `.cache/`.
