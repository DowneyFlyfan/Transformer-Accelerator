"""Recompute the new-image merge map and bind it to the native whole-chip replay."""
import argparse
from collections import Counter
from hashlib import file_digest, sha256
import json
from pathlib import Path
import re


def digest(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def merge_origins(sign_vectors, columns, features, minimum_matches):
    origins = []
    choices = Counter()
    for position, current in enumerate(sign_vectors):
        neighbors = []
        if position >= columns:
            neighbors.append(("upper", origins[position - columns]))
        if position % columns:
            neighbors.append(("left", origins[position - 1]))
        for role, origin in neighbors:
            disagreements = (current ^ sign_vectors[origin]).bit_count()
            if features - disagreements >= minimum_matches:
                origins.append(origin)
                choices[role] += 1
                break
        else:
            origins.append(position)
            choices["new"] += 1
    return origins, choices


def check_map(observed, expected):
    for position, (a, b) in enumerate(zip(observed, expected, strict=True)):
        if a != b:
            raise ValueError(f"Token {position} chooses origin {a}, expected {b}")


def verified_prefix(log, candidate_stage, fixture):
    prefix = []
    group_zero = "UNSEEDED_PROJECTION_GROUP_PASS group=0 slots=409"
    with log.open("rb") as stream:
        for line in stream:
            if not line.endswith(b"\n"):
                break
            prefix.append(line)
            if line.rstrip() == group_zero.encode():
                break
    assert prefix and prefix[-1].rstrip() == group_zero.encode()
    observed = b"".join(prefix)
    text = observed.decode()
    assert re.search(r"(?m)^\s*-defparam tri_oracle_attention430_tb\.INTEGRATE=1$", text)
    assert f"file: {candidate_stage / 'attention_bundle.sv'}\n" in text
    assert f"\t+FIXTURE={fixture}\n" in text
    assert re.search(r"(?m)^LOCAL_MERGE_LAYER_PROGRESS time=\S+ ns maps=576 rows=0$", text)
    assert not re.search(r"\*F,|\*E,|COMPOSE430_MAP index=|\$fatal", text)
    return observed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate_stage", type=Path, help="Candidate's attention replay directory")
    parser.add_argument("snapshot", type=Path, help="New file for the completed map-phase log prefix")
    args = parser.parse_args()
    assert __debug__ and not Path("/.dockerenv").exists()
    root = Path.cwd()
    stage = args.candidate_stage.resolve()
    preparation_path = stage / "prepared.json"
    preparation = json.loads(preparation_path.read_text())
    fixture = Path(preparation["fixture"])
    candidate = stage.parent / "native/cold.v"
    bundle = stage / "attention_bundle.sv"
    testbench = stage / "attention_tb.sv"
    signs = fixture / "signs.hex"
    golden = fixture / "map.hex"
    for path in (candidate, bundle, testbench, signs, golden):
        assert digest(path) == preparation["evidence_sha256"][str(path.relative_to(root))]
    assert digest(candidate) == preparation["candidate_sha256"]
    includes = set(re.findall(r'(?m)^`include "([^"]+)"$', bundle.read_text()))
    assert {str(candidate), str(testbench)} <= includes

    bench = testbench.read_text()
    (threshold,) = re.findall(r"(?m)^\s*wire \[11:0\] frame_minimum_matches=(\d+);$", bench)
    assert "wire frame_new_image=1;" in bench
    check = (
        r"if \(map_valid && map_ready\) begin\s+"
        r"if \(map_index!==10'\(maps\) \|\| map_origin!==golden\[maps\] \|\| map_last!==\(maps==575\)\)\s+"
        r'\$fatal\(1,"COMPOSE430_MAP index=%0d",maps\);\s+maps\+\+;'
    )
    assert re.search(check, bench)
    assert re.search(r"while \(!frame_done_valid\) @\(negedge clk\);\s+"
                     r'if \(frame_done_error \|\| maps!=576\) \$fatal\(1,"COMPOSE430_FRAME_RESULT"\);', bench)
    phase = bench.index("            build_frame();")
    assert phase < bench.index("UNSEEDED_PROJECTION_GROUP_PASS")
    assert bench.index("restore_map(1);", 0, phase) < phase
    assert '$readmemh({fixture,"/signs.hex"},signs);' in bench
    assert '$readmemh({fixture,"/map.hex"},golden);' in bench

    image = [int(line, 16) for line in signs.read_text().splitlines()]
    target = [int(line, 16) for line in golden.read_text().splitlines()]
    assert len(image) == len(target) == 576 and all(0 <= value < (1 << 2048) for value in image)
    matches = int(threshold)
    assert 0 <= matches <= 2048
    origins, decisions = merge_origins(image, 24, 2048, matches)
    check_map(origins, target)
    snapshot = verified_prefix(stage / "attention/xrun.log", stage, fixture)
    with args.snapshot.open("xb") as stream:
        stream.write(snapshot)

    files = (preparation_path, candidate, bundle, testbench, signs, golden, Path(__file__).resolve())
    print(json.dumps({
        "state": "native_completed_token_frame_matches_independent_sign_reference",
        "candidate_sha256": preparation["candidate_sha256"],
        "tokens": len(origins),
        "columns": 24,
        "sign_bits_per_token": 2048,
        "minimum_matches": matches,
        "decisions": decisions,
        "observed_frame": "new-image trained sign inputs",
        "log_prefix_sha256": sha256(snapshot).hexdigest(),
        "scope": (
            "The exact candidate replay checked each accepted position, origin and final marker against "
            "the fixture. This host tool regenerated all expected origins from the trained signs. "
            "The frozen prefix ends after the first projection group, which follows completed map generation. "
            "Whole-chip attention and trained model accuracy remain separate."
        ),
        "evidence_sha256": {str(path.relative_to(root)): digest(path) for path in files},
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
