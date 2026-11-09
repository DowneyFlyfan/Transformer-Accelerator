# Connect prediction batching to the qualified numeric frame controller

The numeric frame95 now passes18 actual-memory cases. The next integration must retain exactly one gated_down_fabric backend, twenty cores and600 compiled memories. Instantiating the old predicted_gated_fabric beside frame95 would duplicate the datapath and is excluded.

Extract only the prepared normalized-strip prediction, framing and160-ID batching control from predicted_gated_fabric into prediction_packet_stream. Reuse the unchanged strip_predictor, channel_compactor and predicted_dispatch. The extracted block has no arithmetic fabric, result-data bank or external memory port. Capture tag/features/dense_rows at configuration; validate32-row groups and strip framing; preserve stall-stable batches and the original IDs. Malformed input drains through group LAST before resetting prediction state and emitting one terminal error.

Connect that stream to feedforward_frame with an atomic configuration handshake. Give both children configuration only when both are ready. Route a terminal prediction error to an invalid selected-count packet (161), accepted only when the numeric controller next reaches its packet-ready boundary. That boundary follows completion/draining of the preceding down contribution; frame95 then invalidates all contexts and emits its existing terminal error. Do not reset the compute backend while an external memory transaction is outstanding. A numeric terminal error stops input and resets only the memory-free prediction frontend. Keep the existing frame transaction rule: a terminal error cancels earlier output prefixes.

Prediction inputs remain prepared normalized strips and packed sign planes, consistent with the existing qualified canonical prediction interface. Raw normalization, coefficient/sign fetching and activation-cache frontend integration remain separate unfinished work. Do not describe the joined prepared-strip top as a complete paper processor.

- [x] Observe missing prediction_packet_stream in the native packet test before adding production code (prediction100_missing_retry).
- [x] Implement the extracted controller; pass9 cases including5632-row/2048-feature prediction, full160-ID batches, exact-fill and partial/empty tails, captured fields, stalls, malformed framing after an accepted160-ID prefix and reset. Reject a wrong-ID reference. Evidence: prediction100_functional_qualification.json.
- [ ] Join production prediction packets to the qualified frame controller; independently test successful frames, sparse selection, empty selection and error/drain arbitration on the actual600 memories. Producer code must not schedule down rounds.
- [ ] Review and qualify the joined source revision, then prepare its separately identified synthesis/physical inputs. Preserve original37 files, accepted routed core44 and full models68 throughout the ongoing parent99 experiment.

No paper accuracy, power or post-layout timing result follows from these source simulations. Full-chip routing and quantitative comparison remain active goal requirements.
