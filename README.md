# Tri-Oracle accelerator reproduction

SystemVerilog reproduction of [Tri-Oracle](https://doi.org/10.1109/ISSCC49663.2026.11408987), targeting Taiwan Semiconductor Manufacturing Company (TSMC) 28HPC+.

Verified with Cadence Xcelium:

- Native normalization checked all 575,488 values for 281 tokens.
- Projection checked 719,360 dot products and 11,240 acknowledged query, key and value vectors.
- Those generated vectors fed head prediction: all 473,760 trained scores matched. The predicted mask then drove attention on the same 20 compute arrays; all 2,048 context values for query 280 matched independent integer arithmetic.
- A separate run restored those native vectors and verified all 575,488 context values across 281 query positions and 32 heads, including causal token sizes and memory transactions.

[Native chain](records/tri_oracle_native_projection_attention_result.json) · [All-query result](records/tri_oracle_all_query_native_attention.json) · [Testbench](verilog/live_native_projection_attention_frame/tb.sv)

A host graphics processor run completed the first trained layer: token merging retained 304 of 616 rows, followed by attention, feed-forward computation, integer residual joins and the next normalization. Independent checks covered every merge decision and head classification, selected projection and attention queries, and their complete feed-forward/residual suffixes. All 82 serialized output files were retained and independently hash-checked.

All 88 trained attention matrices have signed 8-bit exports in 44 bundles. Rotary coefficients and encoder inputs were verified for 616 positions.

The hardware tests model normalized and projected data in external memory. All-layer integration, token generation, task accuracy, current mapping and routed timing remain unfinished. Paper performance is unverified.

Compile exported bundles with `+incdir+<project-root>`. Data, libraries and logs stay in `.cache/`.

Run unit regressions in the existing container:

```sh
docker exec -w "$PWD" cadence-ddi bash syn/run_tri_oracle_simulation.sh
```

All 28 unit simulations passed. The full regression currently exits at 12 unused-port lint warnings in the unchanged default compute fabric.
