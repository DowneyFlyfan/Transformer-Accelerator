# Tri-Oracle accelerator reproduction

Independent SystemVerilog implementation of [Tri-Oracle](https://doi.org/10.1109/ISSCC49663.2026.11408987), a vision-language accelerator that reduces work through runtime token merging, attention-head prediction, and feed-forward weight skipping. This implementation targets Taiwan Semiconductor Manufacturing Company (TSMC) 28HPC+ at 28 nanometers. The decoder layer uses five clusters of four compute cores.

## Verified results

- The [mapped compact layer](records/wac_compact_tensor_mapped_attention_result.json) passed four bit-exact attention rows in Cadence Xcelium with 623 compiled static random-access memory macros.
- The compact netlist also [matched 32,768 trained feed-forward outputs](records/wac_compact_tensor_trained_replay_result.json) and the archived cycle log across 71 mask packets and 13 output tiles.
- The [shared memory interface](records/wac_shared_memory_layer_boundary_result.json) reduced external signal bits from 14,343 to 13,299. The replay used mapped interface logic with the SystemVerilog layer.

Whole-chip routing, timing closure at 580 megahertz, model accuracy, and energy validation remain open.

## Run the source regression

From the repository root inside the configured Cadence container:

```sh
bash syn/run_tri_oracle_simulation.sh
```

The regression uses Xcelium and Verilator. Synthesis and physical implementation use Cadence Genus and Innovus with local TSMC libraries. SystemVerilog lives in [verilog](verilog/), implementation scripts in [syn](syn/), and evidence in [records](records/). Generated outputs live in `.cache/`.
