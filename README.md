# Tri-Oracle accelerator reproduction

SystemVerilog reproduction of the [Tri-Oracle vision-language accelerator](https://doi.org/10.1109/ISSCC49663.2026.11408987) for Taiwan Semiconductor Manufacturing Company (TSMC) 28HPC+.

A 20-core Xcelium test matched 32 attention heads and 2,048 trained projection outputs, including eight-bit conversion, using the same arrays. [Verified results](records/tri_oracle_quantized_shared_projection_verified.json)

The test uses captured query, key and value vectors. Decoder integration, mapping, full-model validation, routing and timing closure remain unfinished.

The broader regression currently stops on 12 existing unused-signal lint warnings.

Run the regression inside the Cadence container.

```sh
bash syn/run_tri_oracle_simulation.sh
```

Generated files go in `.cache/`.
