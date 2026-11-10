"""Compare native proportional softmax outputs with fixed-point and real references."""

from collections import Counter
import gzip
import json
import math
from pathlib import Path
import random
import re
import subprocess
import tempfile

from run_tri_oracle_batch396_masks import GIB, check_memory, sha256
from tri_oracle_process_guard import terminate_process_group


ROOT = Path(__file__).resolve().parents[1]
TOP = "tri_oracle_proportional_softmax_tb"
EXP2 = [round((1 << 20) * math.exp2(-index / 64)) for index in range(65)]
FULL_SCALE = 65535


def fixed_probabilities(scores, sizes):
    """Decode the local fixed-point convention with unbounded scalar arithmetic."""
    if not any(sizes):
        return [0] * len(scores)
    maximum = max(score for score, size in zip(scores, sizes, strict=True) if size)
    weights = []
    for score, size in zip(scores, sizes, strict=True):
        if size == 0:
            weights.append(0)
            continue
        power = ((maximum-score)*5909 + 2048) // 4096
        whole, fraction = divmod(power, 256)
        index, remainder = divmod(fraction, 4)
        high, low = EXP2[index:index+2]
        interpolated = (high*(4-remainder) + low*remainder + 1) // 4
        weights.append((size * interpolated) // (1 << whole))
    reciprocal = (1 << 48) // sum(weights)
    return [(weight * reciprocal * FULL_SCALE + (1 << 47)) // (1 << 48) for weight in weights]


def real_probabilities(scores, sizes):
    """Evaluate the published size-weighted softmax equation for signed Q8 scores."""
    if not any(sizes):
        return [0.0] * len(scores)
    maximum = max(score for score, size in zip(scores, sizes, strict=True) if size)
    weights = [size * math.exp((score-maximum)/256) for score, size in zip(scores, sizes, strict=True)]
    denominator = math.fsum(weights)
    return [weight/denominator for weight in weights]


def directed_rows():
    random_source = random.Random(425)
    rows = [
        ([0, 0, 32767], [1, 3, 0]),
        ([0] + [-3584] * 1023, [1] + [1023] * 1023),
        ([0, 0], [3, 3]),
        ([32767, -32768, -1], [0, 0, 0]),
        ([-32768], [1023]),
        ([-32768, 32767, 32766, -32767], [1023, 1, 1, 0]),
        ([0] * 1024, [1023] * 1024),
        (list(range(-255, 1)), [1 + index % 13 for index in range(256)]),
    ]
    for length in (2, 17, 31, 64, 255, 1024):
        rows.append(([random_source.randrange(-2048, 2049) for _ in range(length)],
                     [random_source.randrange(1, 577) if index % 7 else 0 for index in range(length)]))
    return rows


def run_native(command, folder):
    log = folder / "console.log"
    with log.open("x") as stream:
        process = subprocess.Popen(command, cwd=folder, stdin=subprocess.DEVNULL, stdout=stream,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        try:
            status = process.wait(timeout=90)
        finally:
            terminate_process_group(process)
    return status, log.read_text()


def main():
    check_memory(12*GIB)
    trace_path = ROOT / ".cache/model_reference/batch425/rows.json"
    trace_raw = trace_path.read_text()
    trace = json.loads(trace_raw)
    source = ROOT / "verilog/tri_oracle_proportional_softmax.sv"
    bench = ROOT / "verilog" / f"{TOP}.sv"
    inputs = trace["source_sha256"].copy()
    for path in (trace_path, source, bench, Path(__file__), ROOT/"syn/tri_oracle_process_guard.py"):
        inputs[str(path)] = sha256(path)
    assert all(sha256(Path(path)) == digest for path, digest in inputs.items())
    output = ROOT / "records/batch425_proportional_softmax_result.json"
    archive = ROOT / "records/batch425_proportional_softmax_evidence.json.gz"
    assert not output.exists() and not archive.exists()
    directed = directed_rows()
    assert fixed_probabilities(*directed[0]) == [16384, 49151, 0]
    assert fixed_probabilities(*directed[1])[0] == 35023
    assert fixed_probabilities(*directed[2]) == [32767, 32767]
    assert fixed_probabilities(*directed[3]) == [0, 0, 0]
    assert fixed_probabilities(*directed[4]) == [65535]

    trained = [(row["scores"], row["sizes"]) for row in trace["rows"]]
    rows = directed + trained
    errors = []
    expected_stalls = 0
    for row_index, (scores, sizes) in enumerate(rows):
        assert len(scores) == len(sizes) and 1 <= len(scores) <= 1024
        assert all(-32768 <= score < 32768 for score in scores)
        assert all(0 <= size <= 1023 for size in sizes)
        fixed = fixed_probabilities(scores, sizes)
        real = real_probabilities(scores, sizes)
        absolute = [abs(code/FULL_SCALE - probability) for code, probability in zip(fixed, real, strict=True)]
        assert max(absolute) <= 0.001, (row_index, max(absolute))
        assert abs(sum(fixed) - (FULL_SCALE if any(sizes) else 0)) <= len(scores)
        assert all(code == 0 for code, size in zip(fixed, sizes, strict=True) if not size)
        expected_stalls += 3 * sum(key == len(scores)-1 or key % 23 == 0 for key in range(len(scores)))
        errors.append(max(absolute))

    expected_words = sum(len(scores) for scores, _ in rows)
    marker = f"SOFTMAX_PASS rows={len(rows)} words={expected_words} stalls={expected_stalls}"
    logs = {}
    changes = {
        "unit_sizes": ("interpolated * read_data[25:16]", "30'(interpolated)", 0, 32768),
        "masked_maximum": ("in_size != 0 && in_score > maximum", "in_score > maximum", 0, 0),
        "early_exponent_truncation": ("fractional_weight >> log_delta[16:8]",
                                      "(30'(interpolated) >> log_delta[16:8]) * read_data[25:16]", 1, 65535),
    }

    with tempfile.TemporaryDirectory(dir=ROOT/".cache", prefix="batch425_native_") as folder:
        work = Path(folder)
        fixture = work / "vectors.txt"
        with fixture.open("x") as stream:
            for scores, sizes in rows:
                stream.write(f"{len(scores)}\n")
                probabilities = fixed_probabilities(scores, sizes)
                for score, size, probability in zip(scores, sizes, probabilities, strict=True):
                    stream.write(f"{score & 65535:04x} {size} {probability}\n")
        fixture_digest = sha256(fixture)
        lint = subprocess.run(["verilator", "--lint-only", "-Wall", "--top-module", source.stem, str(source)],
                              cwd=work, capture_output=True, text=True, timeout=30, check=True)
        logs["verilator"] = lint.stdout + lint.stderr
        for name, change in [("xcelium", None), *changes.items()]:
            run = work/name
            run.mkdir()
            selected = source
            if change is not None:
                before, after, _, _ = change
                selected = run/source.name
                text = source.read_text()
                assert text.count(before) == 1
                selected.write_text(text.replace(before, after))
            command = ["/opt/cadence/bin/xrun", "-64bit", "-sv", "-xmerror", "RECOME", "-top", TOP,
                       str(selected), str(bench), f"+FIXTURE={fixture}"]
            status, log = run_native(command, run)
            logs[name] = log
            if change is None:
                assert status == 0 and log.splitlines().count(marker) == 1, log[-3000:]
                assert not re.search(r"\*(?:E|F),", log), log[-3000:]
            else:
                row, observed = change[2:]
                expected = fixed_probabilities(*rows[row])[0]
                expected_failure = f"SOFTMAX_MISMATCH row={row} key=0 observed={observed} expected={expected} last=0"
                assert status != 0 and log.count(expected_failure) == 1 and marker not in log, log[-3000:]
        executable = work/"iverilog.vvp"
        compile_result = subprocess.run(["iverilog", "-g2012", "-s", TOP, "-o", str(executable), str(source), str(bench)],
                                        cwd=work, capture_output=True, text=True, timeout=30, check=True)
        simulation = subprocess.run(["vvp", str(executable), f"+FIXTURE={fixture}"],
                                    cwd=work, capture_output=True, text=True, timeout=90, check=True)
        assert simulation.stdout.splitlines().count(marker) == 1, simulation.stdout
        logs["iverilog"] = compile_result.stderr + simulation.stdout + simulation.stderr
        vectors = fixture.read_text()

    assert not work.exists() and all(sha256(Path(path)) == digest for path, digest in inputs.items())
    evidence = dict(logs=logs, vectors=vectors, trained_trace=trace_raw)
    with archive.open("xb") as stream:
        stream.write(gzip.compress(json.dumps(evidence, sort_keys=True).encode(), mtime=0))
    assert json.loads(gzip.decompress(archive.read_bytes())) == evidence
    categories = Counter(("prefill" if row["prefill"] else "decode") +
                         ("_streaming" if row["streaming"] else "_retrieval") for row in trace["rows"])
    report = dict(state="trained_proportional_softmax_functionally_verified", question=trace["question"],
                  layers=sorted({row["layer"] for row in trace["rows"]}), trained_rows=len(trained),
                  trained_keys=sum(len(scores) for scores, _ in trained), directed_rows=len(directed),
                  comparisons_per_simulator=expected_words, stall_cycles_per_simulator=expected_stalls,
                  max_absolute_probability_error_trained=max(errors[len(directed):]),
                  max_absolute_probability_error_all=max(errors), trained_categories=categories,
                  simulation_marker=marker, rejected_counterfactuals=list(changes), fixture_sha256=fixture_digest,
                  inputs_sha256=inputs, native_evidence_sha256=sha256(archive),
                  integrated_in_attention_datapath=False, paper_results_matched=False)
    with output.open("x") as stream:
        stream.write(json.dumps(report, indent=2)+"\n")
    print("BATCH425_VERIFIED", marker, f"trained_max_abs_error={report['max_absolute_probability_error_trained']:.9f}")


if __name__ == "__main__":
    main()
