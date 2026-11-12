"""Bind native Genus constraints to the exact linked parent and imports."""

import argparse
from contextlib import ExitStack
import json
from pathlib import Path

from audit_tri_oracle_linked_pin_constraints import audit_targets
from link_tri_oracle_parallel_chip import catalog
from prepare_tri_oracle_packed_sign_predictor import rewrite
from prepare_tri_oracle_parallel_chip_synthesis import TOP, pin, read, verify
from prepare_tri_oracle_parallel_pin_constraints import source_ports
from verify_tri_oracle_packed_down_weights import ROOT


def run(mapping, linked, source, output):
    mapping_receipt, linked_receipt = (folder / "receipt.json" for folder in (mapping, linked))
    native, assembled = read(mapping_receipt), read(linked_receipt)
    assert native["state"] in {"dual_lane_chip_parent_mapped_and_preserved_cut_signatures_verified",
                               "joined_chip_parent_mapped_and_preserved_cut_signatures_verified"}
    assert assembled["state"] in {"parallel_chip_parent_linked_with_verified_mapped_imports",
                                  "joined_chip_parent_linked_with_verified_mapped_imports"}
    assert native["native"]["native_exit_status"] == 0 and native["native"]["stop_reason"] is None
    top = assembled["top"]
    assert top == native["top"]
    pins = {}
    for path in (mapping_receipt, linked_receipt, Path(__file__).resolve()):
        pin(pins, path)
    expected = assembled["input_sha256"]
    for path in (mapping_receipt, source):
        pin(pins, path, expected[str(path.relative_to(ROOT))])
    sdc, netlist = mapping / "constraints.sdc", linked / "chip.v"
    pin(pins, sdc, native["output_sha256"][str(sdc.relative_to(ROOT))])
    pin(pins, netlist, assembled["chip_sha256"])

    constraints = sdc.read_text()
    original, = (line for line in constraints.splitlines() if line.startswith("current_design "))
    assert original in {f"current_design {TOP}", f"current_design {top}"}
    assert constraints.count('create_clock -name "core_clock" -period 1.72414 ') == 1
    adjusted = rewrite(constraints, ((original + "\n", f"current_design {top}\n"),))
    with ExitStack() as stack:
        diagnostics = audit_targets(catalog(stack, netlist), top, adjusted, source_ports(source.read_text()))
    assert not diagnostics["port_differences"] and not diagnostics["unresolved_protections"], diagnostics
    assert diagnostics["resolved_protections"] == {"get_cells": len(native["preserved_cuts"])}
    counts = diagnostics["constrained_port_bits"]
    assert counts == {"set_load": 7631, "set_output_delay": 7631, "set_input_delay": 4732, "set_input_transition": 4732}
    verify(pins)

    output.mkdir()
    target = output / "candidate.sdc"
    target.write_text(adjusted)
    pin(pins, target)
    report = {"state": "linked_chip_native_parent_constraints_bound", "candidate_sha256": assembled["chip_sha256"],
              "top": top, "clock_period_ns": 1.72414, **diagnostics, "input_sha256": pins,
              "scope": "Genus-exported constraints resolve against the linked netlist before native physical import."}
    (output / "receipt.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(report["state"], sum(counts.values()) // 2 + 2, diagnostics["resolved_protections"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("mapping", "linked", "source", "output"):
        parser.add_argument(name, type=lambda value: Path(value).resolve())
    run(**vars(parser.parse_args()))
