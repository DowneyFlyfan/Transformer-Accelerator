"""Prepare a trained streaming-head stimulus for the cold-exported chip."""

from argparse import ArgumentParser
from collections import Counter
import json
import math
from pathlib import Path

import numpy as np
import torch

from verify_tri_oracle_booth_attention_reference import ROOT, digest, probabilities

DATA = ROOT / ".cache/model_reference"
HEADS = DATA / "batch427/heads.json"
ROWS = DATA / "batch426/operands.json"
COMPACT = ROOT / "records/batch422_compact_decoder_result.json"
CAPTURE = ROOT / "records/batch427_attention_layer_result.json"
PLACEMENT = ROOT / "records/tri_oracle_corrected_booth_buffered_placement_roundtrip.json"
IMAGE_TOKENS = 576
SLOTS = 409
LAYER = 10
HEAD = 2
OUTPUT_POSITIONS = (316, 607)


def load(path):
    return json.loads(path.read_text())


def signed_vectors(words, device):
    """Decode packed trace words [token] to signed bytes [token, feature]."""
    codes = np.frombuffer(b"".join(bytes.fromhex(word)[::-1] for word in words), dtype=np.int8)
    return torch.as_tensor(codes.reshape(len(words), 64).copy(), device=device)


def recompute(head, rows, mapping, image_start, original_positions):
    assert torch.cuda.is_available() and torch.cuda.mem_get_info()[0] > 2 * 2**30
    device = torch.device("cuda:0")
    torch.cuda.reset_peak_memory_stats(device)
    # Archived integer operands [query token starting at 96, feature] and [retained key token, feature].
    query_codes = signed_vectors(head["queries"], device).to(torch.float64)
    key_codes = signed_vectors(head["keys"], device).to(torch.float64)
    # Exact dot matrix [query token starting at 96, retained key token].
    dots = (query_codes @ key_codes.T).to(torch.int64)
    # Index tensors constructed from the prompt and key extents.
    query = torch.arange(96, len(original_positions), device=device)[:, None]  # [query token, singleton]
    key = torch.arange(len(original_positions), device=device)[None, :]       # [singleton, key token]
    tile_start = query // 32 * 32                                             # [query token, singleton]
    cutoff = dots[:, :32].amax(dim=1, keepdim=True) - head["alpha"]            # [query token, singleton]
    above = dots > cutoff                                                     # [query token, key token]
    inner = int((above & (key >= tile_start - 64) & (key < tile_start - 32)).sum())
    recent = int((above & (key >= tile_start) & (key <= query)).sum())
    assert (inner, recent, recent > 8 * inner) == (head["inner"], head["recent"], head["streaming"])
    assert head["streaming"]

    # Reference exponential samples [fractional table index].
    table = torch.tensor([round((1 << 20) * math.exp2(-index / 64)) for index in range(65)],
                         device=device)
    # Packed outputs hold feature zero in the least significant word.
    packed = []
    for row in rows:
        position = row["query_position"]
        rank = original_positions.index(position)
        visible = [*range(32), *range(rank - 31, rank + 1)]
        assert row["selected"] == visible and row["keys_hex"] == head["keys"]
        assert row["query_hex"] == head["queries"][rank - 96]
        # Reconstruct causal merge sizes from the original-token map.
        appeared = min(IMAGE_TOKENS, position - image_start + 1)
        retained_sizes = Counter(mapping[:appeared])
        sizes = [retained_sizes[original_positions[i] - image_start]
                 if image_start <= original_positions[i] < image_start + IMAGE_TOKENS else 1 for i in visible]
        assert sizes == [row["sizes"][i] for i in visible]
        # Index and gather [visible key token]. Values retain [visible key token, feature].
        selected_dots = dots[rank - 96, visible]
        assert selected_dots.tolist() == row["dots"]
        score = (selected_dots.double() * math.ldexp(1.0, row["shift"])).round().clamp(-32768, 32767).long()
        weights = probabilities(score, torch.tensor(sizes, device=device), table)
        values = signed_vectors([row["values_hex"][i] for i in visible], device).long()
        # Accumulate over visible keys to form one value per output feature [feature].
        result = (weights[:, None] * values).sum(dim=0).tolist()
        assert result == row["result"] and result != row["unit_size_result"]
        assert all(-(1 << 31) <= value < 1 << 31 for value in result)
        packed.append((rank, position, visible, "".join(f"{value & 0xffffffff:08x}" for value in reversed(result))))
    return packed, torch.cuda.max_memory_allocated(device)


def prepare(output):
    capture = load(CAPTURE)
    for path in (HEADS, ROWS, COMPACT):
        assert digest(path) == capture["inputs_sha256"][str(path)], path
    heads, trace, compact = (load(path) for path in (HEADS, ROWS, COMPACT))
    assert compact["local_ratio"] == [8, 1] and compact["minimum_matching_signs"] == 1536
    (head,) = [item for item in heads["heads"] if (item["layer"], item["head"]) == (LAYER, HEAD)]
    rows = [row for row in trace["cases"] if (row["layer"], row["head"]) == (LAYER, HEAD)
            and row["query_position"] in OUTPUT_POSITIONS]
    assert [row["query_position"] for row in rows] == list(OUTPUT_POSITIONS)
    image_start = rows[0]["image_start"]
    maps = trace["maps"][:LAYER + 1]
    mapping = maps[-1]
    roots = [index for index, survivor in enumerate(mapping) if index == survivor]
    assert len(roots) == len(set(mapping))
    positions = [*range(image_start), *(image_start + index for index in roots),
                 *range(image_start + IMAGE_TOKENS, OUTPUT_POSITIONS[-1] + 1)]
    assert len(positions) == len(head["keys"]) == 374
    packed, peak = recompute(head, rows, mapping, image_start, positions)

    folder = Path(compact["native_fixture"])
    mode = compact["native_fixture_modes"].index("compact_and_streaming")
    signs_file, map_file = (folder / f"{name}_{mode}.hex" for name in ("signs", "map"))
    for path in (signs_file, map_file):
        assert digest(path) == compact["native_fixture_sha256"][str(path)], path
    signals = signs_file.read_text().splitlines()
    archived_map = map_file.read_text().splitlines()
    dense_signs, sign_counts = [], []
    for layer, current in enumerate(maps):
        start = layer * IMAGE_TOKENS
        assert [int(word, 16) for word in archived_map[start:start + IMAGE_TOKENS]] == current
        source = range(IMAGE_TOKENS) if layer == 0 else [
            index for index, survivor in enumerate(maps[layer - 1]) if survivor == index]
        active_signs = [signals[start + index] for index in source]
        sign_counts.append(len(active_signs))
        dense_signs.extend(active_signs + ["0" * 512] * (IMAGE_TOKENS - len(active_signs)))
    bank_words = ["0" * 128] * (SLOTS * 40)
    bank_words[96:len(positions)] = head["queries"]
    bank_words[32 * SLOTS:32 * SLOTS + len(positions)] = head["keys"]
    assert rows[0]["values_hex"] == rows[1]["values_hex"] and rows[0]["shift"] == rows[1]["shift"]
    bank_words[36 * SLOTS:36 * SLOTS + len(positions)] = rows[0]["values_hex"]

    output.mkdir()
    files = {
        "signs.hex": dense_signs,
        "map.hex": [f"{value:03x}" for layer in maps for value in layer],
        "expected.hex": bank_words,
        "value_order.hex": [f"{key:03x}" for _, _, keys, _ in packed for key in keys],
        "sign_counts.hex": [f"{count:03x}" for count in sign_counts],
        "rows.txt": [f"{image_start} {HEAD} {head['alpha']} {rows[0]['shift']} {head['inner']} "
                     f"{head['recent']} 1 {len(positions)-1}"] +
                    [f"{rank} {position} {len(keys)} {payload}" for rank, position, keys, payload in packed],
    }
    for name, lines in files.items():
        (output / name).write_text("\n".join(lines) + "\n")
    placement = load(PLACEMENT)
    cold = ROOT / Path(placement["database"]).parents[1] / "cold/cold.v"
    assert digest(cold) == placement["evidence_sha256"][str(cold.relative_to(ROOT))]
    evidence = (CAPTURE, HEADS, ROWS, COMPACT, signs_file, map_file, PLACEMENT, cold,
                *(output / name for name in files), Path(__file__).resolve())
    return dict(
        state="trained_streaming_fixture_verified_on_host_gpu",
        scope="Archived signed operands for two streaming rows and eleven live merge commands.",
        question=trace["question"], layer=LAYER, head=HEAD, retained_prefill_tokens=len(positions),
        prediction={"inner": head["inner"], "recent": head["recent"], "streaming": True},
        output_rows=[{"rank": rank, "original_position": position, "selected_keys": len(keys)}
                     for rank, position, keys, _ in packed],
        sign_vectors_per_layer=sign_counts, cold_netlist_sha256=digest(cold),
        cuda_peak_device_bytes=peak,
        evidence_sha256={str(path.relative_to(ROOT)): digest(path) for path in evidence},
    )


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    assert output.is_relative_to(ROOT / ".cache")
    print(json.dumps(prepare(output), indent=2, sort_keys=True))
