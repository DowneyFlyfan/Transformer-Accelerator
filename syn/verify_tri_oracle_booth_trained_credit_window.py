"""Compare eight and nine credits while replaying a trained weight matrix."""

import argparse
import json
from pathlib import Path
import re

from prepare_tri_oracle_booth_packet_replay import replace_once
from verify_tri_oracle_booth_response_packing import (
    BASELINE, BASE_RUN, ROOT, TERMINAL, digest, inputs,
)


PRIOR = Path("records/tri_oracle_memory_io_link.json")
CREDIT = Path("records/tri_oracle_corrected_booth_response_credit_window.json")
TOP = "compact_index_replay_tb"
FIXTURES = ("down_index.bin", "down_payload.bin", "projected.hex")
CASES = (8, 9)
DELAY = 7


def generated_bench(text):
    text = replace_once(text, "  for (genvar phase=0;phase<2;phase++) begin : transport_peer",
                        "  localparam int Window = `TRI_ORACLE_TRAINED_WINDOW;\n"
                        "  localparam int Return = `TRI_ORACLE_TRAINED_RETURN;\n"
                        "  int return_stall_cycles[2];\n"
                        "  for (genvar phase=0;phase<2;phase++) begin : transport_peer")
    for before, after in (
        ("int available=8;", "int available=Window;"),
        ("logic [3:0] delayed=0;", "logic [Return-1:0] delayed=0;"),
        ("available<=8;\n        delayed<=0;", "available<=Window;\n        delayed<=0;\n        return_stall_cycles[phase]<=0;"),
        ("int'(delayed[3])", "int'(delayed[Return-1])"),
        ("updated>8) $fatal(1,\"TRAINED_CREDIT_CONSERVATION\");",
         "updated>Window) $fatal(1,\"TRAINED_CREDIT_CONSERVATION\");\n"
         "        if (stage_valid[phase] && available==0) return_stall_cycles[phase]<=return_stall_cycles[phase]+1;"),
        ("{delayed[2:0],pad_credit[phase]}", "{delayed[Return-2:0],pad_credit[phase]}"),
        ('      $display("DUAL_GROUP_MATRIX_WRITES',
         '      $display("TRAINED_WINDOW_CHECK credits=%0d delay=%0d stalls=%0d,%0d",\n'
         '               Window,Return,return_stall_cycles[0],return_stall_cycles[1]);\n'
         '      $display("DUAL_GROUP_MATRIX_WRITES'),
    ):
        text = replace_once(text, before, after)
    return text


def setup():
    stage, cold, mapped, baseline = inputs()
    place_receiver = stage / "placed_receiver.v"
    assert place_receiver.read_bytes() == mapped
    old_bench, old_bundle = BASE_RUN / "trained_tb.sv", BASE_RUN / "trained_mapped.sv"
    model = json.loads(PRIOR.read_text())["evidence_sha256"]
    for path in (old_bench, old_bundle, BASE_RUN / "trained_mapped/console.log"):
        assert digest(path) == baseline["evidence_sha256"][str(path)]
    proof = json.loads(CREDIT.read_text())
    assert digest(cold) == proof["cold_netlist_sha256"]
    assert digest(place_receiver) == proof["evidence_sha256"][str(place_receiver)]

    folder = stage.with_name("response_credit_trained")
    bench = folder / "trained_tb.sv"
    text = old_bundle.read_text()
    before_paths = {Path(path) for path in re.findall(r'(?m)^`include "([^"]+)"$', text)}
    old_receiver = BASE_RUN / "genus/netlist.v"
    before_paths -= {old_bench, old_receiver}
    for path in before_paths:
        assert digest(path) == model[str(path.relative_to(ROOT))], path
    text = replace_once(text, str(old_receiver), str(place_receiver.resolve()))
    text = replace_once(text, str(old_bench), str(bench.resolve()))
    fixture_paths = {}
    for name in FIXTURES:
        fixture = (BASE_RUN / "trained_mapped" / name).resolve(strict=True)
        assert digest(fixture) == model[str(fixture.relative_to(ROOT))], fixture
        fixture_paths[name] = fixture
    generated = {bench: generated_bench(old_bench.read_text()), folder / "bundle.sv": text}
    evidence = {CREDIT, PRIOR, BASELINE, cold, place_receiver, old_bench, old_bundle, *before_paths, *fixture_paths.values()}
    return folder, cold, generated, fixture_paths, evidence


def prepare():
    folder, _, generated, fixture_paths, _ = setup()
    folder.mkdir()
    for path, text in generated.items():
        path.write_text(text)
    for credits in CASES:
        output = folder / f"credit{credits}"
        output.mkdir()
        for name, source in fixture_paths.items():
            (output / name).symlink_to(source)
    print(folder)


def verify():
    folder, cold, generated, fixture_paths, evidence = setup()
    for path, expected in generated.items():
        assert path.read_text() == expected
    evidence.update(generated)
    evidence.add(Path(__file__).resolve())
    historical = BASE_RUN / "trained_mapped/console.log"
    evidence.add(historical)
    selected = re.compile(r"(?m)^(?:INDEXED_DOWN_TILE|STAGED_INDEXED_DOWN_MATRIX_PASS|"
                          r"COMPACT_INDEX_MATRIX_PASS|EARLY_PAIR_SPARSE_ROWS_PASS) .+$")
    baseline = selected.findall(historical.read_text())
    assert sum(line.startswith("INDEXED_DOWN_TILE ") for line in baseline) >= 78
    results = {}
    for credits in CASES:
        output = folder / f"credit{credits}"
        for name, source in fixture_paths.items():
            assert (output / name).resolve(strict=True) == source
        log = output / "xrun.log"
        status = output / "exit_status"
        assert int(status.read_text()) == 0
        text = log.read_text()
        assert text.count(TERMINAL) == 1 and not re.search(r"\*(?:E|F|SE),", text)
        for argument in (f"-top {TOP}", str((folder / "bundle.sv").resolve()), "+FULL_MATRIX"):
            assert f"\t{argument}\n" in text, argument
        assert f"TRI_ORACLE_TRAINED_WINDOW={credits}" in text and f"TRI_ORACLE_TRAINED_RETURN={DELAY}" in text
        assert selected.findall(text) == baseline
        assert "STAGED_INDEXED_DOWN_MATRIX_PASS cases=78 exact_bytes=11534336 " in text
        assert "NATIVE_MEMORY_IO_PASS acks=16 faults=2 " in text
        assert "INDEXED_WEIGHT_MODE_PASS switched_to_raw=1" in text
        count, = re.findall(r"(?m)^DUAL_GROUP_MATRIX_WRITES writes=90112 cycles=(\d+)$", text)
        stalls, = re.findall(rf"(?m)^TRAINED_WINDOW_CHECK credits={credits} delay={DELAY} stalls=(\d+),(\d+)$", text)
        compact, full = re.search(r"(?m)^MEMORY_REQUEST_HARDWARE_FIXTURE compact=(\d+) full=(\d+)$", text).groups()
        lane_stats = re.findall(r"(?m)^STAGED_MATRIX_LANE ideal=0 lane=(\d+) (.+)$", text)
        assert [lane for lane, _ in lane_stats] == ["0", "1"]
        results[str(credits)] = {
            "matrix_cycles": int(count),
            "peer_credit_stalls": [int(value) for value in stalls],
            "compact_read_requests": int(compact),
            "full_address_read_requests": int(full),
            "lanes": [dict((key, int(value)) for key, value in (word.split("=") for word in fields.split()))
                      for _, fields in lane_stats],
        }
        evidence.update((log, status))
    return {
        "state": "placed_booth_receiver_credit_window_verified_on_trained_matrix",
        "cold_netlist_sha256": digest(cold),
        "trained_tiles": 78,
        "exact_weight_bytes_per_run": 11534336,
        "modeled_return_delay_cycles": DELAY,
        "receivers": results,
        "matrix_cycles_saved_with_nine_credits": results["8"]["matrix_cycles"] - results["9"]["matrix_cycles"],
        "scope": "Same trained indexed down-projection matrix and archived mapped loader and write path, "
                 "with the receiver extracted from the repaired placed chip. Credit delay is modeled.",
        "evidence_sha256": {str(path.relative_to(ROOT) if path.is_absolute() else path): digest(path) for path in evidence},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "verify"))
    args = parser.parse_args()
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").is_file()
    if args.phase == "prepare":
        prepare()
    else:
        print(json.dumps(verify(), indent=2, sort_keys=True))
