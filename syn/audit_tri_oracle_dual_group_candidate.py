"""Independently reconcile a linked writer against the paper's mapped resources."""

import argparse
from collections import Counter
import json
import mmap
from pathlib import Path

from audit_tri_oracle_indexed_whole_chip import changed_modules, memory_paths
from audit_tri_oracle_mapped_redundancy import TOP, audit, hierarchy
from audit_tri_oracle_placed_chip_boundary import digest
from link_tri_oracle_dual_group_whole_chip import DECODER, WIDE_TILE, WIDE_TRANSPORT
from link_tri_oracle_indexed_whole_chip import LOADER, STAGE, module_at, pins, signature, spans
from verify_tri_oracle_buffered_topology import PAPER_SHA256, verify_compute_arrays


RECORDS = Path("records")


def read(path):
    return json.loads(path.read_text())


def audit_widened(base, candidate, writer, identity):
    narrow = RECORDS / "tri_oracle_indexed_whole_chip_link.json"
    writer_proof = RECORDS / "tri_oracle_dual_group_weight_fabric.json"
    resources = RECORDS / "tri_oracle_repaired_native_compute_and_memory.json"
    targets = RECORDS / "paper_result_targets.json"
    paper = Path(read(targets)["source"])
    assert digest(paper) == PAPER_SHA256
    assert digest(base) == identity["base_sha256"] == read(narrow)["candidate_sha256"]
    assert digest(candidate) == identity["candidate_sha256"]
    assert digest(writer) == read(writer_proof)["evidence_sha256"][str(writer)]
    assert read(writer_proof)["base_candidate_sha256"] == identity["base_sha256"]

    before, graph = (hierarchy(path, include_memory=True) for path in (base, candidate))
    paths = memory_paths(graph)
    assert paths == memory_paths(before) and len(paths) == identity["compiled_memory_paths"] == 631
    design = {master: {child: model for child, model in children.items() if model in graph}
              for master, children in graph.items()}
    saved = read(resources)
    modes = Counter(paths.values())
    assert modes == saved["compiled_macro_count_by_master"]
    capacity = sum(count * saved["bytes_per_memory_macro"][master] for master, count in modes.items())
    assert capacity == saved["compiled_memory"]["compiled_bytes"]
    assert round(capacity / 1024) == read(targets)["silicon"]["sram_published_KB"]

    tensor = TOP
    for instance in ("layer", "layer", "feedforward", "compute", "compute", "tensor"):
        tensor = design[tensor][instance]
    assert design[tensor]["packed_write_stage"] == STAGE
    assert design[tensor]["packed_loader"] == WIDE_TRANSPORT
    assert design[WIDE_TRANSPORT]["raw_loader"] == LOADER
    for lane in range(2):
        selector = design[WIDE_TRANSPORT][rf"\indexed_lane[{lane}].loader"]
        loader = design[selector]["loader"]
        assert design[loader]["decoder"] == WIDE_TILE

    cuts = writer.read_bytes()
    cut_index = spans(cuts)
    with (
        base.open("rb") as left, candidate.open("rb") as right,
        mmap.mmap(left.fileno(), 0, access=mmap.ACCESS_READ) as original,
        mmap.mmap(right.fileno(), 0, access=mmap.ACCESS_READ) as linked,
    ):
        old_index, new_index = spans(original), spans(linked)
        assert old_index.keys() <= new_index.keys()
        edits = sorted(changed_modules(original, linked, old_index, new_index))
        assert set(edits) == cut_index.keys() | {tensor}
        for master in cut_index:
            assert module_at(linked, new_index, master) == module_at(cuts, cut_index, master)
        assert module_at(original, old_index, TOP) == module_at(linked, new_index, TOP)
        assert module_at(original, old_index, DECODER) == module_at(linked, new_index, DECODER)
        transport = signature(module_at(linked, new_index, WIDE_TRANSPORT))
        body = module_at(linked, new_index, tensor)
        stage = pins(body, STAGE, "packed_write_stage")
        controller = pins(body, WIDE_TRANSPORT, "packed_loader")
        fabric = pins(body, design[tensor]["fabric"], "fabric")
        for lane in range(2):
            assert transport[f"rsp_data[{lane}]"] == (b"input", b"[511:0]")
            assert transport[f"load_payload[{lane}]"] == (b"output", b"[1023:0]")
            assert stage[f"load_payload[{lane}]"] == controller[f"load_payload[{lane}]"]
            assert stage[f"write_payload[{lane}]"] == fabric[f"wide_load_payload[{lane}]"]

    topology = audit(design)
    arrays = verify_compute_arrays(candidate, design, read(targets))
    assert topology["clusters"] == saved["clusters"]
    return {
        "state": "widened_mapped_topology_and_memory_resources_verified",
        "candidate_sha256": identity["candidate_sha256"],
        "predecessor_sha256": identity["base_sha256"],
        "paper_sha256": PAPER_SHA256,
        "clusters": topology["clusters"],
        "compute": arrays,
        "memory_masters": modes,
        "compiled_memory_instances": len(paths),
        "compiled_memory_bytes": capacity,
        "modified_existing_definitions": edits,
        "preserved_raw_loader": LOADER,
        "scope": "Structural resource evidence on the linked candidate. Compute peak assumes the paper clock. "
                 "Native whole-chip execution and physical timing require independent checks.",
        "evidence_sha256": {str(path): digest(path) for path in
                            (base, candidate, writer, narrow, writer_proof, resources, targets, Path(__file__))},
    }


def main():
    assert __debug__ and Path("/.dockerenv").is_file()
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("base", "candidate", "writer", "link_receipt", "output"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    data = audit_widened(args.base, args.candidate, args.writer, read(args.link_receipt))
    with args.output.open("x") as receipt:
        json.dump(data, receipt, indent=2, sort_keys=True)
        receipt.write("\n")
    print("DUAL_GROUP_STRUCTURE_VERIFIED", data["candidate_sha256"], flush=True)


if __name__ == "__main__":
    main()
