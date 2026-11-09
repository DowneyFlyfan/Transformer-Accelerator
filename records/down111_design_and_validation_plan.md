# Registered address/cache path for sparse down projection

The existing slow-corner mapped controller reports rounded zero setup margin at a1.72414 ns period. Its longest path runs from chunk_start through original-ID selection, address addition and cache/next-state logic. This source change separates those dependencies; it preserves the transaction interface, layout, quantization, slot semantics and original implementation as a comparison.

Compute the row base once for each output row: register the row number, two8-by17-bit partial products, their combination, and the low/high base addition. Then capture each selected ID/value and register the low/high selected-byte address before cache lookup. Keep the registered address while waiting for a response; reuse the returned cache word without recalculating it. No extra arithmetic core or memory bank is instantiated.

Valid descriptors enforce output_start+output_count<=65536 and dense_features<=65536. Each processed row is at most65535, so row*dense_features<=4294901760<2^32. Combining the partial products into32 bits therefore loses no valid information. The subsequent33-bit low addition carries at most1; a33-bit high result detects64-bit overflow. Adding a selected ID uses another low/high pair with an explicit final carry check. Zero-valued selected entries retain the original overflow-rejection behavior.

- [x] Native missing-module failure observed before production code.
- [ ] Independent scalar/reference tests: accumulation, cache reuse, quantization, empty finalizers, maximum dimensions, address boundaries, malformed responses, stalls and coordinated reset.
- [ ] Wrong-reference rejection, independent review and slow-corner mapping with usable reported margin.
- [ ] Mapped-netlist functional tests, actual-memory cluster/fabric integration and full prepared-frame regression.
- [ ] Prepare a separately identified full-parent synthesis/physical revision. Whole-chip clock-tree/routing, all-corner timing, actual frontend/model accuracy and paper energy/latency/area remain required.
