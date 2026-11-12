"""Check the native setup arithmetic and identify the slowest reported stages."""

import argparse
from collections import Counter
from decimal import Decimal
import json
from pathlib import Path
import re

from check_tri_oracle_paper300_gate import sha


ROOT = Path(__file__).resolve().parents[1]
COMPACT = ROOT / ".cache/physical/wac_budgeted_parent_boundary/compact_load_transport"
BASELINE = COMPACT / "estimated_placement_timing"
VIEW = "setup_slow"
NS = r"-?\d+\.\d+"
PATH = re.compile(rf"(?m)^Path (\d+): (VIOLATED|MET) \(({NS}) ns\) Setup Check")
POINT = re.compile(rf"(?m)^  (\S+)\s+\S+\s+\S+\s+[RF]\s+(\S+)\s+(\d+)\s+({NS})\s+({NS}|-)\s+({NS})\s*$")
TOLERANCE = Decimal("0.000150")
NATIVE_FIELDS = {
    "compact_tensor_matched_slow_placement_timing_measured": ("extraction_native", "report_native"),
    "compact_weight_decoder_matched_pre_route_timing_measured": ("extraction_native", "report_native"),
    "compact_row_buffer_matched_pre_route_timing_measured": ("extraction", "report"),
}


def read(path):
    return json.loads(path.read_text())


def field(pattern, text):
    value, = re.findall(pattern, text, re.M)
    return value


def parse_setup_paths(text):
    """Return path records using the printed arrival, required time and stage rows."""
    headings = list(PATH.finditer(text))
    assert headings and [int(match[1]) for match in headings] == list(range(1, len(headings) + 1))
    paths = []
    for index, match in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        block = text[match.end():end]
        start = field(r"^\s*Startpoint: \([RF]\) (\S+)$", block)
        finish = field(r"^\s*Endpoint: \([RF]\) (\S+)$", block)
        assert field(r"^\s*View: (\S+)$", block) == VIEW
        assert field(r"^\s*Group: (\S+)$", block) == "core_clock"
        required = Decimal(field(rf"^\s*Required Time:=\s*({NS})\s*$", block))
        slack = Decimal(field(rf"^\s*Slack:=\s*({NS})\s*$", block))
        assert Decimal(match[3]) == slack and (match[2] == "VIOLATED") == (slack < 0)
        capture, launch = field(rf"^\s*Clock Edge:\+\s*({NS})\s+({NS})\s*$", block)
        period = Decimal(capture) - Decimal(launch)
        assert abs(period - Decimal(1000) / Decimal(580)) < Decimal("0.000010")
        points = POINT.findall(block)
        assert len(points) >= 2 and points[0][0] == start and points[-1][0] == finish
        arrival = Decimal(points[-1][-1])
        assert abs(required - arrival - slack) <= TOLERANCE, (required, arrival, slack)
        prior = None
        stages = []
        for point, cell, fanout, transition, delay, arrival_at_point in points:
            actual = Decimal(arrival_at_point)
            if delay != "-":
                delay_ns = Decimal(delay)
                if prior is not None:
                    assert abs(actual - prior - delay_ns) <= TOLERANCE, point
                stages.append({"point": point, "cell": cell, "fanout": int(fanout),
                               "transition_ns": float(transition), "delay_ns": float(delay_ns)})
            prior = actual
        assert stages
        paths.append({"startpoint": start, "endpoint": finish, "required_ns": float(required),
                      "arrival_ns": float(arrival), "slack_ns": float(slack), "period_ns": float(period),
                      "largest_stages": sorted(stages, key=lambda stage: -stage["delay_ns"])[:3]})
    assert all(a["slack_ns"] <= b["slack_ns"] for a, b in zip(paths, paths[1:]))
    return paths


def audit(folder):
    receipt_path = folder / "receipt.json"
    receipt = read(receipt_path)
    keys = NATIVE_FIELDS[receipt["state"]]
    paths = {}
    for stage, key in zip(("extract", "report"), keys, strict=True):
        log = folder / stage / "console.log"
        assert receipt[key]["native_exit_status"] == 0
        assert sha(log) == receipt[key]["log_sha256"]
        paths[str(log.relative_to(ROOT))] = sha(log)
    extract = (folder / "extract/console.log").read_text()
    report = (folder / "report/console.log").read_text()
    assert extract.splitlines().count("COMPACT_ESTIMATED_PARASITICS_WRITTEN") == 1
    assert report.splitlines().count("COMPACT_ESTIMATED_PARASITICS_RELOADED") == 1
    assert report.splitlines().count("PLACED_TIMING_MODE single HIGH_FANOUT_DEFAULT_DELAY false") == 1
    assert report.splitlines().count(f"LINKED_PLACED_TIMING_VIEW_WRITTEN {VIEW}") == 1
    timing_path = folder / "report/timing.rpt"
    annotation = folder / "report/annotation.rpt"
    hashes = receipt.get("output_sha256", receipt.get("evidence_sha256", {}))
    for file in (timing_path, annotation):
        assert hashes[str(file)] == sha(file)
    setup = parse_setup_paths(timing_path.read_text())
    assert {"reported_paths": len(setup), "violating_paths": sum(path["slack_ns"] < 0 for path in setup),
            "worst_slack_ns": setup[0]["slack_ns"]} == receipt["timing"]
    paths.update({str(file.relative_to(ROOT)): sha(file) for file in (receipt_path, timing_path, annotation)})
    return {
        "timing": receipt["timing"], "worst_path": setup[0], "period_ns": setup[0]["period_ns"],
        "critical_startpoints": dict(Counter(path["startpoint"] for path in setup)),
        "largest_delay_stages": dict(Counter(path["largest_stages"][0]["point"] for path in setup)),
    }, paths


def run(baseline, candidate, output):
    if not __debug__:
        raise RuntimeError("Run the timing audit with assertions enabled")
    original, pins = audit(baseline)
    result = {"state": "compact_placed_slow_setup_paths_independently_checked", "baseline": original}
    if candidate:
        revised, current = audit(candidate)
        receipt = read(candidate / "receipt.json")
        baseline_field = ("unmasked_timing" if receipt["state"] == "compact_row_buffer_matched_pre_route_timing_measured"
                          else "baseline_timing")
        baseline_receipt = baseline / "receipt.json"
        assert receipt["evidence_sha256"][str(baseline_receipt)] == sha(baseline_receipt)
        assert receipt[baseline_field] == original["timing"]
        assert revised["period_ns"] == original["period_ns"]
        delta = revised["timing"]["worst_slack_ns"] - original["timing"]["worst_slack_ns"]
        assert abs(delta - receipt["delta_worst_slack_ns"]) < 1e-9
        result.update(candidate=revised, delta_worst_slack_ns=delta)
        pins.update(current)
    pins[str(Path(__file__).resolve().relative_to(ROOT))] = sha(Path(__file__))
    assert all(sha(ROOT / file) == digest for file, digest in pins.items())
    result.update(evidence_sha256=pins, scope="Estimated interconnect delay on legally placed compact decoder versions.")
    with output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(result["state"], result.get("delta_worst_slack_ns"), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--baseline", type=lambda value: Path(value).resolve(), default=BASELINE)
    parser.add_argument("--candidate", type=lambda value: Path(value).resolve())
    args = parser.parse_args()
    run(args.baseline, args.candidate, args.output)
