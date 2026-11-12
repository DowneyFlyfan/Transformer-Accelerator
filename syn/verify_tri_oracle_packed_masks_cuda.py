"""Recompute the trained predictor masks directly from the packed sign image."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import threading
import time


ROOT = Path(__file__).resolve().parents[1]
GIB = 2**30


def memory():
    available = next(int(line.split()[1]) * 1024 for line in Path("/proc/meminfo").read_text().splitlines()
                     if line.startswith("MemAvailable:"))
    anonymous = next(int(line.split()[1]) for line in Path("/sys/fs/cgroup/memory.stat").read_text().splitlines()
                     if line.startswith("anon "))
    return available, anonymous


def run(output):
    assert Path("/.dockerenv").is_file()
    available, anonymous = memory()
    assert available >= 12.5 * GIB and anonymous <= 0.5 * GIB

    def guard():
        while True:
            available, anonymous = memory()
            if available < 11.5 * GIB or anonymous > 1.5 * GIB:
                os._exit(75)
            time.sleep(0.2)

    threading.Thread(target=guard, daemon=True).start()
    import numpy as np
    import torch

    torch.set_num_threads(2)
    assert torch.cuda.is_available() and torch.cuda.mem_get_info()[0] >= 14 * GIB
    torch.cuda.set_per_process_memory_fraction(0.1)
    torch.cuda.reset_peak_memory_stats()
    device = torch.device("cuda:0")
    start = time.monotonic()
    pins = {}

    def pin(path, expected=None):
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        assert expected is None or expected == digest, path
        assert pins.setdefault(str(path.relative_to(ROOT)), digest) == digest, path

    mask_record = ROOT / "records/batch396_mask_fixture.json"
    norm_record = ROOT / "records/batch403_activation_precision.json"
    sign_record = ROOT / "records/wac_packed_sign_line_result.json"
    native_record = ROOT / "records/wac_prefetched_metadata_native_result.json"
    for path in (mask_record, norm_record, sign_record, native_record, Path(__file__).resolve()):
        pin(path)
    mask, norm, sign, native = (json.loads(path.read_text()) for path in
                                (mask_record, norm_record, sign_record, native_record))
    invocation = ROOT / ".cache/physical/ranked_sign_slots/prefetched_metadata_32/trained/invocation.json"
    pin(invocation, native["input_sha256"][str(invocation.relative_to(ROOT))])
    argv = json.loads(invocation.read_text())["argv"]
    paths = {name: Path(next(arg.split("=", 1)[1] for arg in argv if arg.startswith(f"+{name}=")))
             for name in ("FIXTURE", "NORM", "PACKED")}
    masks = paths["FIXTURE"] / "branch_masks.hex"
    pin(masks, mask["files_sha256"][str(masks)])
    pin(paths["NORM"], norm["files_sha256"][str(paths["NORM"])])
    pin(paths["PACKED"], sign["evidence_sha256"][str(paths["PACKED"].relative_to(ROOT))])

    tokens, features, channels = mask["tokens"], mask["features"], mask["channels"]
    assert (tokens, features, channels) == (16, 2048, 5632)
    groups, strips = channels // 32, features // 8
    lines = np.frombuffer(bytes.fromhex(paths["PACKED"].read_text()), dtype=np.uint8)
    # Packed order is [group, strip, byte], with the lowest-address byte printed last.
    packed = torch.from_numpy(lines.reshape(groups, strips, 64)[..., ::-1].copy()).to(device)
    shifts = torch.arange(8, dtype=torch.uint8, device=device)
    bits = ((packed[..., None] >> shifts) & 1).bool()
    # Unpack [group, strip, pair, branch, half, channel] to [branch, channel, feature].
    weights = bits.reshape(groups, strips, 4, 2, 2, 32).permute(3, 0, 5, 1, 2, 4).reshape(2, channels, features)
    words = np.array([int(line, 16) for line in paths["NORM"].read_text().splitlines()], dtype=np.uint16)
    codes = torch.from_numpy(words.view(np.int16).reshape(tokens, features)).to(device)
    mask_bytes = np.frombuffer(bytes.fromhex(masks.read_text()), dtype=np.uint8).reshape(tokens, groups, 12)
    # The archived line stores gate, up, and final skip words in that order.
    expected = np.unpackbits(mask_bytes.reshape(tokens, groups, 3, 4)[..., ::-1], bitorder="little", axis=-1)
    target = torch.from_numpy(expected.transpose(0, 2, 1, 3).reshape(tokens, 3, channels)).to(device).bool()
    counts = []
    skipped = 0
    for token, row in enumerate(codes):
        chosen = torch.nonzero((row > 768) | (row < -768)).flatten()
        counts.append(chosen.numel())
        signs = row[chosen] < 0
        score = 2 * (weights.index_select(-1, chosen) == signs).sum(dim=-1, dtype=torch.int32) - chosen.numel()
        gate = (score[0] <= 0) & bool(chosen.numel())
        up = (score[1] == 0) & bool(chosen.numel())
        skip = gate & up
        assert torch.equal(torch.stack((gate, up, skip)), target[token]), token
        skipped += int(skip.sum())
    assert counts == mask["outlier_counts"]
    assert skipped == mask["skipped_channels"] == native["trained_replay"]["skipped"]
    assert groups * tokens == native["trained_replay"]["groups"]
    torch.cuda.synchronize()
    for name, digest in pins.copy().items():
        pin(ROOT / name, digest)
    result = {"state": "trained_packed_sign_masks_verified_independently_on_cuda", "tokens": tokens,
              "groups": tokens * groups, "exact_mask_bits": tokens * channels * 3, "skipped_channels": skipped,
              "outliers_by_token": counts, "device": torch.cuda.get_device_name(),
              "peak_device_bytes": torch.cuda.max_memory_allocated(), "elapsed_seconds": time.monotonic() - start,
              "input_sha256": pins}
    with output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(result["state"], result["exact_mask_bits"], skipped, result["peak_device_bytes"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    run(parser.parse_args().output)
