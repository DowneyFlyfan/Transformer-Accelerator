"""Verify the indexed command graft against the unmodified cold export."""

import argparse
import json
import mmap
from pathlib import Path
import re

from audit_tri_oracle_mapped_redundancy import hierarchy
from audit_tri_oracle_placed_chip_boundary import digest
from link_tri_oracle_indexed_whole_chip import (
    DISPATCH, LOADER, MODE, OLD_DISPATCH, PAYLOAD, STAGE, TOP, TRANSPORT,
    module_at, pins, replacements, signature, spans,
)


def memory_paths(graph):
    pending = [(TOP, TOP)]
    result = {}
    while pending:
        path, master = pending.pop()
        for name, child in graph[master].items():
            instance = path + "." + name.removeprefix("\\")
            if child.startswith(("TS5N28", "TS6N28")):
                assert instance not in result
                result[instance] = child
            else:
                pending.append((instance, child))
    return result


def changed_modules(before, after, old_index, new_index):
    slab = 1024**2
    for master, (first, last) in old_index.items():
        a, b = new_index[master]
        if last - first != b - a:
            yield master
            continue
        for offset in range(0, b - a, slab):
            width = min(slab, b - a - offset)
            if before[first + offset:first + offset + width] != after[a + offset:a + offset + width]:
                yield master
                break


def check_route(before, after, old_index, new_index, linked_graph, path):
    native_top = module_at(before, old_index, TOP)
    linked_top = module_at(after, new_index, TOP)
    assert signature(native_top) == signature(linked_top)
    assert pins(linked_top, DISPATCH, "dispatch") == pins(native_top, OLD_DISPATCH, "dispatch") | {
        "layer_feedforward_indexed": MODE.encode()
    }
    master = TOP
    for node in path.split(".")[1:-1]:
        child = linked_graph[master][node]
        assert signature(module_at(after, new_index, child)) == signature(
            module_at(before, old_index, child)
        ) | {MODE: (b"input", b"")}
        assert pins(module_at(after, new_index, master), child, node) == pins(
            module_at(before, old_index, master), child, node
        ) | {MODE: MODE.encode()}
        master = child

    old_tensor = module_at(before, old_index, master)
    linked_tensor = module_at(after, new_index, master)
    assert linked_graph[master]["packed_loader"] == TRANSPORT
    assert linked_graph[TRANSPORT]["raw_loader"] == LOADER
    indexed = {"cfg_indexed": MODE.encode()}
    payload = {}
    for lane, response in enumerate((b"wide_rsp_data", b"aux_rsp_data")):
        wire = f"{PAYLOAD}{lane}".encode()
        indexed[f"rsp_data[{lane}]"] = response
        indexed[f"load_payload[{lane}]"] = wire
        payload[f"load_payload[{lane}]"] = wire
    assert pins(linked_tensor, TRANSPORT, "packed_loader") == pins(
        old_tensor, LOADER, "packed_loader"
    ) | indexed
    assert pins(linked_tensor, STAGE, "packed_write_stage") == pins(
        old_tensor, STAGE, "packed_write_stage"
    ) | payload


def reject_truncated_lane(before, old_index, old_graph, dispatch, transport):
    declaration = rb"input \[511:0\]\s+\\rsp_data\[0\]\s*,\s*\\rsp_data\[1\]\s*;"
    replacement = rb"input [511:0] \\rsp_data[0] ; input [510:0] \\rsp_data[1] ;"
    broken, count = re.subn(declaration, replacement, transport)
    assert count == 1
    # Put the second declaration on its own line for the non-ANSI port parser.
    broken = broken.replace(b"; input [510:0]", b";\n  input [510:0]", 1)
    try:
        replacements(before, old_index, old_graph, dispatch, broken)
    except ValueError as error:
        assert "Transport interface changed" in str(error), error
    else:
        raise AssertionError("Truncated response lane passed")


def audit(base, candidate, manifest):
    assert __debug__, "Use Python assertions"
    assert digest(base) == manifest["base_sha256"]
    assert digest(candidate) == manifest["candidate_sha256"]
    old = hierarchy(base)
    new = hierarchy(candidate, include_memory=True)
    macros = memory_paths(hierarchy(base, include_memory=True))
    assert len(macros) == 631 and macros == memory_paths(new)
    with base.open("rb") as original, candidate.open("rb") as linked, mmap.mmap(
        original.fileno(), 0, access=mmap.ACCESS_READ
    ) as before, mmap.mmap(linked.fileno(), 0, access=mmap.ACCESS_READ) as after:
        old_index, new_index = spans(before), spans(after)
        assert old_index.keys() <= new_index.keys()
        added = len(new_index) - len(old_index)
        assert added == manifest["added_module_count"]
        modified = sorted(changed_modules(before, after, old_index, new_index))
        assert modified == manifest["edited_modules"]
        check_route(before, after, old_index, new_index, new, manifest["loader_path"])
        reject_truncated_lane(before, old_index, old,
                              module_at(after, new_index, DISPATCH),
                              module_at(after, new_index, TRANSPORT))
    return {
        "state": "whole_chip_indexed_link_structure_verified",
        "candidate_sha256": manifest["candidate_sha256"],
        "base_sha256": manifest["base_sha256"],
        "compiled_memory_instances_at_original_hierarchical_paths": len(macros),
        "modified_existing_modules": modified,
        "additional_implementations": added,
        "truncated_response_interface_rejected": True,
        "top_level_ports_preserved": True,
        "scope": "Structural linkage. Native simulation, placement qualification and paper-level validation remain pending.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("link_manifest", type=Path)
    args = parser.parse_args()
    result = audit(args.base, args.candidate, json.loads(args.link_manifest.read_text()))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
