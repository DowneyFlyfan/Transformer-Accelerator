"""Compare sign predictions with exact fixed-point zeros on trained fixtures."""

from array import array
from ctypes import CDLL, POINTER, c_int, c_int8, c_int32
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from check_tri_oracle_paper300_gate import PAPER_RELATIVE, PAPER_SHA256, sha
from tri_oracle_model_reference import requantize, silu_code


ROOT = Path.cwd()
RECORDS = ROOT / "records"
CACHE = ROOT / ".cache"
HIDDEN, CHANNELS = 2048, 5632


def integers(path, bits, count):
    values = [int(word, 16) for word in path.read_text().split()]
    assert len(values) == count and all(0 <= value < (1 << bits) for value in values), path
    midpoint = 1 << (bits - 1)
    return [value - 2 * midpoint if value >= midpoint else value for value in values]


def flags(path, count):
    values = integers(path, 8, count)
    assert set(values) <= {0, 1}
    return values


def weight_bytes(path):
    raw = path.read_bytes()
    assert len(raw) == 3 * HIDDEN * CHANNELS and raw.count(b"\n") == HIDDEN * CHANNELS, path
    return bytes.fromhex(raw.decode("ascii"))


def dot(function, left, right, rows, channels, terms):
    assert len(left) == rows * terms and len(right) == channels * terms
    product = (c_int32 * (rows * channels))()
    function((c_int8 * len(left)).from_buffer_copy(left), (c_int8 * len(right)).from_buffer_copy(right),
             product, rows, channels, terms)
    return list(product)


def margins(norm, weights):
    """The exact XNOR sum is 2 × the matching outlier signs minus the count."""
    support = [(index, value < 0) for index, value in enumerate(norm) if abs(value) > 768]
    return [2 * sum((weights[offset + index] >= 128) == negative for index, negative in support) - len(support)
            for offset in range(0, len(weights), HIDDEN)]


def active_groups(values, width):
    """Count eight-position packed groups used by at least one token."""
    assert len(values) % width == 0 and width % 8 == 0
    return sum(any(any(values[row + start:row + start + 8]) for row in range(0, len(values), width))
               for start in range(0, width, 8))


def quantify(function, files, normalized, positions):
    tokens = len(positions)
    activations = array("b", integers(files["activation"], 8, tokens * HIDDEN))
    gate, up, down = (weight_bytes(files[name]) for name in ("gate", "up", "down"))
    shifts = integers(files["shifts"], 8, tokens * 3)
    assert all(0 <= shift <= 63 for shift in shifts)
    keep = flags(files["keep"], tokens * CHANNELS)
    intermediate = integers(files["intermediate"], 8, tokens * CHANNELS)
    expected = integers(files["expected"], 32, tokens * HIDDEN)
    gates = dot(function, activations, gate, tokens, CHANNELS, HIDDEN)
    ups = dot(function, activations, up, tokens, CHANNELS, HIDDEN)
    dense = array("b")
    adjusted_inputs = array("b")
    adjusted_keep = []
    report = []
    for token, position in enumerate(positions):
        first, last = token * CHANNELS, (token + 1) * CHANNELS
        gate_shift, up_shift, down_shift = shifts[3 * token:3 * token + 3]
        norm = normalized[token * HIDDEN:(token + 1) * HIDDEN]
        count = sum(abs(value) > 768 for value in norm)
        gate_margin, up_margin = (margins(norm, weights) for weights in (gate, up))
        assert all(abs(score) <= count and score % 2 == count % 2 for score in gate_margin + up_margin)
        skip = [count > 0 and gs <= 0 and us == 0 for gs, us in zip(gate_margin, up_margin, strict=True)]
        assert [not value for value in skip] == keep[first:last], position
        dense_row = [requantize(requantize(silu_code(requantize(g, gate_shift, 16)) *
                                         requantize(u, up_shift, 16), 8, 16), down_shift, 8)
                     for g, u in zip(gates[first:last], ups[first:last], strict=True)]
        assert [0 if pruned else value for value, pruned in zip(dense_row, skip, strict=True)] == intermediate[first:last]
        dense.extend(dense_row)
        parity_added = [bool(count % 2) and g <= 0 and abs(u) == 1
                        for g, u in zip(gate_margin, up_margin, strict=True)]
        adjusted_inputs.extend(0 if added else baseline for added, baseline in
                               zip(parity_added, intermediate[first:last], strict=True))
        adjusted_keep.extend(retained and not added for retained, added in
                             zip(keep[first:last], parity_added, strict=True))
        report.append(dict(position=position, outliers=count, baseline_skips=sum(skip),
                           baseline_skips_of_nonzero=sum(pruned and value != 0 for pruned, value in zip(skip, dense_row)),
                           exact_zero_down_inputs=dense_row.count(0), parity_adjusted_added_skips=sum(parity_added),
                           parity_adjusted_added_skips_of_nonzero=sum(pruned and value != 0
                               for pruned, value in zip(parity_added, dense_row))))
    assert dot(function, array("b", intermediate), down, tokens, HIDDEN, CHANNELS) == expected
    dense_output = dot(function, dense, down, tokens, HIDDEN, CHANNELS)
    adjusted_output = dot(function, adjusted_inputs, down, tokens, HIDDEN, CHANNELS)
    activation_groups = active_groups(activations, HIDDEN)
    removed_gate_up_beats = 2 * activation_groups * (active_groups(keep, CHANNELS) -
                                                      active_groups(adjusted_keep, CHANNELS))
    removed_down_beats = (HIDDEN // 8) * (active_groups(intermediate, CHANNELS) -
                                          active_groups(adjusted_inputs, CHANNELS))
    return {"tokens": report, "baseline_outputs_reproduced": len(expected),
            "dense_outputs_different_from_pruned": sum(a != b for a, b in zip(dense_output, expected, strict=True)),
            "parity_adjusted_outputs_different_from_pruned":
                sum(a != b for a, b in zip(adjusted_output, expected, strict=True)),
            "parity_adjusted_projected_weight_beats_avoided": {"gate_up": removed_gate_up_beats,
                                                               "down": removed_down_beats}}


def run():
    assert __debug__ and Path("/.dockerenv").is_file()
    evidence = {}

    def bind(path, digest=None):
        path = ROOT / path
        observed = sha(path)
        assert digest is None or digest == observed, path
        assert evidence.setdefault(str(path.relative_to(ROOT)), observed) == observed
        return path

    def read(path, digest=None):
        return json.loads(bind(path, digest).read_text())

    def source(directory, name, hashes):
        path = directory / f"{name}.hex"
        return bind(path, hashes[str(path)])

    bind(PAPER_RELATIVE, PAPER_SHA256)
    base = read(RECORDS / "batch389_fixture_preparation.json")
    learned = read(RECORDS / "batch403_activation_precision.json")
    intermediate = read(RECORDS / "batch407_learned_fixture.json")
    control = read(RECORDS / "batch396_mask_fixture.json")
    assert base["original_layer"] == intermediate["original_checkpoint_layer"] == 0
    assert learned["predictor_outlier_and_sign_drift"] == 0
    model = ROOT / "syn/tri_oracle_model_reference.py"
    bind(model, base["source_sha256"][str(model)])
    fixture = {name: source(Path(base["fixture"]), name, base["files_sha256"])
               for name in ("gate", "up", "down", "shifts", "keep")}
    fixture.update({name: source(Path(learned["fixture"]), name, learned["files_sha256"])
                    for name in ("activation", "expected", "norm")})
    fixture["intermediate"] = source(Path(intermediate["fixture"]), "intermediate", intermediate["files_sha256"])
    counts = source(Path(control["fixture"]), "outlier_counts", control["files_sha256"])

    published = read(RECORDS / "tri_oracle_layer10_mapped_feedforward.json")
    native_path, = (Path(name) for name in published["evidence_sha256"] if name.endswith("layer10_mapped_feedforward/receipt.json"))
    native = read(native_path, published["evidence_sha256"][str(native_path)])
    assert native["candidate_sha256"] == published["candidate_sha256"] and native["native"]["native_exit_status"] == 0
    plan_path = native_path.with_name("prepared.json")
    plan = read(plan_path, native["input_sha256"][str(ROOT / plan_path)])
    layer10 = ROOT / native_path.parent
    paths = dict(plan["input_sha256"])
    new = {name: source(layer10 / "fixture", name, paths) for name in ("gate", "up", "down", "keep", "intermediate", "shifts")}
    norms = layer10.with_name("layer10_normalization")
    new.update({name: source(norms, name, paths) for name in ("activation", "expected")})
    packets = source(norms, "norm_expected", paths).read_text().splitlines()
    assert len(packets) == len(native["positions"]) * HIDDEN // 8
    normalized = []
    for word in packets:
        packet = int(word, 16)
        for lane in range(8):
            value = ((packet >> (72 + 16 * lane)) & 65535)
            normalized.append(value - 65536 if value >= 32768 else value)
            assert (abs(normalized[-1]) > 768) == bool(packet & (1 << (64 + lane)))

    c_source = bind("syn/tri_oracle_fixture_dot.c")
    bind(Path(__file__).resolve())
    with TemporaryDirectory(dir=CACHE, prefix="predictor_parity_") as scratch:
        library = Path(scratch) / "fixture_dot.so"
        subprocess.run(["gcc", "-O3", "-Wall", "-Wextra", "-Werror", "-fopenmp", "-fPIC", "-shared",
                        str(c_source), "-o", str(library)], check=True)
        function = CDLL(str(library)).tri_oracle_fixture_dot
        function.argtypes = (POINTER(c_int8), POINTER(c_int8), POINTER(c_int32), c_int, c_int, c_int)
        function.restype = None
        assert dot(function, array("b", [-128, 127, 1, -1]), bytes((127, 128, 2, 254)), 2, 2, 2) == [
            -32512, -510, 255, 4]
        layer0 = quantify(function, fixture, integers(fixture["norm"], 16, 16 * HIDDEN), base["original_token_positions"])
        assert [row["outliers"] for row in layer0["tokens"]] == integers(counts, 16, 16)
        assert sum(row["baseline_skips"] for row in layer0["tokens"]) == control["skipped_channels"]
        audit10 = quantify(function, new, normalized, native["positions"])
        assert audit10["baseline_outputs_reproduced"] == native["exact_feedforward_words"]
    assert all(sha(name) == digest for name, digest in evidence.items())
    return dict(state="trained_fixture_predictor_parity_and_dense_zeros_measured", paper_sha256=PAPER_SHA256,
                paper_figure="31.6.5", layer_zero=layer0, layer_ten=audit10, evidence_sha256=evidence,
                scope="Two candidate fixtures. Exact zeros are counted after computing the dense gate and up projections. "
                      "A parity-adjusted window of one for odd counts is a local diagnostic, with no hardware change or accuracy claim.")


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True))
