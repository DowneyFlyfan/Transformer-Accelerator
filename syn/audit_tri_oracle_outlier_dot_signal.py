"""Measure the outlier-only dot-product signal on two mapped replay fixtures."""

from array import array
from ctypes import CDLL, POINTER, c_int, c_int8, c_int32
import json
import math
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from audit_tri_oracle_predictor_parity import CHANNELS, HIDDEN, dot, integers, margins, weight_bytes
from check_tri_oracle_paper300_gate import PAPER_RELATIVE, PAPER_SHA256, sha
from tri_oracle_model_reference import requantize, silu_code


PRIOR = Path("records/tri_oracle_predictor_parity.json")
TARGET = Path("records/wac_channel_packing_bound_result.json")


def agreement(scores, exact):
    """Pearson correlation and strict same-sign counts on one token's channels."""
    count = len(scores)
    assert len(exact) == count
    cross = count * sum(x * y for x, y in zip(scores, exact, strict=True)) - sum(scores) * sum(exact)
    variances = [(count * sum(x * x for x in values) - sum(values) ** 2) for values in (scores, exact)]
    correlation = cross / math.sqrt(math.prod(variances)) if all(variances) else None
    nonzero = sum(value != 0 for value in exact)
    aligned = sum(x * y > 0 for x, y in zip(scores, exact, strict=True))
    return dict(correlation=correlation, exact_nonzero=nonzero, same_sign=aligned)


def optimal_zero_count(distances, zeros, budget):
    """Count zeros at a fixed skip budget, using the best possible tie break."""
    buckets = {}
    for score, zero in zip(distances, zeros, strict=True):
        counts = buckets.setdefault(score, [0, 0])
        counts[0] += 1
        counts[1] += zero
    assert 0 <= budget <= len(zeros)
    selected = 0
    for candidates, true_zeros in (buckets[score] for score in sorted(buckets)):
        take = min(budget, candidates)
        selected += min(take, true_zeros)
        budget -= take
        if not budget:
            break
    return selected


def signed_support(norm, activation):
    indices = [index for index, value in enumerate(norm) if abs(value) > 768]
    partial = array("b", [0]) * HIDDEN
    for index in indices:
        partial[index] = activation[index]
    return indices, partial


def weighted_sign_scores(weights, activation, indices):
    """Retain activation magnitude at selected positions, using only weight signs."""
    return [sum(activation[index] * (1 if weights[offset + index] < 128 else -1)
                for index in indices) for offset in range(0, len(weights), HIDDEN)]


def measure(function, files, norms, baseline, percentage):
    tokens = len(baseline["tokens"])
    activations = array("b", integers(files["activation"], 8, tokens * HIDDEN))
    weights = {branch: weight_bytes(files[branch]) for branch in ("gate", "up")}
    shifts = integers(files["shifts"], 8, tokens * 3)
    assert all(0 <= shift <= 63 for shift in shifts)
    full = {branch: dot(function, activations, matrix, tokens, CHANNELS, HIDDEN)
            for branch, matrix in weights.items()}
    budget = (percentage * CHANNELS + 99) // 100
    output = []
    for token, prior in enumerate(baseline["tokens"]):
        start = token * HIDDEN
        norm = norms[start:start + HIDDEN]
        activation = activations[start:start + HIDDEN]
        indices, partial = signed_support(norm, activation)
        assert len(indices) == prior["outliers"]
        first = token * CHANNELS
        exact = {branch: full[branch][first:first + CHANNELS] for branch in weights}
        signed = {branch: margins(norm, matrix) for branch, matrix in weights.items()}
        branches, partial_scores, weighted_scores = {}, {}, {}
        for branch, matrix in weights.items():
            outlier = dot(function, partial, matrix, 1, CHANNELS, HIDDEN)
            # Independent scalar evaluation on the same sparse inputs.
            for channel, value in enumerate(outlier):
                terms = (matrix[channel * HIDDEN + index] for index in indices)
                assert value == sum(activation[index] * (byte if byte < 128 else byte - 256)
                                    for index, byte in zip(indices, terms, strict=True))
            direct = exact[branch]
            signal = sum(value * value for value in direct)
            assert signal > 0
            residual = sum((a - b) ** 2 for a, b in zip(direct, outlier, strict=True))
            partial_scores[branch] = outlier
            weighted_scores[branch] = weighted_sign_scores(matrix, activation, indices)
            branches[branch] = {"outlier_only": agreement(outlier, direct), "sign_only": agreement(signed[branch], direct),
                                "weighted_sign_only": agreement(weighted_scores[branch], direct),
                                "outlier_dot_relative_squared_error": residual / signal}
        gshift, ushift, dshift = shifts[token * 3:token * 3 + 3]
        dense = [requantize(requantize(silu_code(requantize(g, gshift, 16)) * requantize(u, ushift, 16), 8, 16), dshift, 8)
                 for g, u in zip(exact["gate"], exact["up"], strict=True)]
        zeros = [value == 0 for value in dense]
        assert sum(zeros) == prior["exact_zero_down_inputs"]
        # Optimistic ranking diagnostic. Keep the gate and up ordering the
        # current rule uses, then rank favored channels by the up distance.
        def nonzero_in_ranking(scores):
            rank = [(g > 0, abs(u)) for g, u in zip(scores["gate"], scores["up"], strict=True)]
            return budget - optimal_zero_count(rank, zeros, budget)

        output.append(dict(position=prior["position"], outliers=len(indices),
                           selected_activation_square_fraction=sum(x * x for x in partial) / sum(x * x for x in activation),
                           exact_zero_channels=sum(zeros), minimum_nonzero_channels_at_skip_budget=budget - min(budget, sum(zeros)),
                           nonzero_channels_in_sign_ranking=nonzero_in_ranking(signed),
                           nonzero_channels_in_weighted_sign_ranking=nonzero_in_ranking(weighted_scores),
                           nonzero_channels_in_outlier_only_ranking=nonzero_in_ranking(partial_scores), **branches))
    return {"skip_budget_per_token": budget, "tokens": output}


def run():
    assert __debug__ and Path("/.dockerenv").is_file()
    prior = json.loads(PRIOR.read_text())
    pins = {str(PRIOR): sha(PRIOR), str(TARGET): sha(TARGET)}

    def bind(relative):
        path = Path(relative)
        assert sha(path) == prior["evidence_sha256"][str(path)], path
        pins[str(path)] = prior["evidence_sha256"][str(path)]
        return path

    bind("syn/tri_oracle_model_reference.py")
    bind("syn/audit_tri_oracle_predictor_parity.py")
    assert sha(bind(PAPER_RELATIVE)) == PAPER_SHA256
    base = Path(".cache/model_reference/batch389")
    learned = Path(".cache/model_reference/batch403")
    layer0 = {name: bind(base / f"{name}.hex") for name in ("gate", "up", "shifts")}
    layer0["activation"] = bind(learned / "activation.hex")
    norms0 = integers(bind(learned / "norm.hex"), 16, len(prior["layer_zero"]["tokens"]) * HIDDEN)
    layer10_packet, = (bind(name) for name in prior["evidence_sha256"] if name.endswith("/layer10_normalization/norm_expected.hex"))
    layer10 = {"activation": bind(layer10_packet.parent / "activation.hex")}
    for name in ("gate", "up", "shifts"):
        layer10[name] = bind(layer10_packet.parent.with_name("layer10_mapped_feedforward") / "fixture" / f"{name}.hex")
    norms10 = []
    for word in layer10_packet.read_text().splitlines():
        packet = int(word, 16)
        for lane in range(8):
            code = (packet >> (72 + 16 * lane)) & 65535
            norms10.append(code - 65536 if code >= 32768 else code)
            assert (abs(norms10[-1]) > 768) == bool(packet & (1 << (64 + lane)))
    assert len(norms10) == len(prior["layer_ten"]["tokens"]) * HIDDEN
    paper = json.loads(TARGET.read_text())["paper_figure_31_6_5"]
    percentage = paper["predicted_channel_reduction_percent"]["VQAv2"]
    c_source = bind("syn/tri_oracle_fixture_dot.c")
    verifier = Path(__file__).relative_to(Path.cwd())
    pins[str(verifier)] = sha(verifier)
    with TemporaryDirectory(dir=".cache", prefix="outlier_dot_signal_") as scratch:
        library = Path(scratch).resolve() / "fixture_dot.so"
        subprocess.run(["gcc", "-O3", "-Wall", "-Wextra", "-Werror", "-fopenmp", "-fPIC", "-shared",
                        str(c_source), "-o", str(library)], check=True)
        function = CDLL(str(library)).tri_oracle_fixture_dot
        function.argtypes = (POINTER(c_int8), POINTER(c_int8), POINTER(c_int32), c_int, c_int, c_int)
        function.restype = None
        result = {"layer_zero": measure(function, layer0, norms0, prior["layer_zero"], percentage),
                  "layer_ten": measure(function, layer10, norms10, prior["layer_ten"], percentage)}
    assert all(sha(path) == checksum for path, checksum in pins.items())
    return dict(state="trained_outlier_dot_signal_measured", paper_figure="31.6.5", paper_sha256=PAPER_SHA256,
                paper_skip_percent=percentage, **result, evidence_sha256=pins,
                scope="Two mapped replay fixtures. Exact zeros are defined by the local fixed-point format. "
                      "Sign ranking uses an optimistic tie break and is diagnostic only.")


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True))
