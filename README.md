# Tri-Oracle accelerator reproduction

SystemVerilog reproduction of [Tri-Oracle](https://doi.org/10.1109/ISSCC49663.2026.11408987), targeting Taiwan Semiconductor Manufacturing Company (TSMC) 28HPC+.

Verified with Cadence Xcelium:

- Native normalization checked all 575,488 values for 281 tokens.
- Projection checked 719,360 dot products and 11,240 acknowledged query, key and value vectors.
- Those generated vectors fed head prediction: all 473,760 trained scores matched. The predicted mask then drove attention on the same 20 compute arrays; all 2,048 context values for query 280 matched independent integer arithmetic.

[Native chain](records/tri_oracle_native_projection_attention_result.json) · [Testbench](verilog/live_native_projection_attention_frame/tb.sv) · [Earlier connected result](records/tri_oracle_live_predicted_attention_result.json)

The test models normalized and projected data in external memory. Complete model and token merging integration, all-query attention verification, task accuracy, current mapping and routed timing remain unfinished. Paper performance is unverified.

Compile exported bundles with `+incdir+<project-root>`. Data, libraries and logs stay in `.cache/`.

Run unit regressions in the existing container:

```sh
docker exec -w "$PWD" tri-oracle-eda bash syn/run_tri_oracle_simulation.sh
```

All 28 unit simulations passed. The full regression currently exits at 12 unused-port lint warnings in the unchanged default compute fabric.
