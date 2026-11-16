"""Check area-oriented synthesis against the verified clock-gated mapping."""
import argparse
import json
from pathlib import Path
import re

from verify_tri_oracle_gated_compute_array import ROOT, WORK as GATED, area, compile_script, digest, read


WORK = GATED.with_name("compact_gated_array")
PRIOR = Path("records/tri_oracle_gated_compute_array.json")


def area_script():
    anchor = "    set_db lp_insert_clock_gating true\n"
    source = compile_script()
    assert source.count(anchor) == 1
    return source.replace(anchor, '    set_db dp_area_mode true\n'
                          '    puts TRI_ORACLE_ARRAY_DATAPATH_AREA_MODE=[get_db dp_area_mode]\n' + anchor)


def verify_compaction():
    baseline = read(PRIOR)
    transcript = (WORK / "console.log").read_text()
    assert "TRI_ORACLE_ARRAY_DATAPATH_AREA_MODE=true" in transcript
    assert re.search(r"(?m)^REDUCTION_SYNTH_COMPARE_PASS \d+$", transcript)
    assert re.search(r"(?m)^Normal exit\.$", transcript)
    assert (WORK / "synthesize.tcl").read_text() == area_script()
    outputs = ("area.rpt", "netlist.v", "emitted.sdc")
    for name in outputs:
        path = GATED / name
        assert digest(path) == baseline["evidence_sha256"][str(path)], path
    assert area(GATED / "area.rpt") == area(WORK / "area.rpt")
    for name, timestamp in (("netlist.v", r"// Generated on: .+"), ("emitted.sdc", r"#  Created by Genus\(TM\).+")):
        before, after = (root.joinpath(name).read_text().splitlines(keepends=True) for root in (GATED, WORK))
        assert len(before) == len(after), name
        changes = [index for index, (first, second) in enumerate(zip(before, after, strict=True)) if first != second]
        index, = changes
        assert index < 10 and all(re.fullmatch(timestamp, lines[index].rstrip("\n")) for lines in (before, after)), name
    cells, sites = area(WORK / "area.rpt")
    assert cells == baseline["clock_gated_mapped_cells"] and sites == baseline["clock_gated_mapped_sites"]
    files = [PRIOR, WORK / "synthesize.tcl", WORK / "console.log", Path(__file__).resolve().relative_to(ROOT)]
    files.extend(root / name for root in (GATED, WORK) for name in outputs)
    return {
        "state": "datapath_area_mode_reproduces_identical_gated_mapping_and_constraints",
        "mapped_cells": cells, "mapped_sites": sites, "sites_saved": 0,
        "projected_site_deficit_unchanged": -baseline["remaining_geometric_site_margin_with_receiver_and_array_replacements"],
        "scope": "The area-oriented run completed. Each emitted netlist and constraint file changes only in its "
                 "generation timestamp. The prior mapped functional and timing evidence applies to the identical circuit.",
        "evidence_sha256": {str(path): digest(path) for path in files},
    }


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "verify"))
    action = parser.parse_args().action
    if action == "prepare":
        WORK.mkdir(parents=True, exist_ok=True)
        (WORK / "synthesize.tcl").write_text(area_script())
    else:
        print(json.dumps(verify_compaction(), indent=2, sort_keys=True))
