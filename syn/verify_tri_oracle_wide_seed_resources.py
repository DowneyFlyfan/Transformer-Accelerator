"""Reconcile the widened whole-chip seed with the paper's memory and compute figures."""

from collections import Counter
from contextlib import ExitStack
from hashlib import sha256
import json
from pathlib import Path

from build_tri_oracle_booth_chip_seed import canonical
from check_tri_oracle_paper300_gate import PAPER_RELATIVE, PAPER_SHA256
from link_tri_oracle_indexed_whole_chip import update_instance
from verify_tri_oracle_booth_chip_compute_geometry import (
    MULTIPLIER, compute_paths, connected_cluster_members, module_text, verify_array,
)
from verify_tri_oracle_booth_chip_geometry import geometry
from verify_tri_oracle_booth_chip_link import named_bindings
from verify_tri_oracle_booth_compiled_memory import logical_memories, memory_poses, unique
from verify_tri_oracle_corrected_booth_roundtrip import ROOT, TOP, digest, read
from verify_tri_oracle_pad_memory import compiler_sizes, memory_roles
from verify_tri_oracle_serialized_placement_transfer import catalog
from verify_tri_oracle_wide_request_trial import MODULE, TX


SEED = Path("records/tri_oracle_wide_request_placement_seed.json")
PLACEMENT = Path("records/tri_oracle_corrected_booth_buffered_placement_roundtrip.json")
COMPILERS = Path("records/tri_oracle_repaired_native_compute_and_memory.json")
TARGETS = Path("records/paper_result_targets.json")
ACCELERATOR = b"chip/chip/normalization/chip/chip/chip/accelerator/"


def macro_roles(macros):
    assert all(path.startswith(ACCELERATOR) for path in macros)
    return unique((path.removeprefix(ACCELERATOR).decode().replace("/", "."), master.decode())
                  for path, master in macros.items())


def native_array(body, rows, lanes, width):
    """Check Innovus's expanded pin lists before applying the existing slice verifier."""
    def modulo_notation(match):
        master, index, raw = match.groups()
        fields = named_bindings(raw)
        low = int(index) * width
        high = low + width - 1
        for pin in ("a", "b"):
            name = b"operand_" + pin.encode()
            expanded = b"{" + b",".join(name + b"[%d]" % bit for bit in range(high, low - 1, -1)) + b"}"
            assert fields[pin] == expanded, (index, pin)
            fields[pin] = name + b"[%d:%d]" % (high, low)
        connections = b", ".join(b".%s(%s )" % (pin.encode(), value) for pin, value in fields.items())
        return rb"  %s \product[%s].recoded.signed_multiplier (%s);" % (master, index, connections)

    normalized = MULTIPLIER.sub(modulo_notation, body)
    return verify_array(normalized, rows, lanes, width)


def same_modules(previous, current, transmitter):
    """Check that the widened link is the sole functional change in the chip."""
    assert current.keys() == previous.keys() | {MODULE}
    top = module_text(previous, TOP)
    assert top.count(b"output [7:0] memory_tx_data;") == 1
    expanded = top.replace(b"output [7:0] memory_tx_data;", b"output [21:0] memory_tx_data;")
    assert module_text(current, TOP) == update_instance(expanded, TX, "request_link", replacement=MODULE)
    assert module_text(current, MODULE) == module_text(transmitter, MODULE)
    for name in previous.keys() - {TOP}:
        old_data, old_start, old_end = previous[name]
        new_data, new_start, new_end = current[name]
        with memoryview(old_data)[old_start:old_end] as old, memoryview(new_data)[new_start:new_end] as new:
            assert old == new, name
    return len(previous) - 1


def verify():
    evidence = {}

    def pin(path, expected=None):
        actual = digest(path)
        assert expected is None or actual == expected, path
        assert evidence.setdefault(str(path), actual) == actual
        return path

    pin(Path(PAPER_RELATIVE), PAPER_SHA256)
    target = read(pin(TARGETS))
    silicon = target["silicon"]
    assert silicon["processing_element_precision"] == "signed INT8"
    wide = read(pin(SEED))
    old = read(pin(PLACEMENT))
    compilers = read(pin(COMPILERS))
    prior = Path(old["database"]).parents[1] / "cold"
    mapped, = (Path(name) for name in wide["evidence_sha256"] if name.endswith("/genus/netlist.v"))
    folder = mapped.parents[1] / "placement_seed"
    baseline, previous_layout = prior / "cold.v", prior / "layout.def"
    candidate, layout = folder / "candidate.v", folder / "seed.def"
    for path in (mapped, baseline, previous_layout, candidate, layout):
        pin(path, wide["evidence_sha256"][str(path)])
    assert evidence[str(candidate)] == wide["candidate_sha256"]
    for path in (baseline, previous_layout):
        assert evidence[str(path)] == old["evidence_sha256"][str(path)]

    previous_macros = unique(memory_poses(previous_layout))
    placed_macros = unique(memory_poses(layout))
    memories = logical_memories(candidate)
    assert memories == {name: pose[0] for name, pose in placed_macros.items()}
    assert previous_macros.keys() == placed_macros.keys()
    relocations = 0
    for name, before in previous_macros.items():
        after = placed_macros[name]
        assert before[0] == after[0] and before[3:] == after[3:], name
        relocations += before[1:3] != after[1:3]
    assert relocations == wide["moved_memory_macros"]
    assert len(memories) == wide["unchanged_memory_halos"] == old["geometry"]["fixed_memory_macros"]

    ownership = macro_roles(memories)
    compiler_views = {pin(Path(name), checksum) for name, checksum in compilers["evidence_sha256"].items()
                      if Path(name).parent.name in {"LEF", "NLDM", "VERILOG"}}
    counts = Counter(ownership.values())
    capacity = compiler_sizes(compiler_views, set(counts))
    roles = memory_roles(ownership, capacity)
    total_bytes = sum(capacity[master] * count for master, count in counts.items())
    assert total_bytes == sum(roles[key] for key in ("core_memory_bytes", "aggregator_io_bytes", "support_memory_bytes"))
    paper_label = silicon["sram_published_KB"]
    assert (total_bytes + 512) // 1024 == paper_label

    rows, lanes = silicon["processing_element_array_per_core"]
    bits = 8
    clusters, cores = silicon["clusters"], silicon["cores_per_cluster"]
    with ExitStack() as stack:
        previous_modules, current_modules, tx = (catalog(stack, [path]) for path in (baseline, candidate, mapped))
        unchanged_modules = same_modules(previous_modules, current_modules, tx)
        arrays = compute_paths(current_modules)
        owners = connected_cluster_members(arrays, clusters, cores)
        array_masters = {master for _, master in arrays}
        assert len(array_masters) == len(arrays) == clusters * cores
        multiplier_masters = set()
        for master in array_masters:
            multiplier_masters.update(native_array(module_text(current_modules, master), rows, lanes, bits))
        assert multiplier_masters <= current_modules.keys()

    bbox, units, _, regions, groups, _ = geometry(layout, verify_top=True)
    assert len(regions) == len(groups) == len(arrays)
    assert {canonical(group).removesuffix(b"/") for group in groups} == set(owners.values())
    die_mm = [(upper - lower) / (1000 * units) for lower, upper in zip(bbox[:2], bbox[2:], strict=True)]
    assert die_mm == silicon["die_dimensions_mm"]
    peak_frequency = target["peak"]["clock_megahertz"]
    peak_ops = len(arrays) * rows * lanes * 2 * peak_frequency * 10**6
    assert round(peak_ops / 10**12, 2) == target["peak"]["trillion_operations_per_second"]

    pin(Path(__file__).resolve().relative_to(ROOT))
    macro_paths = "".join(f"{path}\t{master}\n" for path, master in sorted(ownership.items()))
    return {
        "state": "widened_seed_compute_and_compiled_memory_reconciled",
        "candidate_sha256": evidence[str(candidate)], "seed_sha256": evidence[str(layout)],
        "paper_figures": ["31.6.2", "31.6.7"], "unchanged_predecessor_modules": unchanged_modules,
        "die_mm": die_mm,
        "memory": {
            **roles, "installed_compiler_macro_count": len(ownership), "relocated_macros": relocations,
            "compiler_view_count": len(compiler_views), "macro_owners_sha256": sha256(macro_paths.encode()).hexdigest(),
            "macro_counts_by_master": dict(counts), "bytes_per_macro_master": capacity,
            "installed_bytes": total_bytes, "installed_kib": total_bytes / 1024, "paper_label_kb": paper_label,
            "bytes_above_paper_if_binary": total_bytes - 1024 * paper_label,
            "bytes_above_paper_if_decimal": total_bytes - 1000 * paper_label,
        },
        "compute": {
            "clusters": clusters, "cores_per_cluster": cores, "physical_array_groups": len(groups),
            "rows_per_array": rows, "lanes_per_row": lanes, "signed_operand_bits": bits,
            "multiplier_instances": len(arrays) * rows * lanes, "clock_target_megahertz": peak_frequency,
            "ideal_peak_operations_per_second": peak_ops,
        },
        "scope": "Exact widened netlist and coordinate seed. The reported memory label reconciles at rounded "
                 "binary precision, and the paper does not disclose an exact byte count. The nominal compute "
                 "rate assumes every lane issues a multiply and an add each cycle at the target clock. "
                 "Native import, achieved clock frequency, model replay and timing remain separate.",
        "evidence_sha256": evidence,
    }


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").is_file()
    print(json.dumps(verify(), indent=2, sort_keys=True))
