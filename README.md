# Tri-Oracle accelerator reproduction

SystemVerilog reproduction of [Tri-Oracle](https://doi.org/10.1109/ISSCC49663.2026.11408987), targeting Taiwan Semiconductor Manufacturing Company (TSMC) 28HPC+.

Verified with Cadence Xcelium:

- A captured normalized frame checked 6,144 normalization codes, 120 projected vectors and 4,096 final values across two early token positions.
- Head prediction checked 32 heads across 185 queries each and matched all 473,760 trained scores.
- The actual predicted mask then drove attention on the same 20 compute arrays. All 2,048 context values for query 280 matched independent scalar arithmetic; the exported source passed cold compilation with 621 memory blocks.

[Connected result](records/tri_oracle_live_predicted_attention_result.json) · [Testbench](verilog/live_predicted_attention_frame/tb.sv) · [Normalized frame](records/tri_oracle_native_input_normalization_frame_result.json)

The connected test consumes captured signed eight-bit query/key/value vectors and models external memory. Complete model and token merging integration, complete native projection, task accuracy, current mapping and routed timing remain unfinished. Paper performance is unverified.

Compile exported bundles with `+incdir+<project-root>`. Data, libraries and logs stay in `.cache/`.

Run unit regressions in the existing container:

```sh
docker exec -w "$PWD" tri-oracle-eda bash syn/run_tri_oracle_simulation.sh
```

All 28 unit simulations passed. The full regression currently exits at 12 unused-port lint warnings in the unchanged default compute fabric.
