"""Compare unplaced and placed timing for the same two mapped arrays."""

from collections import Counter
import json
from pathlib import Path
import re

from verify_tri_oracle_booth_chip_link import WORK
from verify_tri_oracle_gated_compute_array import ROOT, digest, read, timing_script

OUT = WORK / "operand_geometry/unplaced_comparison"
INPUTS = {
    "earlier_booth": (
        "earlier",
        "tri_oracle_booth_operand_buffers",
        "tri_oracle_booth_timing_swaps",
    ),
    "sparse_booth": (
        "smaller",
        "tri_oracle_sparse_booth_operand_buffers",
        "tri_oracle_sparse_booth_control_buffers",
    ),
}
VIEWS = ("setup", "hold", "gate_setup", "gate_hold")


def delays(folder):
    result = {}
    for view in VIEWS:
        report = folder / f"native_{view}.rpt"
        slacks = re.findall(rb"Slack:=\s+(-?\d+\.\d+)", report.read_bytes())
        assert slacks, report
        result[view] = min(map(float, slacks))
    return result


def verify():
    evidence = {}
    inputs = {}
    shared_constraints = None

    def pin(path, expected=None):
        value = digest(path)
        assert expected is None or value == expected, path
        evidence[str(path)] = value
        return path

    for name, (short, receipt, constraints_receipt) in INPUTS.items():
        older, source = (
            read(pin(Path(f"records/{item}.json")))
            for item in (receipt, constraints_receipt)
        )
        proof = older["evidence_sha256"]
        native = OUT / short
        (logical,) = (
            Path(k) for k in proof if k.endswith("/operand_buffers/netlist.v")
        )
        assert pin(native / "netlist.v", proof[str(logical)]).resolve(
            strict=True
        ) == logical.resolve(strict=True)
        sdc = pin(native / "emitted.sdc")
        signatures = {
            v
            for k, v in source["evidence_sha256"].items()
            if k.endswith("/emitted.sdc")
        }
        assert signatures == {evidence[str(sdc)]}
        lines = Counter(
            " ".join(line.split())
            for line in sdc.read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
        if shared_constraints is not None:
            assert lines == shared_constraints
        shared_constraints = lines
        assert pin(native / "timing.tcl").read_text() == timing_script()
        log = pin(native / "console.log").read_text()
        assert re.search(r"(?m)^TRI_ORACLE_MAPPED_ARRAY_TIMING_FINISHED$", log)
        assert re.search(r"Message Summary:\s+\d+ warning\(s\), 0 error\(s\)", log)
        assert not re.search(
            r"(?m)^\*\*ERROR:|Started Early Global Route|read_def ", log
        )
        (placed_report,) = (
            Path(k) for k in proof if k.endswith("/operand_buffers/native_setup.rpt")
        )
        unplaced = delays(native)
        placed = delays(placed_report.parent)
        assert placed == older["after_slack_ns"]
        for view in VIEWS:
            measured = placed_report.parent / f"native_{view}.rpt"
            pin(measured, proof[str(measured)])
            pin(native / f"native_{view}.rpt")
        inputs[name] = {
            "unplaced_slack_ns": unplaced,
            "placed_slack_ns": placed,
            "worst_setup_slack_loss_after_placement_ns": round(
                unplaced["setup"] - placed["setup"], 3
            ),
        }
    assert shared_constraints
    pin(Path(__file__).resolve().relative_to(ROOT))
    return {
        "state": "paired_booth_array_unplaced_and_placed_timing_verified",
        "constraints_statements_matched": shared_constraints.total(),
        "clock_megahertz": 580,
        "variants": inputs,
        "scope": "The same mapped netlist and timing constraints are used for each array's placed and unplaced run. The setup losses compare each run's worst slack and include changes in which path is worst.",
        "evidence_sha256": evidence,
    }


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    print(json.dumps(verify(), sort_keys=True, indent=2))
