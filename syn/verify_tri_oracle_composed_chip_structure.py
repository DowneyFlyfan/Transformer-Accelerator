"""Audit the repacked whole-chip netlist and coordinates before native reload."""

from collections import Counter
import json
import mmap
from pathlib import Path
import re

from audit_tri_oracle_mapped_redundancy import (
    ENDMODULE, MODULE, PE_ARRAY, SHARED_HEAD, SHARED_STRIP, TOP, audit, hierarchy,
)
from audit_tri_oracle_shared_prediction_roles import SIGN_BANK, scan_feedforward, scan_head
from check_tri_oracle_paper300_gate import dimensions
from verify_tri_oracle_buffered_topology import PAPER_SHA256, reachable_arrays
from verify_tri_oracle_pad_memory import compiler_sizes, memory_roles
from verify_tri_oracle_repeater_placement_evidence import compiled_memory_inventory, read, sha


ROOT = Path(__file__).resolve().parents[1]
RECORDS = ROOT / "records"
COMPOSITION = RECORDS / "tri_oracle_hot_timed_array_twenty_core_composition.json"
BASELINE = RECORDS / "tri_oracle_bounded_decoder_mapped_paper_structure.json"
TARGETS = RECORDS / "paper_result_targets.json"
REGISTER = re.compile(
    rb"(?m)^[ \t]*(\w+)\s+\\(product\[(\d+)\]\.value"
    rb"|carry_save\.row\[(\d+)\]\.(sum|carry)|completed_results)\s*"
    rb"_reg(?:\[(\d+)\])?\[(\d+)\]\s*\(([^;]+)\);"
)
PIN = re.compile(rb"\.(\w+)\s*\(([^()]*)\)")
RESULT_DRIVER = re.compile(rb"\.(Z|ZN|Q|QN)\s*\(\s*out_sums\[(\d+)\]\s*\)")


def verify_array(body, rows, lanes):
    """Check the product, carry-save and completion stages in one mapped array."""
    for direction, names, width in (
        (b"input", rb"operand_a,\s*operand_b", 8 * rows * lanes),
        (b"input", rb"lane_enable", rows * lanes),
        (b"output", rb"out_sums", 19 * rows),
    ):
        pattern = rb"(?m)^[ \t]*" + direction + rb"\s+\[(\d+):0\]\s+" + names + rb"\s*;"
        assert re.findall(pattern, body) == [str(width - 1).encode()], names

    banks = {b"product": set(), b"sum": set(), b"carry": set(), b"completed_results": set()}
    for master, signal, product, row, kind, queue, bit, assignment in REGISTER.findall(body):
        if product:
            bank, index = b"product", int(product)
        elif row:
            bank, index = kind, int(row)
        else:
            bank, index = b"completed_results", int(queue)
            signal += rb"[%d]" % index
        key = index, int(bit)
        assert key not in banks[bank], (bank, key)
        banks[bank].add(key)
        pins = {pin: re.sub(rb"\s+", b"", net) for pin, net in PIN.findall(assignment)}
        assert master.startswith(b"DF") and pins[b"CP"] == b"clk", (bank, key)
        expected = rb"\%s[%s]" % (signal, bit)
        if pins.get(b"Q") != expected:
            assert bank == b"product" and master.startswith(b"DFKCND") and pins[b"QN"] == expected, key

    result_bits = 19 * rows
    assert banks[b"product"] == {(i, b) for i in range(rows * lanes) for b in range(16)}
    assert banks[b"sum"] == {(r, b) for r in range(rows) for b in range(19)}
    assert banks[b"carry"] == {(r, b) for r in range(rows) for b in range(2, 19)}
    assert banks[b"completed_results"] == {(q, b) for q in range(3) for b in range(result_bits)}
    outputs = [int(bit) for _, bit in RESULT_DRIVER.findall(body)]
    assert sorted(outputs) == list(range(result_bits))
    return {name.decode() + "_register_bits": len(bits) for name, bits in banks.items()}


def verify_cluster_ownership(graph, reference, clusters):
    """Trace each reachable cluster and its buffered copies back to the reference."""
    aliases = {}

    def compare(active, original):
        assert graph[active].keys() == reference[original].keys(), (active, original)
        if active != original:
            assert active.startswith("tri_oracle_native_token_map_copy_"), active
            assert aliases.setdefault(active, original) == original, active
        for name, child in graph[active].items():
            compare(child, reference[original][name])

    def resolve(hierarchy, path):
        def walk(master, prefix):
            if prefix == path:
                yield master
            for key, child in hierarchy[master].items():
                instance = prefix + "." + key.removeprefix("\\")
                if instance == path or path.startswith(instance + "."):
                    yield from walk(child, instance)

        master, = walk(TOP, TOP)
        return master

    for cluster in clusters:
        path = cluster["instance"]
        compare(resolve(graph, path), resolve(reference, path))
    assert aliases and len(set(aliases.values())) == len(aliases)
    assert aliases.keys().isdisjoint(aliases.values())
    # Use the audited copies as the family members, leaving unreachable original
    # definitions out of the renamed view.
    normalized = {
        aliases.get(master, master): {key: aliases.get(child, child) for key, child in children.items()}
        for master, children in graph.items() if master not in aliases.values()
    }
    return audit(normalized), len(aliases)


def verify():
    assert __debug__ and not Path("/.dockerenv").exists()
    evidence = {}

    def pin(path, expected=None):
        identity = sha(path)
        assert expected is None or identity == expected, path
        assert evidence.setdefault(str(path.relative_to(ROOT)), identity) == identity, path
        return path

    def artifact(record, suffix):
        (name, identity), = ((name, identity) for name, identity in record["evidence_sha256"].items()
                             if name.endswith(suffix))
        return pin(ROOT / name, identity)

    composition = read(pin(COMPOSITION))
    baseline = read(pin(BASELINE))
    targets = read(pin(TARGETS, baseline["evidence_sha256"][str(TARGETS.relative_to(ROOT))]))
    pin(ROOT / targets["source"], PAPER_SHA256)
    assembly = read(artifact(composition, "/twenty_core_fit/chip/verified.json"))
    replay = read(artifact(composition, "/twenty_core_fit/verified_reset_replays.json"))
    candidate = artifact(assembly, "/twenty_core_fit/chip/buffered.v")
    seed = artifact(assembly, "/twenty_core_fit/chip/seed.def")
    silicon = targets["silicon"]
    rows, lanes = silicon["processing_element_array_per_core"]
    assert silicon["processing_element_precision"] == "signed INT8" and (rows, lanes) == (32, 8)
    assert list(dimensions(seed)) == silicon["die_dimensions_mm"] == baseline["die_mm"]

    graph, macros = compiled_memory_inventory(candidate, seed)
    reference = artifact(baseline, "/bounded_decoder/whole_chip.v")
    assert evidence[str(reference.relative_to(ROOT))] == baseline["candidate_sha256"]
    topology, cluster_copies = verify_cluster_ownership(graph, hierarchy(reference), baseline["clusters"])
    assert topology["clusters"] == baseline["clusters"]
    shared = topology["additional_shared_prediction_instances"]
    assert shared == baseline["additional_shared_prediction_instances"]
    head, = (master for master in shared.values() if master.startswith(SHARED_HEAD))
    strip, = (master for master in shared.values() if master.startswith(SHARED_STRIP))

    arrays = reachable_arrays(graph, TOP)
    listed = Counter(name for case in replay["cases"] for name in case["arrays"])
    assert arrays == listed == Counter(assembly["definitions"].keys())
    assert set(arrays.values()) == {1} and len(arrays) == silicon["clusters"] * silicon["cores_per_cluster"]
    assert all(case["mapped_transactions"] == 786 for case in replay["cases"])
    stages = {}
    prediction_bodies = {}
    with candidate.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as source:
        for match in MODULE.finditer(source):
            name = match[1].decode()
            if name in arrays:
                end = ENDMODULE.search(source, match.end()).start()
                stages[name] = verify_array(source[match.end():end], rows, lanes)
            if name in {head, strip, SIGN_BANK}:
                end = ENDMODULE.search(source, match.end()).start()
                prediction_bodies[name] = source[match.end():end]
    assert stages.keys() == arrays.keys() and all(name.startswith(PE_ARRAY) for name in stages)
    assert len({tuple(counts.items()) for counts in stages.values()}) == 1
    assert {
        "attention_tile_scheduler": scan_head(prediction_bodies[head], graph[head]),
        "feedforward_metadata_and_sign_replay": scan_feedforward(
            prediction_bodies[strip], graph[strip], prediction_bodies[SIGN_BANK]
        ),
    } == baseline["shared_prediction_roles"]

    files = {pin(ROOT / name, digest) for name, digest in baseline["evidence_sha256"].items()
             if Path(name).parent.name in {"LEF", "NLDM", "VERILOG"}}
    sizes = compiler_sizes(files, set(macros.values()))
    roles = memory_roles(macros, sizes)
    memory = baseline["memory"]
    assert sizes == memory["bytes_per_macro_master"]
    assert Counter(macros.values()) == memory["compiled_macro_count_by_master"]
    assert json.loads(json.dumps(roles)) == {key: memory[key] for key in roles}
    total = sum(sizes[master] for master in macros.values())
    assert total == memory["compiled_bytes"] and len(macros) == memory["compiled_macros"]
    assert (total + 512) // 1024 == silicon["sram_published_KB"]
    nominal = 2 * len(arrays) * rows * lanes * targets["peak"]["clock_megahertz"] * 10**6
    assert round(nominal / 10**12, 2) == targets["peak"]["trillion_operations_per_second"]
    pin(candidate)
    pin(seed)
    pin(Path(__file__).resolve())
    return dict(
        state="repacked_whole_chip_structure_and_seed_memory_verified",
        candidate_sha256=evidence[str(candidate.relative_to(ROOT))],
        seed_sha256=evidence[str(seed.relative_to(ROOT))],
        die_mm=silicon["die_dimensions_mm"], clusters=len(topology["clusters"]),
        verified_cluster_hierarchy_aliases=cluster_copies,
        compute=dict(arrays=len(stages), rows=rows, lanes=lanes, operand_bits=8,
                     nominal_operations_per_second_at_paper_clock=nominal,
                     register_bits_per_array=next(iter(stages.values()))),
        memory=dict(macros=len(macros), bytes=total, binary_kibibytes=total / 1024, **roles),
        paper_capacity_label_kb=silicon["sram_published_KB"],
        compiled_capacity_difference_from_binary_label_bytes=total - silicon["sram_published_KB"] * 1024,
        native_reload_verified=False,
        scope="Host audit of mapped geometry, pipeline registers, prediction ownership and fixed "
              "memory in the proposed placement. Nominal throughput assumes the paper clock.",
        evidence_sha256=evidence,
    )


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2, sort_keys=True))
