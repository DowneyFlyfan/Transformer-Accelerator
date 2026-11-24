# Tri-Oracle accelerator reproduction

SystemVerilog reproduction of [Tri-Oracle](https://doi.org/10.1109/ISSCC49663.2026.11408987), targeting Taiwan Semiconductor Manufacturing Company (TSMC) 28HPC+.

Verified with Cadence Xcelium:

- A captured input frame used 20 shared arrays, checked 6,144 normalization codes and 120 projected vectors, and matched 4,096 final values across two token positions.
- Standalone head prediction checked 32 heads across 185 queries each, matched all 473,760 trained scores and selected 21 streaming heads. Its source export passed cold compilation with 621 memory blocks.

[Normalized frame result](records/tri_oracle_native_input_normalization_frame_result.json) · [Head prediction result](records/tri_oracle_native_head_prediction_result.json) · [Head testbench](verilog/live_head_prediction_frame/tb.sv)

The head test consumes captured, signed eight-bit query/key vectors. Earlier context operands are supplied, and external memory is modeled. Complete model and token merging integration, longer context execution, task accuracy, current mapping and routed timing remain unfinished. Paper performance is unverified.

Compile exported bundles with `+incdir+<project-root>`.

Run unit regressions in the existing container:

```sh
docker exec -w "$PWD" tri-oracle-eda bash syn/run_tri_oracle_simulation.sh
```

Generated data, libraries and logs stay in `.cache/`.
