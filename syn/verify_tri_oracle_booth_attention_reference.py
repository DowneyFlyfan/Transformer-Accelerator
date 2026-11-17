"""Recompute every fixed-point attention row in the physical-port fixture on CUDA."""

from hashlib import sha256
import json
import math
from pathlib import Path

import numpy as np
import torch

from verify_tri_oracle_booth_projection_reference import ROOT, digest, unpack_hex_bytes


PHYSICAL = ROOT / ".cache/physical/whole_chip_xcelium_speed/prepared.json"
PROJECTION = ROOT / "records/tri_oracle_trained_projection_gpu_reference.json"
REFERENCE = ROOT / "records/tri_oracle_trained_attention_output_reference.json"
DATA = ROOT / ".cache/model_reference"
HEADS, KV_HEADS, FEATURES = 32, 4, 64


def probabilities(score, token_sizes, table):
    # score and token_sizes are [visible key]. table is [exponential lookup index].
    # Integer intermediate arrays below share the visible-key axis.
    power = ((score.max() - score) * 5909 + 2048) >> 12
    fraction = power & 255
    index = fraction >> 2
    remainder = fraction & 3
    interpolated = (table[index] * (4 - remainder) + table[index + 1] * remainder + 1) >> 2
    # The integral exponent is bounded before shifting to keep the operation defined.
    whole = (power >> 8).clamp_max(63)
    weights = (token_sizes * interpolated) >> whole
    assert int(weights.sum()) > 0
    mass = weights * ((1 << 48) // weights.sum())
    # Multiplying an unsigned 48-bit mass by 65535 can overflow signed 64-bit
    # arithmetic. Splitting at bit 32 keeps the exact quotient in range.
    low = (mass & 0xFFFFFFFF) * 65535 + (1 << 47)
    high = (mass >> 32) * 65535
    return (high + (low >> 32)) >> 16


def compare_rows(vectors, layer, exponents, map_words, reference_lines):
    # vectors [projection group, retained token, head feature], decoded from
    # verified signed8 outputs. layer supplies retained positions and row ranks.
    # exponents is one integer per projection group. map_words has one origin
    # index per input image token. reference_lines is the ordered wire fixture.
    device = vectors.device
    retained = len(layer["original_positions"])
    # Grouped-query indexing gives one key and value head for each eight queries.
    group = torch.arange(HEADS, device=device) // (HEADS // KV_HEADS)  # [query head]
    query = vectors[:HEADS].double()  # [query head, query token, feature]
    key = vectors[HEADS + group].double()  # [query head, key token, feature]
    # All summands are products of signed8 codes. A sum of 64 fits in 22 signed
    # bits, so this floating-point matrix multiplication returns exact integers.
    dots = torch.matmul(query, key.transpose(1, 2)).to(torch.int64)  # [query head, query token, key token]
    origins = torch.tensor(map_words, device=device)  # [original image token]
    positions = torch.tensor(layer["original_positions"], device=device)  # [retained token]
    table = torch.tensor([round((1 << 20) * math.exp2(-index / 64)) for index in range(65)],
                         device=device)  # [exponential lookup index]
    # A single visible key reaches full scale, exercising the split above.
    one = torch.zeros(1, dtype=torch.int64, device=device)  # [visible key]
    assert int(probabilities(one, torch.ones_like(one), table)[0]) == 65535
    image_start = int(next(reference_lines))
    assert image_start == layer["image_start"]
    prompt = layer["prompt_slots"]
    assert prompt + 1 == retained
    ranks = [row["rank"] for row in layer["rows"]]
    # Build the visibility masks once on GPU. Shape [prompt query token, key token].
    q_index = torch.arange(96, prompt, device=device)[:, None]  # [prompt query token, singleton key]
    k_index = torch.arange(retained, device=device)[None, :]  # [singleton query, key token]
    tile_start = (q_index // 32) * 32  # [prompt query token, singleton key]
    inner_mask = (k_index >= tile_start - 64) & (k_index < tile_start - 32)
    recent_mask = (k_index >= tile_start) & (k_index <= q_index)
    results = []
    total_reads = streaming_heads = 0
    for head in range(HEADS):
        group_id = head // (HEADS // KV_HEADS)
        shift = exponents[head] + exponents[HEADS + group_id] + 5
        alpha = 4 * 2**(8 - shift)
        assert alpha == int(alpha)
        scores = dots[head]  # [query token, key token]
        score_panel = scores[96:prompt]  # [prompt query token, key token]
        cutoff = score_panel[:, :32].amax(dim=1, keepdim=True) - int(alpha)  # [prompt query token, singleton key]
        above = score_panel > cutoff  # [prompt query token, key token]
        inner = int((above & inner_mask).sum())
        recent = int((above & recent_mask).sum())
        streaming = recent > 8 * inner
        streaming_heads += streaming
        classified = tuple(map(int, next(reference_lines).split()))
        assert classified == (head, int(alpha), shift, inner, recent, int(streaming)), classified

        # Values for this group [key token, feature], with retained-token indices.
        values = vectors[HEADS + KV_HEADS + group_id].to(torch.int64)
        for rank in ranks:
            # visible selects the causal prefix, using two fixed windows for streaming heads.
            visible = torch.arange(rank + 1, device=device)  # [visible key]
            if streaming and rank + 1 > 64:
                visible = torch.cat((visible[:32], visible[-32:]))  # [visible key]
            position = layer["original_positions"][rank]
            # A causal histogram over original image tokens gives one count per
            # possible survivor. Nonimage tokens have size one.
            appeared = max(0, position - image_start + 1)
            counts = torch.bincount(origins[:appeared], minlength=len(map_words))  # [original image token]
            image_index = positions[visible] - image_start  # [visible key]
            is_image = (image_index >= 0) & (image_index < len(map_words))  # [visible key]
            sizes = torch.where(is_image, counts[image_index.clamp(0, len(map_words) - 1)], 1)  # [visible key]
            assert bool((sizes > 0).all())
            # Multiplication by a power of two is exact. CUDA round ties to even.
            scaled = (scores[rank, visible].double() * math.ldexp(1, shift)).round()  # [visible key]
            quantized = scaled.clamp(-32768, 32767).to(torch.int64)  # [visible key]
            probability = probabilities(quantized, sizes, table)  # [visible key]
            accumulators = (probability[:, None] * values[visible]).sum(dim=0)  # [feature]
            expected_rank, expected_position, expected_reads, encoded = next(reference_lines).split()
            assert tuple(map(int, (expected_rank, expected_position, expected_reads))) == (rank, position, len(visible))
            # Device output [feature] is stored as little-endian signed32.
            host_accumulators = accumulators.cpu().numpy()  # [feature]
            words = host_accumulators.astype("<i4")  # [feature]
            assert np.array_equal(words.astype(np.int64), host_accumulators)
            assert words.tobytes() == bytes.fromhex(encoded)[::-1], (head, rank)
            total_reads += len(visible)
            results.append(words)

    assert next(reference_lines, None) is None
    # Results arrive head-major. The archived trained output is rank-major.
    ordered = np.asarray(results).reshape(HEADS, len(ranks), FEATURES).transpose(1, 0, 2)
    return ordered, streaming_heads, total_reads


def verify():
    evidence = {}

    def pin(path, expected=None):
        checksum = digest(path)
        assert expected is None or checksum == expected, path
        evidence[str(path.relative_to(ROOT))] = checksum
        return path

    projection = json.loads(pin(PROJECTION).read_text())
    reference = json.loads(pin(REFERENCE).read_text())
    physical = json.loads(pin(PHYSICAL, projection["evidence_sha256"][str(PHYSICAL.relative_to(ROOT))]).read_text())
    assert projection["state"] == "trained_projection_fixture_verified_with_independent_gpu_arithmetic"
    fixture = Path(physical["fixture"])

    def fixture_input(name):
        path = fixture / name
        return pin(path, physical["evidence_sha256"][str(path.relative_to(ROOT))])

    projection_bytes = unpack_hex_bytes(fixture_input("expected.hex"), FEATURES)
    assert sha256(projection_bytes).hexdigest() == projection["outputs_sha256"]
    # Shape [projection group, retained token, feature] from the prior GPU-verified payload.
    shape = (HEADS + 2 * KV_HEADS, projection["retained_tokens"], FEATURES)
    vectors = torch.from_numpy(np.frombuffer(projection_bytes, dtype=np.int8).reshape(shape)).to("cuda")
    layer_path = DATA / "batch430/reference.json"
    layer = json.loads(pin(layer_path, projection["evidence_sha256"][str(layer_path.relative_to(ROOT))]).read_text())
    prior_path = DATA / "batch429/reference.json"
    prior = json.loads(pin(prior_path, projection["evidence_sha256"][str(prior_path.relative_to(ROOT))]).read_text())
    map_words = [int(line, 16) for line in fixture_input("map.hex").read_text().splitlines()]
    assert len(map_words) == 576 and all(0 <= origin <= index for index, origin in enumerate(map_words))
    results, streaming, reads = compare_rows(
        vectors, layer, prior["output_exponents"], map_words,
        iter(fixture_input("rows.txt").read_text().splitlines()),
    )  # results [selected rank, query head, feature]
    archive = fixture.parent / "trained_attention_output_reference/attention_accumulators.bin"
    assert results.tobytes() == pin(archive, reference["files_sha256"][archive.name]).read_bytes()
    assert streaming == reference["streaming_heads_in_fixture"]
    assert results.size == reference["accumulator_values"] and layer["question"] == reference["question"]
    pin(Path(__file__).resolve())
    return dict(state="physical_attention_fixture_recomputed_on_host_gpu",
                device=torch.cuda.get_device_name(), peak_device_bytes=torch.cuda.max_memory_allocated(),
                attended_rows=int(results.size // FEATURES), exact_signed32_values=int(results.size),
                expected_external_value_requests=reads, streaming_heads=streaming, question=layer["question"],
                scope="One trained prompt and layer with four ranks for each of 32 query heads.",
                evidence_sha256=evidence)


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    assert torch.cuda.is_available() and torch.cuda.mem_get_info()[0] >= 1024**3
    print(json.dumps(verify(), indent=2, sort_keys=True))
