"""Attach the proven host and memory packet wrappers to the wide compute core."""

import argparse
import json
from mmap import ACCESS_READ, mmap
from pathlib import Path
import re
import shutil

from link_tri_oracle_host_results import GROUP, patch_cold
from link_tri_oracle_indexed_whole_chip import module_at, signature, spans, stream_copy
from verify_tri_oracle_host_control import original_links
from verify_tri_oracle_serialized_placement_transfer import INSTANCE
from verify_tri_oracle_value_register_clock_rows import ROOT, linked_file, pin
from verify_tri_oracle_wide_packaging_boundary import GROUP_PORTS, PACKET_ROOT, PLACED_PACKET, TOP, WIDE_PLACEMENTS, WRAPPER_CHAIN


BOUNDARY = Path("records/tri_oracle_wide_packaging_boundary.json")
LOADS = Path("records/tri_oracle_value_register_clock_loads.json")
BATCH = "tri_oracle_grouped_cluster_batch_cells"
WRITER = "tri_oracle_decoder_bank_writeback"
GROUP_SOURCE = {"group_valid": "grouped_out_valid", "group_last": "selected_result_last",
                "group_tag": "layer_command_tag", "group_cluster": "grouped_result_cluster",
                "group_lane": "grouped_result_lane", "group_values": "grouped_result_values"}


def package_cone(source, index):
    package, libraries = set(), set()
    pending = [PACKET_ROOT]
    while pending:
        name = pending.pop()
        if name == TOP or name in package:
            continue
        package.add(name)
        start, stop = index[name]
        for item in INSTANCE.finditer(source, start, stop):
            child = item[1].decode()
            if child in index:
                pending.append(child)
            else:
                libraries.add(child)
    assert len(package) == 78 and len(libraries) > 0
    return package, libraries


def qualified_host_cells(evidence):
    values = json.loads(pin(LOADS, evidence).read_text())["evidence_sha256"]
    typical = {name: sha for name, sha in values.items() if name.endswith("tt1v25c.lib")}
    assert len(typical) == 7
    names = set()
    pattern = re.compile(rb"(?m)^[ \t]*cell\s*\(\s*\"?([\w$]+)\"?\s*\)\s*\{")
    for name, expected in typical.items():
        library = pin(Path(name), evidence, expected)
        with library.open("rb") as stream, mmap(stream.fileno(), 0, access=ACCESS_READ) as data:
            cells = {match[1].decode() for match in pattern.finditer(data)}
        assert cells and not names.intersection(cells)
        names.update(cells)
    return names


def check_split(current, changed):
    current_ports, new_ports = signature(current), signature(changed)
    assert not current_ports.keys() & GROUP_PORTS.keys()
    assert new_ports == current_ports | GROUP_PORTS
    before = original_links(current.decode(), (BATCH, "batch"))
    after = original_links(changed.decode(), (BATCH, "batch"))
    assert before["result_ready"] == "wb_out_ready"
    assert after == before | {"result_ready": "group_ready"}
    assert original_links(current.decode(), (WRITER, "bank_writeback")) == original_links(
        changed.decode(), (WRITER, "bank_writeback"))
    for group, source in GROUP_SOURCE.items():
        assert changed.count(f"assign {group} = {source};".encode()) == 1, group


def verify_assembly(out, wide, original, package, packet, evidence):
    with out.open("rb") as stream, mmap(stream.fileno(), 0, access=ACCESS_READ) as linked:
        index, wide_index, old_index = (spans(item) for item in (linked, wide, original))
        assert index.keys() == wide_index.keys() | package
        core = module_at(linked, index, TOP)
        check_split(module_at(wide, wide_index, TOP), core)
        assert signature(core) == signature(module_at(original, old_index, TOP))
        for name in index:
            if name == TOP:
                continue
            expected, old = (original, old_index) if name in package else (wide, wide_index)
            start, stop = index[name]
            a, b = old[name]
            assert stop-start == b-a, name
            verify_range(linked, expected, start, a, stop-start, name)
        for parent, child, inst in WRAPPER_CHAIN:
            model = module_at(linked, index, child)
            actual = original_links(module_at(linked, index, parent).decode(), (child, inst))
            assert actual.keys() == signature(model).keys(), parent
        assert signature(module_at(linked, index, PACKET_ROOT)) == signature(
            module_at(original, old_index, PACKET_ROOT))
        pkg, leaves = package_cone(linked, index)
        assert pkg == package
    assert pin(packet, evidence)  # Keep the exact packetized donor in the evidence chain.
    return len(index), len(leaves)


def verify_range(actual, expected, a, b, length, name):
    block = 8 << 20
    for offset in range(0, length, block):
        amount = min(block, length-offset)
        assert actual[a+offset:a+offset+amount] == expected[b+offset:b+offset+amount], name


def produce(output, mode):
    evidence = {}
    boundary = json.loads(pin(BOUNDARY, evidence).read_text())
    packets = json.loads(pin(PLACED_PACKET, evidence).read_text())
    packet = linked_file(packets, "/cold/cold.v", evidence)
    assert evidence[str(packet)] == boundary["packetized_candidate_sha256"]

    cases = json.loads(pin(WIDE_PLACEMENTS, evidence).read_text())
    target = cases["placement"][mode]["cold_netlist_sha256"]
    assert target == boundary["wide_candidates"][mode]["cold_netlist_sha256"]
    name, = (name for name, sha in cases["evidence_sha256"].items()
             if name.endswith("/cold.v") and sha == target)
    cold = pin(Path(name), evidence, target)
    active_cells = qualified_host_cells(evidence)
    assert output.resolve().is_relative_to(ROOT / ".cache")
    assert not output.exists() and shutil.disk_usage(output.parent).free >= 12 * (1 << 30)
    body = output / "candidate.v"
    output.mkdir()
    with cold.open("rb") as wide_file, packet.open("rb") as packet_file:
        with mmap(wide_file.fileno(), 0, access=ACCESS_READ) as wide, mmap(packet_file.fileno(), 0, access=ACCESS_READ) as donor:
            core_index, donor_index = spans(wide), spans(donor)
            package, external = package_cone(donor, donor_index)
            assert not core_index.keys() & package
            assert external <= active_cells, sorted(external - active_cells)
            start, stop = core_index[TOP]
            revised = patch_cold(module_at(wide, core_index, TOP))
            with body.open("xb") as full:
                stream_copy(full, wide, 0, start)
                full.write(revised)
                stream_copy(full, wide, stop, len(wide))
                for wrapper in sorted(package):
                    full.write(b"\n")
                    a, b = donor_index[wrapper]
                    stream_copy(full, donor, a, b)
                full.write(b"\n")
            modules, library_references = verify_assembly(body, wide, donor, package, packet, evidence)
    assert library_references == len(external)
    assert GROUP.keys() == GROUP_PORTS.keys()
    for dependency in (Path(__file__).resolve().relative_to(ROOT),
                       Path("syn/link_tri_oracle_host_results.py"),
                       Path("syn/verify_tri_oracle_wide_packaging_boundary.py")):
        pin(dependency, evidence)
    digest = pin(body, evidence)
    return {
        "state": "wide_core_packetized_host_and_memory_interfaces_linked_structurally",
        "base": mode,
        "packetized_top": PACKET_ROOT,
        "base_placed_netlist_sha256": target,
        "linked_netlist_sha256": evidence[str(digest)],
        "mapped_module_definitions": modules,
        "preserved_packet_module_definitions": len(package),
        "resolved_library_master_references_in_package": library_references,
        "restored_group_handshake_and_payload_port_count": len(GROUP),
        "scope": ("Byte-exact assembly outside the wide top-level boundary edit. Group backpressure uses "
                  "the existing transmitter. Preserves separate writeback readiness and all package "
                  "port declarations. Packet execution, synthesis timing, and physical integration remain pending."),
        "evidence_sha256": evidence,
    }


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", choices=("resized", "control_buffered"))
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = produce(args.output, args.candidate)
    (args.output / "prepared.json").write_text(json.dumps(result, indent=2, sort_keys=True)+"\n")
    print(result["state"], result["linked_netlist_sha256"], flush=True)
