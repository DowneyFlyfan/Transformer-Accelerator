"""Recompute workload counters from the captured per-layer row and head counts."""

import argparse
import json
from pathlib import Path
import re

from verify_tri_oracle_channel_scaled_down import ROOT, read, sha

MODES = ("identity_dense", "compact_streaming_dense", "compact_streaming_pruned")
PREFILL, DECODE, HEADS, CHANNELS, IMAGE_TOKENS = 600, 60, 32, 5632, 576


def verify(case):
    receipt, native_path, log = (case / name for name in ("receipt.json", "native_receipt.json", "console.log"))
    result, native = read(receipt), read(native_path)
    assert result["state"] == "normalized_workload_logical_trace_counted"
    assert native["state"] == "native_exit" and native["native_exit_status"] == 0 and native["log_sha256"] == sha(log)
    assert (result["prefill_tokens"], result["decode_steps"], result["channels"]) == (PREFILL, DECODE, CHANNELS)
    pins = result["input_sha256"]
    assert all(sha(Path(path)) == digest for path, digest in pins.items())
    original = ROOT / "records/all_layer_integer_model_validation.json"
    policy = ROOT / "syn/evaluate_tri_oracle_batch417_sparse_answers.py"
    assert pins[str(original)] == sha(original) and pins[str(policy)] == sha(policy)
    assert result["forced_tokens"] == read(original)["baseline_tokens"]
    window = sum(map(int, re.findall(r"(?m)^(?:SINK|RECENT)_TOKENS = (\d+)$", policy.read_text())))
    assert window == 64
    cases = result["layers"]
    assert tuple(cases) == MODES
    totals = {}
    for mode, layers in cases.items():
        assert [layer["layer"] for layer in layers] == list(range(22))
        for layer in layers:
            rows, streaming = layer["prefill_rows"], layer["streaming_heads"]
            assert rows == PREFILL - IMAGE_TOKENS + layer["image_roots"]
            assert 0 < layer["image_roots"] <= IMAGE_TOKENS and 0 <= streaming <= HEADS
            assert layer["decode_rows"] == DECODE
            if mode == "identity_dense":
                assert rows == PREFILL and streaming == 0
            for phase, keys in (("prefill", range(1, rows + 1)), ("decode", range(rows + 1, rows + DECODE + 1))):
                expected_pairs = sum((HEADS - streaming) * key + streaming * min(window, key) for key in keys)
                assert layer[f"{phase}_pairs"] == expected_pairs
                predicted = layer[f"{phase}_predicted"]
                assert 0 <= predicted <= layer[f"{phase}_rows"] * CHANNELS
                assert layer[f"{phase}_skipped"] == (predicted if mode == "compact_streaming_pruned" else 0)
        totals[mode] = {key: sum(layer[key] for layer in layers) for key in (
            "prefill_pairs", "decode_pairs", "prefill_rows", "decode_rows", "prefill_skipped", "decode_skipped")}
        totals[mode]["last_layer_image_roots"] = layers[-1]["image_roots"]
    traces = [line.split()[1:] for line in log.read_text().splitlines() if line.startswith("NORMALIZED_WORKLOAD_CASE ")]
    assert traces == [[mode, str(totals[mode]["prefill_pairs"]), str(totals[mode]["decode_pairs"])] for mode in MODES]
    paths = (Path(__file__), Path(__file__).with_name("run_tri_oracle_normalized_workload_trace.py"),
             receipt, native_path, log, case / "run_guard.py", original, policy)
    return dict(state="normalized_workload_trace_independently_counted", prefill_tokens=PREFILL, decode_steps=DECODE,
        checkpoint_revision=result["checkpoint_revision"], layers=22, totals=totals, channels_per_row=CHANNELS,
        evidence_sha256={str(path.relative_to(ROOT)): sha(path) for path in paths}, scope=result["scope"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", type=Path)
    case = parser.parse_args().case.resolve()
    result = verify(case)
    with (case / "verified.json").open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(result["state"], result["totals"], flush=True)
