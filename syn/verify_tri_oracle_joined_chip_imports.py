"""Check mapped imports for the joined chip before assembling its parent."""

import argparse
from collections import Counter
from contextlib import ExitStack
import json
from pathlib import Path

from link_tri_oracle_parallel_chip import DECODER, DISPATCH, audit_imports, catalog, library_masters, load_setup
from prepare_tri_oracle_joined_decoder_candidate import ROOT, WIDE, read
from prepare_tri_oracle_parallel_chip_synthesis import LOADER_CUT, pin, verify


PREVIOUS = WIDE / "parallel_synthesis"
LOADER = WIDE / "dual_lane_joined_mapped_loader/mapped.v"
PREDICTOR_MEMORIES = Counter({"TS5N28HPCPSVTA32X128M2FW": 9, "TS5N28HPCPSVTA512X64M4F": 1})


def run(output):
    setup, pins, _, expected_memories = load_setup(PREVIOUS)
    previous = ROOT / "records/wac_parallel_chip_mapped_imports_result.json"
    replacement = ROOT / "records/wac_joined_mapped_loader_directed_result.json"
    census = ROOT / "records/wac_dual_lane_packed_sign_memory_result.json"
    for path in (previous, replacement, census, Path(__file__).resolve()):
        pin(pins, path)
    control, loader, source = map(read, (previous, replacement, census))
    assert control["state"] == "parallel_chip_mapped_import_signatures_and_memory_inventory_verified"
    assert loader["state"] == "joined_decoder_mapped_weight_loader_directed_verified"
    assert loader["mapped_cut"] == LOADER_CUT
    assert source["state"] == "packed_sign_source_chip_compiled_memory_census_verified"
    for name, digest in loader["evidence_sha256"].items():
        pin(pins, ROOT / name, digest)
    expected_complete = Counter(source["compiled_by_master"])
    assert source["instances"] == expected_complete.total()
    assert source["packed_predictor_instances"] == PREDICTOR_MEMORIES.total()
    assert expected_memories + PREDICTOR_MEMORIES == expected_complete
    assert control["imported_compiled_memories"] == expected_memories

    library = library_masters(pins, PREVIOUS)
    with ExitStack() as stack:
        assets = catalog(stack, DECODER, DISPATCH, LOADER)
        imported, cuts = audit_imports(assets, library, setup["preserved"], expected_memories)
    assert cuts.keys() == control["cuts"].keys()
    assert all(cut == control["cuts"][name] for name, cut in cuts.items() if name != LOADER_CUT)
    old_loader, new_loader = control["cuts"][LOADER_CUT], cuts[LOADER_CUT]
    assert new_loader["definition_sha256"] != old_loader["definition_sha256"]
    assert new_loader["ports"] == old_loader["ports"] == loader["mapped_ports"]
    assert new_loader["compiled_memories"] == old_loader["compiled_memories"] == 0
    checked = sum(cut["ports"] for cut in cuts.values())
    assert checked == control["checked_cut_ports"]
    verify(pins)
    result = {"state": "joined_chip_existing_mapped_imports_verified",
              "cuts": cuts, "checked_cut_ports": checked, "reachable_definitions": len(imported),
              "unchanged_cuts": len(cuts) - 1, "replacement_cut": LOADER_CUT,
              "verified_compiled_memories": dict(expected_memories),
              "pending_mapped_predictor_memories": dict(PREDICTOR_MEMORIES),
              "expected_total_source_compiled_memories": dict(expected_complete),
              "scope": "Mapped imports for the joined chip, with packed predictor mapping still pending.",
              "evidence_sha256": pins}
    with output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(result["state"], len(cuts), checked, expected_memories.total(), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=lambda value: Path(value).resolve())
    run(parser.parse_args().output)
