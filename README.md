# Tri-Oracle reproduction in progress

Current verified milestone: one shared backend executes projection, gate/up
nonlinearity and sparse down accumulation using exactly twenty compute cores
and 600 compiled static random-access memory (SRAM) instances. The joint
70-case test checks 463 exact raw dot products, 230 bounded nonlinear codes
and 2,048 returned hidden-output sums. The separate canonical prediction test
checks 60 cases and 16,092 exact projection sums through the same owner.
Deliberately wrong references are rejected. See
`records/gated_down93_functional_qualification.json` and
`records/owned_gated94_functional_qualification.json`.

`tri_oracle_feedforward_frame.sv` moves packet subgroup and output-round
scheduling into production hardware. Its actual twenty-core, 600-memory
integration passes 18 cases in 352 seconds: 655 exact raw dot products, 326
bounded nonlinear codes, and 5,220 checked output lanes. Of those lanes, 5,060
belong to successful frames; 160 form a prefix canceled by a deliberate late
memory failure. The full 2,048-output, 5,632-channel frame uses two selected
packets and 91 internally scheduled down calls. Empty finalizers, all fifteen
accumulation slots, partial outputs, sustained stalls, memory faults and reset
recovery pass, and both wrong-reference controls are rejected. See
`records/frame95_actual_functional_qualification.json`.

`tri_oracle_prediction_packet_stream.sv` extracts the prediction/framing/batching
control without a compute fabric or memory. Its nine-case native test checks
the full 5,632-channel/2,048-feature prediction shape, full and partial packets,
stalls, reset, and malformed input after an accepted 160-identifier prefix.
The wrong-identifier reference is rejected. See
`records/prediction100_functional_qualification.json`.

`tri_oracle_predicted_feedforward_frame.sv` joins that stream to the numeric
controller with exactly one shared backend. Its twelve actual-memory cases pass
in588 seconds, checking4,420 final hidden-output lanes. The full5632-channel,
2048-input-feature,2048-output fixture retains196 channels. Coverage includes
configuration rejection by either child, a prediction fault during committed
numeric memory work, memory faults and reset recovery. This test uses prepared
normalized/sign inputs and analytically saturated numeric operands; raw frontend
integration and model accuracy remain pending. See
`records/predicted101_functional_qualification.json`.

The separately named `tri_oracle_sparse_weight_dma_pipelined.sv` addresses the
long selector/multiply/add/overflow path without changing the original source.
Eighteen source cases and seven address-stage reset cases pass. Isolated mapping
at the slow0.9-volt125-degree-Celsius corner reports577 picoseconds of setup
margin at a1.72414-nanosecond period, with2047 cells and4503.912 square
micrometers of library cell area. This does not establish full-parent or routed
timing closure, and this candidate is not yet part of the joined controller.

The routed single-core checkpoint has independent timing and geometry evidence.
The twenty-core prediction parent has legal placement, but whole-chip routed
timing is not closed. Current parent optimization uses compact core models only
for guidance and requires restoration of the original complete core models for
timing diagnostics. The repaired candidate preserves all 1,889,420 original
core cells, all 981 registered-reset ancestor trees, and all sixty macro poses
against the accepted placement inventory. Separate full-model diagnostics still
fail: slow setup -13.394268 ns, typical setup -10.458878 ns, fast hold
-0.058541 ns. The worst setup path traverses the weight-address generator.
These are pre-clock, pre-route diagnostics with signal-interference analysis
disabled by the native engine. See
`records/recovered104_physical_diagnostic_qualification.json`.

This is an independently implemented reproduction, not the authors' design.
The available Taiwan Semiconductor Manufacturing Company (TSMC) 28-nanometer
library differs from the paper's Samsung process. Full model accuracy, chip
energy, complete-chip routing and the paper's measured results remain unverified.
The historical development notes below describe earlier stages and local
implementation choices.

Source and small evidence records are versioned. Libraries, process design kits,
papers, model weights, simulator builds and physical databases remain local and
are excluded from Git. Native Cadence runs require the locally configured
container and library views; the repository does not distribute those dependencies.

This folder contains scaled SystemVerilog models of the three prediction
mechanisms described in Tri-Oracle (2026 IEEE International Solid-State
Circuits Conference, Digital Object Identifier
10.1109/ISSCC49663.2026.11408987): token merging, attention-head type
prediction, and small-near-zero-value prediction. A proportional-softmax
normalizer demonstrates the token-size correction. These modules are not the
authors' register-transfer-level design or a full vision-language accelerator.

The full 32-line by 8-lane signed eight-bit compute-array basis is in
`verilog/tri_oracle_pe_array.sv`. Its product stage and three reduction stages
accept one transaction per cycle when outputs are consumed. The pipeline and
full-precision 19-bit sums are local choices. The memory and compute hierarchy
below is implemented; the paper's dual-mode output reduction remains absent.

`verilog/tri_oracle_memory_compute.sv` connects the compute array to the core
memory capacities in Figure 31.6.2: 8 kilobytes each of weight and input
storage, 2 kilobytes of output storage, and 1 kilobyte of auxiliary storage.
The inferred banks and command/load ports are local implementation choices.
Its test covers source loading, continuous issue, output readback, and
consecutive accumulation into one destination. Foundry memory-macro mapping, full-chip prediction integration and
instruction-driven execution remain unfinished.

`tri_oracle_compute_cluster.sv` and `tri_oracle_compute_fabric.sv` instantiate
four memory/compute cores per cluster and five clusters. Each cluster has an
inferred 2-kilobyte aggregation bank, ordered output, and destination
reservation. The routing, queue protocol, and signed sum/maximum/mean
arithmetic are local choices. The full hierarchy test loads all 20 cores and
checks aggregate values, output stalls, queue wraparound, and selected-cluster
issue. The twenty-core fabric does not yet connect the prediction controllers;
it is not an integrated model-execution processor.

The paper does not disclose all thresholds, tie rules, timing, or memory
interfaces. Parameters and local choices in the modules state those gaps.
No chip energy, frequency, area, or model-accuracy claim follows from these
functional tests.

`verilog/tri_oracle_strip_predictor.sv` extends the sign-magnitude estimator
to full vectors by accumulating counts across eight-feature strips for 32
outputs. It accepts one strip per cycle, supports up to 4,096 features,
intersects the final gate/up masks, and reports overlong frames while skipping
no work. Its 16-bit normalization format with eight fractional bits, framing
and maximum length are explicit local choices. Tests cover literal full-vector
results, signed extrema, threshold boundaries, stalled outputs, reset and
counter capacity. This unit now feeds the dispatch stage below; complete kernel
scheduling and model-level validation remain open.

`tri_oracle_rmsnorm.sv` and `tri_oracle_rms_predictor.sv` now normalize signed
residual codes before the learned scale and feed one 32-output prediction group.
The two-pass normalizer supports up to 4,096 features and exactly rounds the
represented root-mean-square quotient into signed16 codes with eight fractional
bits. Terminal framing/energy errors reject the whole prediction mask. The original86-test
source qualification passed, including native Icarus tests and reset mutation controls.
Precision, epsilon representation and the replay protocol are local choices.
This frontend is not connected to the routed feed-forward top; sign fetching,
learned-scale arithmetic, reuse across output groups and its physical implementation
remain open. Evidence: `records/rms_prediction_frontend_validation.json`.

`tri_oracle_sign_fetch.sv` and `tri_oracle_rms_sign_predictor.sv` now replace
software sign delivery for that frontend with packed-sign memory requests.
Only feature pairs containing outliers are read. Committed faulty responses drain
before error publication; a sticky frame error suppresses later reads and rejects
all skip masks. All88 current Python tests and strict Verilator lint pass; native
wrong-plane/error-state mutations are rejected. Four archived checkpoint cases
pass raw-residual-to-mask simulation, preserving the original outlier positions
and skip decisions, including22 skipped channels out of64 in the coverage token.
Measured sign reads are32 or144 bytes per32-output group for those two tokens.
The packed layout is local, and these are traffic measurements, not chip energy.
Normalization reuse, learned-scale coefficient fetching, activation-memory integration
and physical implementation of the connected frontend remain unfinished. The580MHz/20-processor synthesis entry
is prepared but has not run. See `records/sign_frontend_validation.json` and
`records/rms_sign_model_validation.json`.

`tri_oracle_normalized_feedforward_core.sv` now connects raw-residual prediction,
packed sign reads and the existing gate/up/down execution core on one external
memory port. Tensor/group descriptors remain captured under backpressure. The
arbiter retains a presented request through acceptance and response LAST; faulted
tensors drain internally and publish only one terminal error. The20-case native
suite, all89 Python tests and strict lint pass. A review-found stalled-request
preemption bug was reproduced and fixed; native mutations verify the request lock
and its preservation through a frontend fault. The unchanged compute source and
current routed regression inputs remain intact.
Two real checkpoint slices also pass the connected path against all70 archived
output sums; original software-driven prediction mode was rechecked too. The
pruning case retains22/64 skipped channels and reads86,016 bytes per gate/up
matrix plus64 packed-sign bytes over two groups. Compute activation memory still
contains software learned-scale/quantized inputs; cross-group reuse, full20-core
integration, memory macros and physical implementation of this top remain open.
Its20-worker580MHz imported-core synthesis entry is prepared but not executed.
See `records/normalized_feedforward_validation.json`.

`tri_oracle_affine_quantizer.sv` and `tri_oracle_rms_activation.sv` now generate
learned-scale signed8 activation words from the existing normalization stream.
The eight signed16 products round ties away and saturate; two elastic stages
sustain one accepted/output word per cycle. Coefficients are captured with replay,
while prediction metadata stays before learned scaling. All91 Python tests and
strict lint pass, including full-chain stalled drain, reset and three native
negative controls. Independent review found two coverage gaps, both now fixed.
Native hardware matches independent arithmetic for4,096 real activation codes.
Thirteen codes differ by one from the archived floating-normalization path;
prediction outlier positions are unchanged. This source stream is not yet joined
to activation-cache commit/discard, coefficient memory fetching or compute-port
serving; the connected compute top above still receives precomputed activation
memory. Those integrations and physical/paper qualification remain required.
See `records/rms_activation_validation.json`.

`tri_oracle_cached_feedforward_core.sv` now generates activations once per token,
commits them only after terminal success and serves compute activation bursts
from a local5-kibibyte inferred cache. Compact outlier/sign proxies are reused for
every selected output group, preserving the predictor's exact threshold/sign
inputs. The extracted `tri_oracle_prediction_feedforward_core.sv` retains the
existing execution/arbitration protocol; the earlier normalized top remains a
compatible wrapper. All93 Python tests,24 cached integration cases,20 preserved
normalized cases and strict lint pass. Four real native mutations are rejected.
Two real checkpoint cached runs match70 independent final sums with zero external
activation bytes. The scalar reference first reproduces70 archived baseline sums.
The new raw/learned-scale quantization changes13 activation codes by one, so67 of
the new output accumulators differ from the archived float-input version; hardware
matches the represented integer arithmetic, not the paper's accuracy/energy.
Coefficient loading still uses the replay stream, memory is inferred, and full
processor/physical qualification remains open. The20-worker580MHz cached synthesis
completed on its second bounded attempt:571190 cells and1.045726square millimeters
of library cell area. The slow-corner report shows MET with0picoseconds displayed,
which establishes no positive rounded margin or routed timing closure. The first
attempt stopped at its memory guard. Physical stage scripts
are prepared, with wrong-design checkpoint rejection verified before hierarchy
release; initialization, placement and routing of this cached top have not run.
See `records/cached_synthesis_attempt.json`,
`records/cached_physical_flow_preparation.json`,
`records/activation_cache_integration_validation.json` and
`records/cached_feedforward_architecture.pdf`.

`tri_oracle_activation_loader.sv` adds a standalone memory reader for raw
statistics and raw/learned-coefficient replay. It fetches two64-bit beats per
strip, holds stream outputs under stalls and drains failed transactions through
the actual terminal response.20 native cases, two reset recoveries, five rejected
mutations,94 Python tests and strict lint pass. It is not yet connected to the
cached core. Its maximum4096-feature traffic is24576bytes across two raw passes
and one coefficient pass; this is not a paper energy result. See
`records/activation_loader_validation.json`.

`tri_oracle_memory_feedforward_core.sv` joins that reader to the cached compute
path. Raw activations and learned coefficients now arrive through the shared
memory port, with no software statistics/replay stream ports. Preparation errors
discard remaining reader streams and retain memory ownership through actual LAST
before resetting provisional compute context and returning an error.34 native
contexts, four reset recoveries, six rejected mutations,95 source tests and strict
lint pass. Group descriptors remain external. Its import-preserving synthesis
completed with574100 cells and1.050312square millimeters of library cell area.
Innovus initialization passed; placement is running under a separate memory guard.
Real-checkpoint validation of this interface, routed closure and paper matching
remain required. See `records/memory_feedforward_validation.json`,
`records/memory_feedforward_synthesis_result.json` and
`records/memory_physical_initialization_result.json`.

`tri_oracle_channel_compactor.sv` packs surviving output channels from multiple
32-channel prediction groups into 32-row compute batches, retaining original
channel identifiers. Its bounded two-bank queue emits weight-fetch identifiers
and the compute lane mask. `tri_oracle_predicted_dispatch.sv` connects the
streaming predictor to this queue and preserves each group's first-strip tags.
An empty terminal batch requests no weights or computation; prediction errors
retain every affected channel. These interfaces and queue details are local
implementation choices. Tests verify that two half-dense groups form one full
batch and use its actual identifiers and mask to fetch 32 rows and check sums
through the memory-backed core. That test models the external transfer driver;
system-bus adaptation and the complete kernel controller remain unfinished.

`tri_oracle_predicted_core.sv` now connects the streaming prediction/packing
path to the tile executor and a real full-capacity memory/compute core.
A configuration handshake holds tensor tag, operand bases and feature range
until the terminal result is consumed. Group identity and tensor-last come
from the first strip. Early/late vector endings force dense fallback for the
affected group. A transport error stays visible through tensor completion;
later descriptors drain without operand transfers. Configuration and new-tensor
inputs stay blocked while a previous terminal result is pending.
The hardware, rather than the testbench, issues loads, compute commands and
readback. Its deterministic test supplies only external memory responses and
prediction inputs, checks actual skipped-row requests and signed matrix sums,
and covers full 4096-feature vectors, channel 65535, partial ranges, stalls,
malformed frames, faults, recovery and reset. Normalization/sign-bit fetching
remain upstream. Default GATED=0 executes one selected weight matrix.
GATED=1 fetches both gate/up matrices, completes both dot products, shifts and
saturates sums into signed 16-bit values with eight fractional bits, and applies
SiLU(gate)*up. The three-stage elastic nonlinear unit uses an interpolated
257-point lookup table; its exhaustive code sweep observed at most one output
code of SiLU error with up=1. These precision choices require model calibration.
Nonlinear mode rejects partial feature sums; activation must follow complete
reduction. The down projection remains absent, so this is not a complete
feed-forward layer. See `records/gated_path_integration.json`. It has passed simulation and strict lint but has not yet
been synthesized or routed as an integrated unit.

`tri_oracle_down_executor.sv` now gathers down-projection weight columns using
the surviving original channel identifiers. It requantizes the gated values
into signed eight-bit inputs, reuses a 64-bit weight word when possible, and
skips transfers for zero inputs. Output slots 1 through 15 preserve sums across
packets; slot 0 remains the gate/up workspace. Tag/range checks protect appends,
empty packets initialize or finalize sums, and failures invalidate the affected
context after draining any committed response.

`tri_oracle_feedforward_core.sv` connects prediction, gate/up execution and down
projection to one shared core and memory port. It accumulates a configured
range of up to 480 output rows locally. Results are released only after all
terminal down tiles succeed. The full 24-case Icarus suite and strict lint pass,
including independent dense sums, all 15 slots, multiple batches, maximum
source features, transport failures in each matrix and reset. The block's
independent physical qualification is described below. Normalization/sign fetching, model calibration,
instruction sequencing, and model-wide multi-core scheduling remain unfinished.
Evidence: `records/feedforward_path_integration.json`.

`tri_oracle_sparse_weight_dma.sv` is a hardware burst-transfer engine for those
packed row identifiers. It fetches contiguous eight-weight beats into either
16-word half of the weight bank. The memory core, cluster and fabric now carry
32 per-row weight-write enables, allowing selected rows to load directly into
the bank. Activation and mask writes use their normal interfaces. The engine
checks shapes, alignment, address overflow and response framing, and drains
failed bursts before reporting an error. Its local ready/valid memory protocol
still needs a system-bus adapter. The tile executor now provides autonomous
activation/weight fetch, tiled command issue, completion draining and readback;
whole-model scheduling remains incomplete.

The burst controller has completed mapped synthesis and placement/routing.
Final extracted reports at the 580-megahertz target show +0.001 ns slow-corner
setup and +0.015 ns fast-corner hold slack. Design-rule, connectivity, antenna
and active-net routing checks pass, and its routed netlist passes the functional
Icarus tests. The narrow setup margin and full-chip qualification remain material
limits. Results are in `records/dma_implementation_result.json`.

The full-capacity core has completed banked synthesis with its unchanged
19-kibibyte capacity: 359,524 cells, 707,028.504 square micrometers of cell
area and +0.207 nanoseconds of pre-route setup slack. Its mapped functional
Icarus test passes without delay annotation. The current routed baseline
contains 689,964 placed cells and 983,098.368 square micrometers of cell area.
Slow/typical setup slack is +0.046663/+0.370667 nanoseconds, but fast hold is
-0.016421 nanoseconds and noisy-slew checks still flag eight nets. Placement,
geometry, connectivity, antenna and active-net routing checks pass. The
original three analysis views and fresh routed exports were verified.
This baseline fails timing/electrical qualification. Its unmodified routed
netlist now passes both functional Icarus tests: 512 independently checked sums
across 40 commands, and selective row writes with disabled-row poison, word
isolation, signed extremes and zero enables. The runs took 62 and 52 seconds,
respectively, with less than eight gibibytes of peak memory. They use the
library-supported TETRAMAX switch with specify timing explicitly disabled.
The switch excludes 6,544,186 timing observers from simulation while preserving every one of
167,109 state primitives and their input logic. Structural checks and 849,930
native output comparisons cover all 206 used cell types, with an incorrect
primitive rejected as a control. These are zero-delay functional results.
See `records/routed_core_functional_mode_gate_attempt.json`,
`records/routed_core_selective_gate_validation.json` and
`records/library_functional_mode_structural_audit.json`.

The integrated feed-forward top has now completed Genus synthesis with the
original full-capacity mapped core preserved: 401,529 cells and 783,666.744
square micrometers of standard-cell area. The controllers add 76,638.240 square
micrometers, approximately 10.84 percent of the core area. The final single
slow-corner setup report displays +1 picosecond at the 580-megahertz target.
The critical path traverses gate/up result selection and requantization into
the nonlinear unit. This narrow pre-placement margin does not establish routed
timing or hold closure. The run completed in 1,506 seconds with approximately
5.71 gibibytes of combined anonymous-memory peak and no out-of-memory event.
Default-activity synthesis power is not a measured workload energy result.
Source snapshots, imported core identity and final artifact checksums were
verified. Its latest independently checked routed checkpoint contains 710,628
placed cells and 982,595.208 square micrometers of cell area. Slow/typical setup
slack is +0.000508/+0.174200 nanoseconds; fast hold is +0.000129 nanoseconds,
with zero negative hold paths. Placement, geometry, antenna, connectivity and
active-net routing checks pass. Independent reload and extraction also report
zero maximum-transition, capacitance and signal-glitch violations. The small
positive timing margins remain explicit; these are block-level checks under
the supplied process views, not foundry signoff or paper-result matching.
The final repair resized four unique data drivers without moving any instance
or changing any other cell type. All 74 protected endpoint delay cells and seven
antenna diodes remain present. All three original timing views and constraints
were retained. The check used all twenty processors and finished in 393 seconds.
Its exported netlist, layout, parasitics and reports have a separate snapshot
with verified checksums. The full processor, foundry static random-access memory
macros and paper-level area, energy and model accuracy remain unfinished.
See `records/feedforward_local_slew_qualification.json`; historical rejected
repairs remain documented in their individual records.

The integrated gate-simulation launchers accept the full feed-forward bench and
require cell-library proofs matching the chosen exported netlist. Its source-level
address checker now validates full-width addresses and burst bounds before
narrowing. A native Icarus mutation reproduced the old high-address alias and
confirmed its rejection after the fix; the unmodified source benchmark passes.
This does not establish integrated routed functionality. The first routed runs
were stopped after exposing a zero-delay clock-tree race: the frame-closed
register sees the new state through its data path before its later clock leaf
arrives in the same simulation timestamp. Its clock has seventeen buffer stages;
the state register's has seven. An observation-only probe reproduces the capture,
and changing that one clock pin in a separate diagnostic netlist restores the
first input handshake. The original synthesis netlist matches the source at all
thirty sampled handshakes through cycle 3,584. No physical database was changed.
A separately hashed functional copy now connects all 180,941 sequential clock
pins to the same verified root-clock event. A hierarchy-aware audit checked
6,887 single-driver scalar clock nets and rejected non-clock fanout, unresolved
clock links and alternate drivers. Every clock buffer, state-cell model and
data/reset/enable connection remains intact; independent comparison confirmed
that only clock-pin arguments and a binary-clock assertion changed. The full
84-test Python suite and fresh native cell-model comparisons pass. This is an
ideal-clock functional method; extracted physical timing still uses the original
routed database. The complete211,914-cycle regression is running. Nine of twelve source-defined
cases now pass, including normal, empty and transport-failure paths. A read-only
live observation matches1,003 sampled progress/handshake lines against the source;
three cases remain. See `records/feedforward_ideal_clock_gate_live_observation.json`. It has no complete regression pass
claim yet. Added logging preserves all twelve source-case results and their
exact cycle counts. See `records/feedforward_ideal_clock_gate_attempt.json`,
`records/feedforward_routed_prefix_divergence.json` and
`records/feedforward_routed_gate_preparation.json`. The earlier runtime estimate
does not establish a completion time for this unresolved verification step.

The tile executor has completed synthesis, placement, clock-tree synthesis
and routing. Its final580-megahertz checks show+0.009 ns slow setup and
+0.019 ns fast hold slack, with no reported design-rule/connectivity/antenna
violations or active nets missing routing. A local via-spacing violation was
repaired and rechecked. Routed functional Icarus simulation passed without
delay annotation; compute storage/arithmetic in that test uses source code.
Evidence and qualifications: `records/executor_implementation_result.json`.

The full processor's frequency/voltage, energy and model targets are recorded
in `records/paper_result_targets.json`. Full-chip results remain unmatched.
The original monolithic synthesis attempt is archived separately; it does not
qualify the current banked implementation.

The compute array has also completed Genus synthesis and Innovus placement,
clock-tree synthesis and routing with the supplied TSMC 28-nanometer libraries.
At the 580-megahertz target, final extracted timing reports show +0.227 ns
setup slack and +0.018 ns hold slack. Design-rule, connectivity and antenna
checks report zero violations. These checks cover the array only, with the
locally documented timing budgets and available process models. They do not
establish whole-chip performance or equivalence to the paper's Samsung process.
Reports and checkpoints are under `.cache/physical/pnr/tri_oracle_pe_array/`;
the persistent evidence record is `records/pe_array_synthesis_result.json`.

Run each test in the project Docker container with Icarus Verilog:

The complete regression, including strict Verilator lint and the compute
array's continuous-throughput check, is `bash syn/run_tri_oracle_simulation.sh`.

```sh
mkdir -p .cache
for unit in token_merger head_predictor snzv_predictor proportional_normalizer; do
  iverilog -g2012 -s tri_oracle_${unit}_tb -o .cache/tri_oracle_${unit}.vvp \
    verilog/tri_oracle_${unit}.sv verilog/tri_oracle_${unit}_tb.sv
  vvp .cache/tri_oracle_${unit}.vvp
  rm -f .cache/tri_oracle_${unit}.vvp
done
iverilog -g2012 -s tri_oracle_token_merger_random_tb \
  -o .cache/tri_oracle_token_merger_random.vvp \
  verilog/tri_oracle_token_merger.sv \
  verilog/tri_oracle_token_merger_random_tb.sv
vvp .cache/tri_oracle_token_merger_random.vvp
rm -f .cache/tri_oracle_token_merger_random.vvp
```

`try/` and the older generic modules in `verilog/` originate from a separate
65 nm floating-point attention experiment. Its old generated outputs were
removed. The `syn/tri_oracle*` scripts are the current implementation flow;
current generated outputs are kept in `.cache/physical/`.

# Targets

- [] Reproduce this paper until synthesize, placement and rounting are all finished and match the results of the paper. Take all (CPU cores - 2) and use GPU for these if it can accelerate. If estimated sythesize time / placement and routing time is longer than 1 day, report to me first.

2026-11-05 model-derived check: the pinned TinyLLaVA-v1 public reference weights (5,640,534,128 bytes) downloaded with the Hugging Face CLI and passed both SHA-256 checks. A real first-language-layer causal-attention/post-normalization activation drives a smaller feed-forward slice:2048 inputs,64 original channels from groups52/175,5632-byte down row stride and35 output rows2013..2047. Icarus matches all35 independent integer sums. The unchanged24-case regression and strict lint pass. Corrected checker case comparisons reject unknown fallback metadata; an original-ID corruption is also rejected. A compensated seven-bit linear up gain reduces the small floating-slice relative L2 error from93.16 to11.69 percent. These are local uncalibrated formats; this case predicts zero skipped channels and is not a full-model accuracy result. Exact paper checkpoint/preprocessing remain unverified. See records/model_reference_validation.json and model_reference_architecture.pdf.

The resident-operand20-core fabric now passes a sustained-rate Icarus check:256 consecutive all-cluster commands,one issue per cycle and one result per cycle per cluster after8-cycle fill. All40960 aggregate values match independent integer references while the16 destination slots wrap16times. A forced-ready stall is rejected; independent review found no actionable issue. This supports10240 nominal arithmetic operations per cycle,conditionally5.9392TOPS if580MHz is physically achieved; it does not establish full-fabric routed frequency, external-memory/model throughput or paper PPA. Evidence: records/fabric_stream_validation.json.

Paper-method correction: Fig31.6.5 uses pre-learned-scale root-mean-square normalization, a one-sided gate estimate, an up interval and AND. Both predictors now implement that branch structure, with explicitly local zero/inclusive gate and symmetric up thresholds. Current25-case Icarus regression and strict lint pass, including a legacy threshold-width fix and8/32-bit tests. Two real-checkpoint slices match35 sums each. The pruning-coverage token skips22/64 rows, including5 requiring negative-gate suppression; each gate/up matrix fetches86016 instead of131072 bytes. This34.375 percent weight-data reduction excludes sign fetching and is not a dataset accuracy/energy result. Prior local z-score reference remains archived. New predictor logic has no physical qualification yet. See records/paper_predictor_alignment.json and the two model_reference validation records.

The pruning-coverage case has a material numerical limitation: its selected35
floating output values have8.26 percent relative Euclidean-norm error with the
unpruned integer computation and51.73 percent error with pruning, using identical
scales. All22 removed activations are nonzero after quantization. The default
last-token case skips nothing and has11.69 percent error. These comparisons
isolate local quantization and pruning effects; they neither measure whole-model
accuracy nor validate the paper's undisclosed prediction thresholds. Matching
integer hardware outputs therefore does not establish model-quality matching.
Evidence: `records/model_reference_error_decomposition.json`.

Complete first-layer feed-forward verification passed with2048 input
features, all5632 intermediate channels and all2048 output rows from the pinned
checkpoint. A software testbench schedules five output ranges of480/480/480/480/128
rows through the existing hardware. Independent streaming scalar arithmetic
reproduces all2048 expected sums. Icarus matched all2048 outputs in65774488 cycles
and70 minutes37 seconds, with no predicted channel skips for this token.
Review identified an address-check narrowing hole in the new testbench;
an actual invalid-address probe passes the old checker and is rejected by the
corrected64-bit bounds check. Both earlier64-channel cases were regenerated
unchanged and passed again. Scope, hashes and live status are in
`records/full_layer_validation.json`. This covers one token's feed-forward
tensor, with software normalization/sign delivery and output-range scheduling;
whole-model accuracy, autonomous full-model execution and physical qualification
remain separate requirements.

Two bounded numerical audits reproduce the full fixture's2048 baseline integer
words and keep the post-projection configuration fixed across the two checked
tokens. Finer gate/up weight groups change first-layer relative Euclidean-norm
error only modestly. Ordered ablations identify larger effects around8-bit down
inputs and down weights. Per-row down-weight scaling yields5.35/5.30 percent
error versus7.70/9.26 percent with the current global scale. Those row-specific
output scales were interpreted in software; no new hardware or task-accuracy
claim follows. See `records/group_quantization_sensitivity.json` and
`records/full_layer_quantization_error_audit.json`.

A bounded image-conditioned software audit now runs the complete floating-point
TinyLLaVA-v1 model on its published diagram/question example and captures three
image positions plus the final text position in the first language block.
An independent wide-integer reconstruction matches all 8,192 dense and 8,192
predicted output words. With the earlier text-derived formats held fixed,
first-layer relative Euclidean error is 14.2-27.2 percent without prediction
and 29.0-35.8 percent with the current local thresholds. The down-input
quantizer contributes much of the error. These four positions from one public
demo are neither a held-out accuracy benchmark nor image-conditioned hardware
simulation. Source hardware and the existing fixtures are unchanged.
See `records/image_quantization_reference.json` and
`records/image_quantization_error_audit.json`.

`tri_oracle_integer_reference.py` provides a graphics-processor implementation of
the same local signed integer arithmetic. It matches all 8,192 dense and 8,192
predicted archived image-derived outputs, including their returned physical
scales. Independent literal cases cover positive, zero and negative gain; a
wrong-scale mutation is rejected. The full Python suite now passes 30 checks.
In a bounded one-image experiment, replacing the first language block's
feed-forward arithmetic preserved all 16 floating-baseline generated tokens
for both tested formats, with and without prediction. The remaining 21 blocks,
attention and vision stayed floating point. This is model integration evidence,
not dataset accuracy, image-conditioned hardware simulation or paper matching.
Evidence: `records/integer_reference_validation.json` and
`records/integer_model_image_probe.json`.
