# Tri-Oracle accelerator reproduction

SystemVerilog reproduction of the [Tri-Oracle vision-language accelerator](https://doi.org/10.1109/ISSCC49663.2026.11408987) for Taiwan Semiconductor Manufacturing Company (TSMC) 28HPC+.

A 20-core Xcelium test matched 32 attention heads and 2,048 trained projection outputs using the same arrays. [Verified results](records/tri_oracle_shared_attention_projection_verified.json)

The updated integration still needs mapping, full-model validation, routing, and timing closure.

Run the regression inside the Cadence container.

```sh
bash syn/run_tri_oracle_simulation.sh
```

Generated files go in `.cache/`.
