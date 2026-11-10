# Tri-Oracle reproduction in progress

The preserved current placed candidate now passes the complete archived trained
feed-forward layer: 2,048 inputs, 5,632 intermediate channels and 2,048 exact
integer outputs on twenty mapped cores with 600 actual vendor memory models.
A wrong first-word reference is rejected using the same compiled image. The
independent qualification binds the current parent, unchanged fixture, native
logs, thirteen output packets and preserved database fingerprint across 421
input/evidence files. See `records/real362_mapped_functional_qualification.json`.

This is functional verification with prepared normalization/sign inputs and
ideal clocking; delay annotation and native timing checks are disabled. The
fixture skips zero channels, so it demonstrates no pruning benefit. Complete
architecture, model accuracy, memory reconciliation and routed timing remain
unqualified, and the paper gate remains on hold.

A resident batched-projection sequencer now reuses each loaded weight tile
across sixteen token rows on the unchanged twenty-core fabric. Two feature
tiles cover all 2,048 input features and 160 output rows. Literal and trained
first-layer cases each pass all 2,560 integer outputs in Icarus Verilog and
Cadence Xcelium; the latter uses all 600 actual vendor memory models. The
trained case preserves full-matrix quantization and 145 token/channel skips.
Six native arithmetic mutations are rejected at independently predicted words.
See `records/batch360_source_qualification.json` and its lossless native logs.

The controller retains a tagged partial-sum context across feature tiles and
rejects appends with a different token count, mask base or activation stride.
Invalid continuations, stale appends and wrong result slots flush ownership;
stalled successful recovery is tested. The resident tests preload operands and
prediction masks. Directed output stalls now also pass for 1, 3, 8 and 16 tokens,
with 4,480 exact output comparisons and unchanged production hardware. The
original short tests had correct arithmetic but exercised zero stalls. See
`records/batch370_tail_qualification.json`.

A separate direct-memory-access (DMA) owner now fetches operands itself on the
same twenty-core, 600-memory source hierarchy. It loads each activation word
once and each weight word retained by any token once per descriptor, then
reuses the weights across the batch. The sixteen-token, 2,048-feature,
160-output trained tile transfers 360,448 bytes in 2,816 native bus requests.
Per-word read histograms check every operand; these are simulated traffic
measurements, not system latency or energy measurements.

The corrected owner passes 6,560 trained output comparisons, including eight
fault/recovery cases without external reset. Another 525 literal comparisons
cover short bursts, 35 selected outputs, padded lanes, original channel IDs
0 and 65,535, and invalid address/alignment/capacity descriptors. Two directed
counterfactuals expose unfinished-burst and cancelled-request faults in the
earlier owner. Stopping the reusable native supervisor also terminates its
owned simulator groups. See `records/batch377_dma_qualification.json` and its
17 losslessly archived native logs. Prediction masks are still prepared inputs;
integration with gated feed-forward execution, full-model scheduling, synthesis
of this new owner and routed timing remain unfinished. The paper gate stays on
hold, and no physical design advancement is authorized.

The paired gated path now computes gate and up together for 80 original
channels on the same twenty-core, 600-memory source hierarchy. Each cluster's
32 physical rows hold sixteen gate/up pairs. Only one completed raw packet is
retained while the existing result queues hold later token packets. Captured
gate/up/down shifts vary independently by token, preserving the frozen
first-token protection and ordinary-token precision policies.

The trained fixture retains all 2,048 input features and quantizes the complete
5,632-channel matrices before selecting original channels 0, 71, ..., 5609.
Independent scalar and graphics-processor calculations agree on every mask,
gate/up sum, signed16 nonlinear result and signed8 down input. Native source
simulation passes 10,240 value comparisons, including all-masked execution,
up-read errors, invalid up addresses, and queued metadata/activation-tag faults
followed by recovery without external reset. A separate arithmetic-only test
checks 2,324 extrema/rounding/saturation cases across all 64 shift settings.
Removing either wrapper fault guard makes its directed regression fail. See
`records/batch384_gated_qualification.json` and its lossless native logs.

This qualifies a gated intermediate tile with prepared prediction masks.
It does not include multiplication by the down matrix or a complete feed-forward
layer. Shared scheduling of all three projections, full-model execution and
physical implementation of the new batched path remain unfinished. Numeric
formats and row pairing are local reconstruction choices; no paper accuracy,
latency, energy or whole-chip timing claim follows from these tests.

A streamed down-projection operator now covers all 5,632 intermediate features
for sixteen tokens on the unchanged twenty-core, 600-memory source hierarchy.
Six feature tiles retain native partial sums while each input tile uses at most
512 words per core. Each activation word is read once; each required weight
word is shared across the token batch. A 128-bit tile summary suppresses reads
of weight words whose eight input bytes are zero for every token. Those words
are cleared locally so fresh memory contents cannot enter the arithmetic.

The fixture reconstructs all 2,048 canonical layer outputs before selecting
160 original output rows spread from 0 through 2047. It preserves the previous
paired gated/down-input subset exactly. Native decode, eight-token tail,
sixteen-token, zero-input and late-fault recovery cases pass 4,960 output
comparisons over the full 5,632-feature width. The late fault follows two
retained partial tiles; recovery completes without external reset. Disabling
local weight clearing makes the fresh-memory zero-input case fail on unknown
data. See `records/batch388_stream_qualification.json` and its lossless logs.

The joined batched controller uses one fabric for the paired gate/up
projection and the down projection. It waits for every intermediate-memory
write acknowledgement before issuing down-projection reads. The small-frame
Xcelium tests passed with 519 exact outputs and 288 checked intermediate bytes
per successful frame, including six fault and recovery cases. The complete
sixteen-token trained-layer run matched all 32,768 outputs and 90,112
intermediate bytes, with 208 output packets and all original feature and
channel dimensions. It used prepared activations and masks on 20 cores with
600 compiled memory models. Xcelium took 56 minutes and 26 seconds. See
`records/batch393_trained_qualification.json` and
`records/batch393_literal_result.json`.

A producer may offer a mask before `mask_ready`. It must hold the tag, start,
count, last flag and payload stable until acceptance, unless `done_valid` and
`done_error` report a terminal error for that tag. In that case the producer
must withdraw the outstanding unaccepted mask before asserting `done_ready`
or reusing the tag and interface. The caller must discard any earlier writes
or output packets from the failed frame. If reset is used, it must also reset
both memory peers. The mask-control tests verified cancellation of a held
mask after a scratch write error, recovery with the same tag without reset,
and rejection of the stale mask when the producer ignored cancellation. The
combined qualification binds nine successful simulations, the stale-mask
control, eleven native logs, and the separately verified trained software
fixture. See `records/batch395_frame_qualification.json`.

Complete model execution, mapping of the new batched path, whole-chip routing
and timing, and the paper's measured accuracy, latency and energy remain
unqualified.

The existing weight predictor now reproduces every mask for the same sixteen
trained tokens when given raw residual codes and packed weight signs. Xcelium
checked all 90,112 skip decisions, both branch decisions for each channel, and
every address in the 55,616 sign reads. The predictor flagged 5,231
token/channel pairs to skip. A signed 16-bit residual with 13 fractional bits
preserved the reference outlier decisions for this fixture. The standalone
baseline repeats normalization for each 32-channel group. See
`records/batch396_mask_fixture.json` and `records/batch396_native_masks.json`.

The reuse controller keeps only the outlier flags and signs, packed four
strips per word in two compiled 512-by-64 memories. Xcelium counted 16
normalizer starts for the entire batch, compared with 2,816 group-by-token
normalizations in the baseline. All 90,112 skip decisions, both branch masks
and all 55,616 external sign reads matched the same trained fixture. The
five native cases cover early and late sign failures, mismatched replay,
cancellation of both held residual offers, same-tag recovery and a
shorter frame crossing the two banks. The cache adds 8,192 bytes to this
frontend, which remains to be accounted for in the whole-chip design. See
`records/batch398_outlier_result.json`.

The mask adapter converts original 32-channel skip groups to token-major
80-channel keep packets, retaining sixteen bits per token when a group
crosses a packet boundary. A Xcelium run with the actual predictor matched
all 71 trained packets, 90,112 keep bits and 768 padding bits. Literal
controls cover both boundary alignments, the maximum 8,160-channel frame,
and cancellation of a stalled packet. An unrelated tag leaves the packet
held. The coordinator must clear a cancelled offer and its cancellation
before reusing that tag. Removing the carry causes the 16-channel tail
test to fail. This run checks the adapter with the trained predictor. See
`records/batch399_mask_packet_result.json`.

The joined predictive frame now generates masks from raw residuals and
packed weight signs, then runs the existing feedforward controller on the
same twenty cores. A read arbiter holds the selected owner from the stalled
request through the accepted last response beat. Twelve Xcelium cases
matched 6,228 output values and 4,608 intermediate bytes. They cover
contending sign and operand reads, a stalled real mask that transfers
unchanged before the abort marker, invalid descriptors rejected before any
traffic, and same-tag recovery. The native hierarchy has 602 memory models
including the two outlier stores. This is a small-frame functional check.
The caller supplies quantized activation operands and both residual passes.
Trained joined execution, timing, and the paper benchmarks remain to be
verified. See `records/batch400_predictive_result.json`.

The coordinator now expresses each handshake dependency separately. Both
coordinator feedback warnings disappeared in the same Verilator setup,
and all twelve Xcelium cases reproduced their exact output, byte, and bus
inventories. Backend warnings remain. See `records/batch401_lint_result.json`
and `records/batch401_predictive_result.json`.

The existing learned-scale normalization hardware now has a full trained
activation check. Xcelium matched all 32,768 normalized codes and all
32,768 activation codes against independent integer and graphics-processor
references for the same sixteen tokens. The local format uses a signed
16-bit residual with 13 fractional bits, eight fractional bits after
normalization, and 15 fractional bits for the learned coefficients.
It preserved all outlier decisions. Relative to the prepared activations,
318 codes changed by one step. Replaying the trained feedforward arithmetic
in software changed 32,452 output codes and moved the output vector by
3.83 percent relative Euclidean norm. The hardware activation path is
still separate from the compute frame, and this sensitivity check gives
no model-accuracy result. See `records/batch403_activation_precision.json`
and `records/batch403_native_activation.json`.

The shared normalization frontend now uses each normalized strip both to
write its learned-scale activation and to store its pre-scale outlier
metadata. It buffers one 128-byte burst and waits for all activation write
acknowledgments before reading weight signs. On the full trained fixture
Xcelium checked 32,768 activation bytes in 256 bursts, 90,112 mask bits,
and every one of 55,616 sign reads with sixteen normalizer starts. Early
and final write errors and a malformed replay produced no sign traffic
and recovered on the same tag. A 17-strip case checks the final one-beat
burst and the next token's stride. An independent one-strip control also
reproduces the stale-address failure when the old metadata write-enable
ordering is restored. The generated activation allocation has yet to be
consumed in a complete trained compute run. See
`records/batch405_normalize_result.json`.

The learned frame connects the generated activation allocation to the
twenty-core feedforward fabric. The frontend owns the shared write port
until its final activation acknowledgment. Only then can a complete
prediction packet start compute, which takes ownership for intermediate
writes. The twelve small-frame Xcelium cases matched 3,168 generated
activation bytes, 4,320 intermediate bytes and 6,228 output values.
They cover first and final activation-write failures, invalid writable
overlaps, malformed replay, and errors during compute or prediction.
The full trained reference independently matches all 90,112 intermediate
bytes and 32,768 output words in central and graphics processor
arithmetic. Full trained hardware execution and paper benchmarks remain
separate qualifications. See `records/batch406_learned_result.json`
and `records/batch407_learned_fixture.json`.

The trained feedforward run with hardware-generated masks completed all 71
gate groups and 13 output groups on the twenty-core fabric. Xcelium matched
32,768 output words, 90,112 intermediate bytes, and all 55,616 sign-read
addresses. The one-hour run used prepared activation codes and 602 compiled
memory models. The lossless log and its digest are recorded alongside
`records/batch402_trained_predictive_result.json`.

The complete trained layer also passes with hardware-generated activations.
Xcelium checked 32,768 activation bytes from 16 normalization starts, all
55,616 sign-read addresses, 90,112 intermediate bytes, and 32,768 output
words. The twenty-core run retired 208 packets using 602 compiled memory
models and the fixed-point reference for the locally generated activations.
The result binds the terminal log and the separate progress log, which
records all 71 mask groups and 13 output tiles. See
`records/batch408_trained_learned_result.json`.

The attention fixture captures the actual rotary query and key vectors from
the first language layer of the pinned model. Reconstructing dense causal
attention on the selected rows matches the model's attention output to
about one ten-millionth in absolute value. Central and graphics processor
integer calculations agree on all 290,880 query-key scores. The fixture
preserves 46,080 scores from sink, inner, and recent tiles and converts the
paper's cutoff of four scaled score units into each head's integer scale.
The local 32-key tiles and ratio threshold of one classify four of the
32 heads as streaming for this image and layer. This diagnostic provides
trained inputs for the head predictor. Head classification across the
model, hardware scheduling, and the paper's attention speedup remain
unverified. See `records/batch409_attention_fixture.json`.

The hardware head classifier now matches the inner and recent intensity
counts for all 480 trained rows and the final type of all 32 heads in
Xcelium. Directed cases verify the strict sink cutoff, causal lane masks,
exact ratio ties, the 4,096-row accumulator limit, and error recovery.
Three deliberately incorrect comparisons fail at the expected boundary.
The test supplies precomputed scores. The next integration step connects
the query-key multiply and accumulation path to the classifier. See
`records/batch410_classifier_result.json` and its native log archive.

The shared tensor fabric now generates those scores from trained query and
key bytes and feeds the classifier directly. Xcelium matched all 46,080
scores, both intensity counts for each of the 480 rows, and all 32 head
decisions. Every operand read was checked against the selected keys. The
same path verified 58 scores from partial tiles, stalled output stability,
and recovery from invalid ranges, a future key, an unaligned query, and a
read error. A corrupted score failed at the first changed lane. The fabric
uses its existing twenty cores and 600 compiled memory models. The fixture
selects one query row per tile position for one image and layer. Tile
scheduling across complete heads and layers and the paper's workload and
timing results remain unqualified. See `records/batch411_attention_score_result.json`.

The expanded reference covers all 510 causal query rows per head from the
first three distinct tile positions through the final partial tile. Central
and graphics processors agree on 1,312,800 selected scores and all 32,640
intensity counts. All 46,080 previously sampled scores reproduce exactly.
Using every row classifies two heads as streaming at the local ratio
threshold, compared with four when using only the sampled rows. Fixed and
floating point agree on all 32 head types for this image and layer. The
receipt records the 32 batches per head for testing key reuse on hardware.
See `records/batch412_tiled_attention_fixture.json`.

The tile adapter now submits up to sixteen query rows together, with a
causal mask for each row. In the 30-row Xcelium check, the shared fabric
matched 2,385 live scores and all 495 masked positions. It read each
selected key word once per batch, for 1,392 key words across the two
batches. The same rows would require 19,080 key words if issued one at a
time under the existing read policy. Five fault cases cover invalid and
overlapping tile descriptors, an interrupted read, a malformed output
after a valid row, and a wrong completion tag. A separate control that
allows a future key into an earlier query fails at that exact score.
See `records/batch413_canary_tile_result.json`.

The full Xcelium sweep now passes all 32 heads and 16,320 query rows on the
shared twenty-core fabric with 600 compiled memory models. It checked
1,312,800 valid scores, 253,920 masked slots, and every head decision.
The hardware read 720,384 key words. The independent traffic calculation
for the same rows issued one at a time gives 10,496,846 key words. This
measures the prediction workload's key reads for this fixture. See
`records/batch413_full_tile_result.json` and its native log archive.

The frozen attention policy was also evaluated across 22 language layers on
each of 16 diagram images. It classified 9,145 of 11,264 heads as streaming
in fixed point and 9,140 in floating point. Only 23 individual decisions
changed with quantization. Independent processor calculations matched
28,881,600 selected scores on the first image across all layers. The fixed
point rate of 81.2 percent exceeds the paper's 50 to 75 percent observation.
This experiment uses the local ratio of one, the pinned checkpoint, and
unmerged prefill inputs. See `records/batch414_head_policy_result.json`.

A head descriptor now drives the complete local tile schedule in hardware.
Xcelium checked all 32 batch descriptors and the final intensity counts
for 510 trained query rows, including the 14-row tail. Six invalid
configurations caused no reads. An injected read failure in the second
batch invalidated the verified first-batch prefix and allowed a retry with
the same tag. Holding the query address fixed failed at the second
descriptor. See `records/batch415_head_schedule_result.json`.

On the 64-question Visual Question Answering v2 validation pilot, the same
policy classified 36,834 of 45,056 head decisions as streaming in fixed
point, or 81.8 percent. Figure 31.6.4 reports 62 percent for the paper's
workload. Floating point classified 36,833 as streaming, with 101 individual
decisions changing between numeric formats. The pilot uses the local ratio
of one and unmerged prefill inputs. It measures head classification before
sparse attention or answer generation. See `records/batch416_vqa_head_policy_result.json`.

The same pilot now includes generated answers under the local streaming mask,
which keeps the first 32 keys and most recent 32 causal keys for streaming
heads. The dense control and the explicit causal mask both reproduced all
64 archived answers and the official 74.69 percent consensus score. Live
head prediction scored 69.38 percent and changed nine answer sequences.
Freezing the decisions from the dense pass scored 58.28 percent and changed
18 sequences. The live policy kept 37.4 percent of eligible prefill pairs.
The graphics processor applies the mask to dense attention tensors, so that
pair count is an arithmetic projection. See `records/batch417_sparse_answers_result.json`.

A separate set of 16 diagram questions selected an 8:1 intensity ratio.
It preserved all 16 dense answer sequences and kept the fewest eligible
prefill pairs among the qualifying ratios. The ratio was frozen before
scoring the 64-question validation pilot. It classified 49.9 percent of
heads as streaming and scored 69.38 percent, the same consensus score as
the local ratio of one. This leaves a 5.31-point loss from the pilot's dense
control. The local window and unmerged input policy remain explicit in
`records/batch418_ratio_calibration.json` and `records/batch418_vqa_ratio_result.json`.

On dense prefill activations from 64 validation images, the sign-based merger
was evaluated at six thresholds across all 22 language layers. The local
75 percent threshold merged 44.5 percent of image tokens, compared with the
44 percent shown in Figure 31.6.3 for the paper's visual question answering
workload. The probe uses the 2,048 signs entering attention on a 24 by 24
image grid and gives the upper representative priority on a tie.

Xcelium matched all 76,032 merge decisions for one trained image across the
six thresholds and 22 layers. The causal size unit matched 15,007,077
values across 76,692 prefix queries, including out-of-order revisits.
Changing the inclusive threshold to a strict comparison failed at the
expected token. See `records/batch419_trained_merger_fixture.json` and
`records/batch420_trained_merger_result.json`.

The validation pilot now applies the causal sizes as logarithmic bias in
floating-point attention and passes compact key and value tensors to the
attention kernel. Merging alone removed 43.8 percent of image key slots and
scored 70.62 percent. Combining merging with live head prediction scored
68.44 percent. The identity control reproduced the dense 74.69 percent score.
The combined mode reuses the 8:1 ratio from unmerged calibration and counts
its sink and recent windows in surviving representatives. The model retains
original query and cache slots. Expanded-representative comparisons verify
the causal bias on trained rows, and decode controls check both Boolean and
additive masks. See `records/batch421_merge_aware_attention_result.json`.

The cumulative decoder removes merged image queries, residual rows, and
feedforward inputs before each layer. Its key and value caches hold only
the surviving keys for that layer and retain original rotary positions.
The 64-question pilot used 46.2 percent fewer prefill cache slots across
layers and scored 71.09 percent with compaction. Adding the local 8:1
streaming policy scored 69.06 percent. The dense control reproduced all
archived answers and scored 74.69 percent. Cached decoding matched a fresh
teacher replay on the anchor question in all three modes. The local merge
rule keeps existing groups intact and uses original upper and left neighbors.
See `records/batch422_compact_decoder_result.json`.

The joint software pilot applies the fixed-point feed-forward reference across
all 22 language layers while physically compacting model tensors and selecting
streaming attention heads. On the same 64 questions, the combined mode scored
61.88 percent, compared with 57.97 percent with weight skipping disabled,
69.06 percent with floating-point feed-forward, and 74.69 percent for the dense
floating-point control. The combined mode removed 45.70 percent of prefill
cache slots and skipped 8.43 percent of feed-forward channels across its retained
prefill rows. Independent rescoring checked all 320 answers and matched all 192
archived control answers. Attention and normalization inputs still use floating
point. These are model-reference scores and mask counts, with no measured chip
timing, traffic, or energy. See `records/batch424_joint_pilot_result.json`.

The cumulative hardware merger consumes signs only for prior surviving roots
and holds a single 24-slot image-row sign bank. Xcelium replayed both live
traces for the anchor image, matching 25,344 map entries and 4,380,542 causal
sizes over 44 layer frames. Only 15,561 input sign vectors were accepted.
The stale-representative control failed at its expected cell. The test also
checks invalid configuration recovery and delays completion until the final
map transfer. See `records/batch423_cumulative_merger_result.json`.

The proportional softmax now accepts signed fixed-point attention scores and
causal token sizes for up to 1,024 keys. It computes a stable exponential,
multiplies by group size before truncation, and shares one approximate
reciprocal across the row. A size of zero masks a key. The current implementation
reuses a single-port scratch array for scores and weights.

Cadence Xcelium and Icarus Verilog each matched 12,915 probability codes on
39 rows, including 25 trained prompt and decode rows from layers 0, 10 and 21.
The trained rows use compact query and key tensors from the archived answer,
independently checked integer dot products, and causal sizes recomputed from
the archived merge maps. The largest absolute error from real proportional
softmax at the same quantized scores was 0.000171 on the trained rows. The tests
reject unit sizes, a masked maximum, and premature exponent truncation. See
`records/batch425_proportional_softmax_result.json`.

The compact attention row controller connects the twenty-core score fabric to
the causal-size unit, proportional softmax, and a signed 64-feature value
accumulator. It loads the image merge map, derives the visible compact prefix,
and omits both key and value reads outside the sink and recent windows for a
streaming row. Retrieval rows run in batches of up to 160 keys. Each score
batch must report successful completion before its scores can enter softmax.

Xcelium matched 3,235 signed dot products and 1,600 exact value components on
25 trained prompt and decode rows with 600 vendor memory models. The largest
weighted-value error against real softmax on the same quantized operands was
0.01054 value-code units. Three additional boundary rows cover a 1,024-key
cache, a long original sequence, and an incomplete mixed-image prefix. The
test also rejects early frame abandonment, omitted group sizes, and an
unselected streaming key read. The caller still supplies the merge map and
head type. Value memory uses an ordered vector response interface. Scratch
mapping, whole-model scheduling and physical timing remain open. See
`records/batch426_attention_row_result.json`.

The attention layer controller now supplies the row engine with the live output
of cumulative token merging and the cached result of native head prediction.
Prediction and attention rows share the same twenty-core tensor owner. The
emitted merge map is transferred to both the caller and the causal-size unit.
The caller commits the map only on successful frame completion. Failed merge
frames drain before completion, and a rejected new image cannot reuse the
previous image's map. Each accepted frame invalidates its predecessor's cached
head types.

Xcelium checked all 12,672 entries in 22 distinct trained merge frames. Five
heads from layers 0, 10 and 21 matched independent integer prediction totals
with the local 8:1 ratio, including two streaming heads. Those decisions drove
25 trained prompt and decode rows that matched 3,235 scores and 1,600 weighted
value components with 600 vendor memory models. The caller still provides
signs and compact query, key and value operands. The controller retains the
active layer's map and head decisions. Whole-model decode still needs to
restore the corresponding state when it returns to an earlier layer. See
`records/batch427_attention_layer_result.json`.

The context-enabled attention controller keeps all 22 layer maps in four
compiled 512-by-64 static random-access memories. Each map uses 90 words, for
1,980 occupied words and 15,840 payload bytes in 16,384 installed bytes.
Head decisions, their validity bits, and frame geometry use separate registers.
Layer restoration reloads the causal-size unit without replaying signs or
rerunning head prediction. It leaves the cumulative merger's prompt sequence
intact so prompt processing can also resume after an intervening restore.

Xcelium checked the chronological prompt and decode schedule on 22 trained
maps with 26 successful restores. It reproduced 1,600 exact value components
across 20 prompt and five decode rows. The tests reject stale layer maps,
missing restored head decisions, and rows that use invalidated heads. The
isolated map store also mapped in Genus with all four memories retained and
passed 12,672 restore comparisons on the mapped netlist. Its estimated
pre-placement setup slack was 1.132 ns at the 580-megahertz target and the
0.9-volt, 125-degree Celsius library corner. See
`records/batch428_attention_context_result.json` and
`records/batch428_context_synthesis_result.json`.

The query, key, and value projection controller produces the 40 attention
heads from 2,048 normalized input features on the shared twenty-core tensor
engine. It uses up to two heads per weight tile, one activation scale per
token, and one output scale per head. It applies fixed-point rotary position
encoding to queries and keys and emits values directly after requantization.
Vectors can stream before the terminal status, so the consumer commits them
only after successful completion.

On four trained positions, including the first decode token, Xcelium matched
10,240 dot products and 10,240 operand bytes. The tests reject malformed
angles, transport and tag failures, and an inverted rotary sign. The caller
supplies normalized activations and rotary coefficients. The generated vectors
have yet to feed the attention controller in a joint simulation. See
`records/batch429_qkv_result.json`.

An independent graphics processor experiment chose power-of-two input-channel
scaling on four separate prompts. On the held-out trace, aggregate relative
value error fell from 25.47 to 8.65 percent, while query error rose from 4.17
to 5.11 percent and key error rose from 2.46 to 3.40 percent. This experiment
uses the same output scales. The native run above uses the baseline operands.
See `records/batch429_qkv_equalization.json`.

Protected-format programming now passes 22 paired first/ordinary-token tests
on the production twenty-core source with 600 actual vendor memory models.
All 1,540 selected-contribution integer outputs match independent scalar sums.
Four native wrong-shift/reference controls fail at their exact expected words;
second-token controls first require the initial token to pass. Original channel
identities, weight addresses, captured configuration, stalled outputs and two
frames without an external reset are checked. See
`records/format354_source_qualification.json`.

Each token fixture preserves all 2,048 input features and the original 5,632-byte
down-matrix stride, while selecting two original 32-channel groups and 35 output
rows for informative coverage. Actual protected model-prefix inputs and full
matrix quantization are retained. Complete native logs and fixture metadata are
losslessly compressed. This qualifies selected-contribution source programming;
complete-layer hardware programming, the current mapped candidate, normalization
hardware, whole-model execution and paper results remain unverified.

An independent capacity audit binds the preserved placed candidate's native
inventories to vendor module dimensions: 600 memory instances contain 399,360
bytes, or 390 kibibytes. The paper's 405KB label matches neither decimal nor
binary interpretation of that total. No uninstantiated storage is added, and
the paper gate remains on hold. See `records/memory355_candidate_capacity.json`.

First-token protection now passes complete answer-generation and incremental
decode checks on the fixed 64-question pilot. The protected prediction mode
scores 67.81%, versus 63.44% for the earlier prediction mode. Protected dense
execution scores 66.72%, versus 67.81% for the retained dense reference; this is
an accuracy tradeoff. The floating model remains at 74.69%. All 192 archived
baseline answer sequences and per-question scores reproduce exactly. See
`records/format348_official_scoring.json` and
`records/format349_protected_generation_qualification.json`.

The new dispatcher retains the earlier format only for global token zero and
keeps a positive token offset during incremental decoding. Five real graphics
processor controls use the full 2,048-feature input width. The full model test
records and independently checks every layer's token-offset and protection
sequence, including 2,288 dense and 2,222 prediction-enabled layer decode calls.
All 320 inference cases completed. Complete inference metadata is losslessly
compressed in `records/format346_vqav2_inference.json.gz`. The integer arithmetic
and model weights are unchanged. This position-based precision control is a
local reconstruction choice; hardware programming and full paper accuracy remain
unverified. Only the 22 language feed-forward sublayers use integer arithmetic.
Re-running requires the local model assets and historical receipts named by the
source-hash manifests.

The earlier input-exponent calibration candidate was **rejected** by full-model
execution. Its local mean per-token error improved from 0.229679 to 0.167708,
but both new dense and prediction-enabled variants scored 0% on the fixed
64-question pilot. All 192 archived floating/dense/predicted answer sequences
and per-question scores reproduced first. See
`records/format339_official_scoring.json` and
`records/format340_candidate_rejection.json`. The full 320-case inference
metadata is losslessly compressed in `records/format337_vqav2_inference.json.gz`.
The earlier fixed-format profile remains the retained comparison below.

A one-fitting-image propagation trace isolates a first-token failure: its
layer-2 scale exponent changes from -5 in the floating capture to -6 after
earlier integer layers. The new table contains -5 and -7, so it selects an
ordinary-token fallback and reduces the layer output norm from about 288 to
1.2. Changing only layer 2 still reproduces that first-token collapse in the
prefill diagnostic. Better isolated-layer
error therefore does not establish end-to-end model correctness.

In a separate prefill-only counterfactual, retaining the earlier first-token
format preserves its normalized input and integer output bit for bit at all
22 layers. Final-logit relative error on that one fitting input falls from
0.886125 for the rejected candidate to 0.188320; the retained fixed policy
gives 0.226035. This is diagnostic evidence, not answer-generation accuracy,
incremental-decode support or hardware qualification. See
`records/format343_propagation_audit.json`. Its `fallback_rows` counts input
coverage before the first-token override; the explicit first-token fields
describe the effective override. No clock distribution or whole-chip routing
is authorized by these software experiments.

Latest accepted software accuracy diagnostic: extending the legal per-layer format search
improves official Visual Question Answering version 2 (VQAv2) scoring on the same
fixed 64-question pilot. Dense integer feed-forward execution rises from 64.84%
to 67.81%; prediction-enabled execution rises from 62.34% to 63.44%. The unchanged
floating-point model scores 74.69%. All 64 floating and legacy dense answer token
sequences and per-question scores reproduce exactly. See
`records/format326_official_scoring.json` and its scoring controls.

The extended settings were fitted on eight separate, unlabeled diagram images.
On eight reused diagnostic images, mean layer output relative error falls from
0.223269 to 0.182272. A previously poor layer improves from 0.867216 to 0.026957
by attenuating the up branch with a larger nonnegative right shift. The measured
problem is gated-product range clipping; gate-input range overflow was absent.
No weights or integer arithmetic changed. The 256-case graphics-processor run
completed in 111.75 seconds. Only the 22 language feed-forward sublayers use
integer arithmetic; attention, vision, normalization, residual additions and the
vocabulary head remain floating. The 64 reused validation questions are a local
diagnostic, not the full benchmark or recovered paper protocol. Applying these
settings to the hardware configuration remains unverified. The complete extended
search metadata is losslessly compressed in
`records/format322_extended_calibration.json.gz`; no model weights or image data
are included.

Latest paper-method milestone: `verilog/tri_oracle_causal_token_size.sv`
implements causal, row-wise token sizes using the token-merge table, an origin
location table and an iterative cursor from Figure 31.6.3. It supports forward
and backward queries, holds output under backpressure, and reuses tables across
frames without a table-wide reset. Interfaces, backward-query support and the
current register-table realization are local reconstruction choices.

The unchanged final-frame merger/normalizer combination fails a concrete causal
regression: token origins `[0,1,0,3]` at query position 1 must weight the two visible
origins equally. Final-frame counts incorrectly produce eight-bit codes 170/85;
the causal counts produce 128/128. The new real merger-to-size-to-normalizer test
passes that case and four further rows. Native Xcelium tests also check 888 prefix
rows and 18,084 origin/count words at capacities 1, 2, 3, 4, 17, 32, 33 and 576. Existing
related tests pass, and a deliberately omitted backward decrement is rejected.
See `records/causal314_functional_validation.json` and the source testbenches.
This is a standalone method qualification. Compiled memory mapping, full-chip
integration and physical implementation of this block remain unfinished.
The same source also passes Icarus Verilog at capacities 17 and 576 and in the
merger/normalizer integration. Both simulators check a full table without a final
marker, reset during partial loading and exclusive frame/query acceptance. See
`records/causal315_icarus_validation.json` and `records/causal316_boundary_validation.json`.

To run the independent prefix reference test inside the configured container:

```sh
iverilog -g2012 -s tri_oracle_causal_token_size_tb -o .cache/causal_size_test.vvp \
  verilog/tri_oracle_causal_token_size.sv verilog/tri_oracle_causal_token_size_tb.sv
vvp .cache/causal_size_test.vvp
rm .cache/causal_size_test.vvp
```

Latest mapped functional milestone (controller273): the repaired prepared prediction/feed-forward
parent passes all twelve functional cases on twenty compute cores and 600
compiled static random-access memory (SRAM) models. The test checks 4,420 exact
hidden outputs, successful and erroneous backpressure, memory faults and reset
recovery. A separate run rejects a deliberately wrong integer sum using the same
hardware, simulator, memory inputs and observer bench. The passing eight-worker
Xcelium run took 1,442.13 seconds. See
`records/controller278_physical_functional_qualification.json` and its bound
`controller274` native logs. This supersedes the controller260/261 mapped
functional milestone for the current physical parent.

This fixture supplies prepared normalized/sign inputs and analytically saturated
numeric operands. It establishes mapped functional behavior without delay
annotation. Full standard-cell mapped trained-layer execution, whole-model
accuracy, routed parent timing and the paper's measured results remain unverified.

One complete archived trained first-language-layer fixture now passes on the
source integration with staged controllers: 2,048 input features, all 5,632
intermediate channels and 2,048 exact final integer outputs. The run used twenty
cores and 600 compiled memory models, checked all channel identifiers, and
completed 176 groups, 45,056 strips, 36 prediction packets and thirteen output
packets. It handled 1,580,544 memory requests and 56 output backpressure stalls in
4,103.06 seconds of simulator wall time. Prepared normalized inputs remain
externally supplied. This is one archived fixture; it does not establish
whole-model accuracy or the paper's latency and energy. See
`records/real190_full_functional_qualification.json`.

The prepared parent has legal geometric placement in a 3.6-by-3.6-millimeter die.
A new batch adds 2,212 noninverting buffers on 61 protected local signal branches,
covering 50,831 of 50,832 original loads. One external load remains on its original
net. All 930,840 pre-batch physical parent leaves, including sixty fixed macros,
retain their names, masters, positions, orientations and protection flags.
The remaining signal graph, direct constants, input/output pin poses, placement
halos, registered-reset ancestry and hierarchy/module protection policies remain
exact. An independent cold reload retains all 1,889,420 original core cells,
600 memory models, 86 preservation targets and all three original timing-constraint
sets. The later paired mapped simulation qualifies this physical candidate;
the original native receipt is retained unchanged.

Historical full-model reports at the unchanged 1.72414-nanosecond period recorded
slow setup -53.757862 nanoseconds, typical setup -40.258564 nanoseconds and fast
reset removal -0.089328 nanoseconds. Subsequent controls exposed dependence on
the high-fanout calculation cutoff, separately from default-delay annotation.
These historical values and comparisons remain unqualified; they establish no
timing improvement or closure. Reanalysis must first prove that every net is
below the calculation cutoff and that unused delay defaults do not affect the
result. These are pre-clock-tree, pre-route estimates with signal interference
analysis disabled. Clock distribution, power delivery, parent routing, timing closure and
paper-performance matching remain unfinished. See
`records/direct305_timing_control_diagnosis.json` for the failed cutoff control,
`records/controller278_physical_functional_qualification.json` and the published
`controller273` split-delay reports. The complete native metadata receipt is
losslessly compressed in `records/controller273_tree_result.json.gz`; it contains
hashes and results, not library or checkpoint data. The accepted-to-imported
hierarchy protection policy is also checked explicitly across the earlier260/266
and266/273 imports; see `records/hierarchy277_initial_import_validation.json`.

A native diagnostic also exposed indexed-name serialization differences in 65 of 114
physical driver lists. The name-list comparison preserves multiplicity and rejects
changed, extra and missing names. Eight literal cases and 114 native pair replays
pass. A separate geometry decoder passes 72 cases, including 61 actual native
coordinates. It handles the one-point list returned by the physical database
before coordinate arithmetic. Both fixes retain the original connection and
preservation gates. See `records/controller265_names_validation.json` and
`records/controller272_points_validation.json`.

Earlier preparation independently verified module uniquification and guidance
model import while retaining the original physical interfaces and protection
policies. The boundary timing model is guidance only; the latest three-corner
analyses restore all original core models and exclude that approximation.
The native inherited-protection fault control still rejects loss of the design
flag. See `records/unique235_preparation_qualification.json`,
`records/frame242_guidance_qualification.json` and
`records/design243_native_control.json`.

Earlier backend milestone: one shared backend executes projection, gate/up
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
in 588 seconds, checking 4,420 final hidden-output lanes. The full 5,632-channel,
2,048-input-feature, 2,048-output fixture retains 196 channels. Coverage includes
configuration rejection by either child, a prediction fault during committed
numeric memory work, memory faults and reset recovery. This test uses prepared
normalized/sign inputs and analytically saturated numeric operands; raw frontend
integration and model accuracy remain pending. See
`records/predicted101_functional_qualification.json`.

The separately named `tri_oracle_sparse_weight_dma_pipelined.sv` addresses the
long selector/multiply/add/overflow path without changing the original source.
Eighteen source and mapped-netlist cases and seven address-stage reset cases
pass. Isolated mapping at the slow 0.9-volt, 125-degree-Celsius corner reports
577 picoseconds of setup margin at a 1.72414-nanosecond period, with 2,047 cells
and 4,503.912 square
micrometers of library cell area. The explicit legacy-interface adapter in
`syn/run_tri_oracle_pipelined_predicted_frame109_validation.py` then joins the
candidate to the complete twenty-core hierarchy. All twelve actual-memory
cases pass, checking the same 4,420 final outputs. The complete test suite uses
10,110 additional clock periods; this is not a per-token latency measurement.
See `records/predicted109_functional_qualification.json`.

The existing sparse down controller maps to 11,031 cells at the slow corner,
but reports only a rounded zero-picosecond setup margin with estimated wiring.
That leaves timing work before whole-parent mapping and routing. None of the
isolated reports establishes complete-chip timing closure.

The same full-shape regression also passes with the simulator's four-worker
mode, but that run took 1,016 seconds versus 588 seconds with one worker.
Both runs checked identical case outputs. One worker remains the default for
this regression; no general hardware or simulator performance ranking follows
from this one comparison. See
`records/predicted108_multicore_comparison_qualification.json`.

The earlier routed single-core checkpoint has independent timing and geometry evidence.
The earlier twenty-core prediction parent has legal placement, but whole-chip routed
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
