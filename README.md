# Tri-Oracle accelerator reproduction

SystemVerilog reproduction of the [Tri-Oracle vision-language accelerator](https://doi.org/10.1109/ISSCC49663.2026.11408987) for Taiwan Semiconductor Manufacturing Company (TSMC) 28HPC+.

The placed 20-core design matched four attention rows and 32,768 trained feed-forward outputs in Xcelium. Routing, timing closure, and full-model validation are pending. [Verified results](records/tri_oracle_placed_replay_result.json)

Run the regression inside the Cadence container.

```sh
bash syn/run_tri_oracle_simulation.sh
```

Generated files go in `.cache/`.
