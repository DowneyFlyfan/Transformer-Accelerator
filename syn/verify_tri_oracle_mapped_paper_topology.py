"""Audit the mapped decoder's paper-facing topology and compiled memory census."""

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import resource

from audit_compact_mapped_architecture import array_registers
from audit_linked_layer_memory import inventory
from audit_tri_oracle_wac_memory_capacity import BENCH, capacities_by_owner
from check_tri_oracle_paper300_gate import PAPER_RELATIVE, PAPER_SHA256, sha
from verify_linked_placed_topology import module_index, parse_module, pin_fields
from verify_tri_oracle_shared_memory import CORNERS, check_native_census, memory_shape, require


ROOT = Path(__file__).resolve().parents[1]
PHYSICAL = ROOT / ".cache/physical"
REFERENCE = PHYSICAL / "shared_memory_layer_boundary/physical_inputs/native_memory_partition_receipt.json"
CORE_INVENTORY = PHYSICAL / "wac_mapped_pe_outlier_core/after.memory.tsv"
REPLAY_TOP = "tri_oracle_attention430_tb"


def read(path):
    return json.loads(path.read_text())


def audit_topology(code, top, targets):
    spans = module_index(code)
    views = {}

    def view(master):
        if master not in views:
            _, ports, _, children, _ = parse_module(code, spans[master])
            views[master] = ports, children
        return views[master]

    def trace(master, *path):
        for name in path:
            master = view(master)[1][name][0]
        return master

    def typed_child(master, name, prefix):
        children = view(master)[1]
        matched = [instance for instance, (cell, _) in children.items() if cell.startswith(prefix)]
        require(matched == [name], f"{master} requires one {prefix} at {name}")
        child, fields = children[name]
        return child, pin_fields(fields)

    def signal(fields, port, name):
        require(re.search(rf"\b{re.escape(name)}\b", fields.get(port, "")) is not None,
                f"Port {port} does not carry {name}")

    def routed_predictor(core_master, kind, prefix):
        child, pins = typed_child(core_master, rf"\{kind}.predict", prefix)
        require(pins.get("clk") == "clk" and pins.get("rst_n") == "strip_rst_n",
                f"{kind} predictor is disconnected from the core clock or reset")
        for port in ("request", "response"):
            signal(pins, port, f"{kind}_{port}")
        return child

    silicon = targets["silicon"]
    rows, lanes = silicon["processing_element_array_per_core"]
    cores_per_cluster = silicon["cores_per_cluster"]
    clusters = silicon["clusters"]
    require(silicon["processing_element_precision"] == "signed INT8", "Unexpected paper operand width")
    layer = trace(top, "layer")
    fabric = trace(layer, "feedforward", "compute", "compute", "tensor", "fabric")
    members = view(fabric)[1]
    require({name for name in members if re.fullmatch(r"\\clusters\[\d+\]\.unit", name)} ==
            {rf"\clusters[{bank}].unit" for bank in range(clusters)}, "Mapped cluster inventory differs")
    banks = []
    arrays = {}
    for bank in range(clusters):
        implementation = trace(fabric, rf"\clusters[{bank}].unit", rf"\selected_bank{bank}.block_instance",
                               "source_cluster", "implementation")
        members = view(implementation)[1]
        require({name for name in members if re.fullmatch(r"\\cores\[\d+\]", name)} ==
                {rf"\cores[{core}]" for core in range(cores_per_cluster)}, "Mapped core inventory differs")
        merger, merge_pins = typed_child(implementation, r"\local_merge.token_merge",
                                         "tri_oracle_aggregator_token_merge_unit")
        for port, name in ((r"\command[cfg_valid]", "merge_range_command"),
                           (r"\result[map_valid]", "merge_range_result"),
                           (r"\size_command[begin_query]", "token_size_bank_command"),
                           (r"\size_result[out_count]", "token_size_bank_result"),
                           ("sign_data", "merge_sign_data")):
            signal(merge_pins, port, name)
        controller, _ = typed_child(merger, "merge_controller", "tri_oracle_cumulative_merge447")
        similarity, _ = typed_child(merger, "similarity", "tri_oracle_aggregator_sign447")
        sizes, _ = typed_child(merger, "sizes", "tri_oracle_token_size_bank")
        core_report = []
        for core in range(cores_per_cluster):
            instance = rf"\cores[{core}]"
            master, raw = members[instance]
            pins = pin_fields(raw)
            for kind in ("head", "strip"):
                for port in ("request", "response"):
                    signal(pins, f"{kind}_{port}", f"core_{kind}_{port}s")
            head = routed_predictor(master, "head", "tri_oracle_core_head450")
            strip = routed_predictor(master, "strip", "tri_oracle_core_strip448")
            classifier, _ = typed_child(head, "classifier", "tri_oracle_attention_head_classifier410")
            array = trace(master, "compute", "compute")
            require(array.startswith("tri_oracle_pe_array_verified_bank"), f"Unrecognized compute array {array}")
            if array not in arrays:
                arrays[array] = array_registers(code, spans[array], rows, lanes, 8)
            core_report.append({"core": core, "array": array, "head": head,
                                "head_classifier": classifier, "strip": strip})
        banks.append({"cluster": bank, "cluster_master": implementation, "token_merger": merger,
                      "merge_controller": controller, "sign_similarity": similarity,
                      "token_size_bank": sizes, "cores": core_report})

    peak = clusters * cores_per_cluster * rows * lanes * 2 * targets["peak"]["clock_megahertz"] * 10**6
    require(round(peak / 10**12, 2) == targets["peak"]["trillion_operations_per_second"],
            "Nominal peak operation count differs from the paper")
    ports, top_members = view(top)
    return {"clusters": banks, "array_geometry": [rows, lanes], "operand_bits": 8,
            "array_registers_by_master": arrays, "nominal_operations_per_second_at_paper_clock": peak,
            "decoder_external_clock": ports["clk"][0] == "input",
            "decoder_hierarchy_children": {name: cell for name, (cell, _) in top_members.items()
                                           if cell in spans}}


def audit_memory(mapped, included, reference, pin):
    counts = Counter(mapped.values())
    models = {}
    for model in included:
        if model.parent.name != "VERILOG":
            continue
        pin(model, reference["input_sha256"][str(model)])
        source = model.read_text()
        matches = [master for master in counts if re.search(rf"\bmodule\s+{re.escape(master)}\b", source)]
        require(len(matches) == 1 and matches[0] not in models, f"Unexpected compiler model: {model}")
        models[matches[0]] = model, source
    require(counts.keys() == models.keys(), "Mapped memory masters and compiler models differ")
    details = {}
    for master, count in sorted(counts.items()):
        model, source = models[master]
        compiler = model.parent.parent
        abstract = compiler / "LEF" / f"{compiler.name}.lef"
        pin(abstract, reference["input_sha256"][str(abstract)])
        require(re.findall(r"(?m)^\s*MACRO\s+(\w+)\s*$", abstract.read_text()) == [master],
                f"Unexpected physical abstract: {master}")
        geometry = set()
        for corner in CORNERS:
            library, = (Path(name) for name in reference["input_sha256"]
                        if name.endswith(f"_{corner}.lib") and Path(name).parent.parent == compiler)
            pin(library, reference["input_sha256"][str(library)])
            geometry.add(memory_shape(source, library.read_text(), master))
        require(len(geometry) == 1, f"Memory geometry differs across corners: {master}")
        depth, width = geometry.pop()
        details[master] = {"instances": count, "words": depth, "bits_per_word": width,
                           "bytes": count * depth * width // 8}
    pin(CORE_INVENTORY, reference["input_sha256"][str(CORE_INVENTORY)])
    core = dict(line.split() for line in CORE_INVENTORY.read_text().splitlines())
    require(all(name.startswith("layer.") for name in mapped), "Memory outside the shared decoder layer")
    layer = {f"{BENCH}.dut.{name.removeprefix('layer.')}": master for name, master in mapped.items()}
    sizes = {master: value["words"] * value["bits_per_word"] // 8 for master, value in details.items()}
    cluster_bytes, parent_bytes, roles, cluster_roles = capacities_by_owner(layer, core, sizes)
    total = sum(item["bytes"] for item in details.values())
    require(total == sum(cluster_bytes) + parent_bytes == sum(roles.values()), "Memory accounting disagrees")
    return {"compiled_instances": len(mapped), "compiled_bytes": total, "by_master": details,
            "bytes_by_role": dict(roles), "bytes_by_cluster": cluster_bytes,
            "cluster_bytes_by_role": [dict(item) for item in cluster_roles]}


def paper_reference(pin):
    reference_path = ROOT / "records/wac_shared_memory_layer_native_attention_result.json"
    pin(reference_path)
    pin(REFERENCE, read(reference_path)["evidence_sha256"][str(REFERENCE.relative_to(ROOT))])
    reference = read(REFERENCE)
    targets_path = ROOT / "records/paper_result_targets.json"
    pin(targets_path, reference["input_sha256"][str(targets_path)])
    pin(ROOT / PAPER_RELATIVE, PAPER_SHA256)
    targets = read(targets_path)
    require(targets["source"] == PAPER_RELATIVE, "Paper target source changed")
    return reference, targets


def audit_chip_hierarchy(code, top, native_memories, included, pin):
    """Check the paper-facing hierarchy on the exact chip netlist replayed by Xcelium."""
    reference, targets = paper_reference(pin)
    memory = inventory(code, top)
    require(memory == native_memories, "Chip netlist and native memory census differ")
    prefix = "layer."
    require(all(path.startswith(prefix) for path in memory), "Memory outside the verified decoder hierarchy")
    spans = module_index(code)
    _, ports, _, children, _ = parse_module(code, spans[top])
    decoder, fields = children["layer"]
    connections = pin_fields(fields)
    require(ports["clk"] == ("input", None) and "clk" in connections, "Missing chip clock connection")
    topology = audit_topology(code, decoder, targets)

    decoder_memory = {path.removeprefix(prefix): master for path, master in memory.items()}
    capacity = audit_memory(decoder_memory, included, reference, pin)
    for helper in (inventory, array_registers, module_index, capacities_by_owner, memory_shape):
        pin(Path(helper.__code__.co_filename))
    pin(Path(__file__))
    label = targets["silicon"]["sram_published_KB"]
    return {
        "decoder_module": decoder,
        "chip_clock_port": "clk",
        "decoder_clock_connection": connections["clk"].strip(),
        "external_clock_direct_to_decoder": connections["clk"].strip() == "clk",
        "topology": topology,
        "memory": capacity,
        "paper_sram_label_kb": label,
        "difference_from_binary_label_bytes": capacity["compiled_bytes"] - label * 1024,
        "difference_from_decimal_label_bytes": capacity["compiled_bytes"] - label * 1000,
    }


def audit(candidate, replay):
    require(__debug__, "Run this verifier with Python assertions enabled")
    evidence = {}

    def pin(path, expected=None):
        current = sha(path)
        require(expected is None or current == expected, f"Evidence digest changed: {path}")
        require(evidence.setdefault(str(path), current) == current, f"Evidence changed during audit: {path}")
        return current

    link = candidate / "receipt.json"
    netlist = candidate / "candidate.v"
    pin(link)
    linked = read(link)
    netlist_sha = pin(netlist, linked["candidate_netlist_sha256"])
    code = netlist.read_text()
    reference, targets = paper_reference(pin)

    bundle = replay / "bundle.sv"
    elaborate = replay / "elaborate/xrun.log"
    smoke = replay / "smoke/xrun.log"
    for path in (bundle, elaborate, smoke, Path(__file__)):
        pin(path)
    included = tuple(Path(path) for path in re.findall(r'(?m)^\s*`include\s+"([^"]+)"\s*$', bundle.read_text()))
    require(included.count(netlist) == 1, "Native bundle does not include the candidate once")
    for path in included:
        pin(path)
    build_log = elaborate.read_text()
    smoke_log = smoke.read_text()
    snapshot = f"\t-xmlibdirname {replay/'xcelium.d'}"
    require(f"\t{bundle}" in build_log and f"file: {bundle}" in build_log
            and f"Writing initial simulation snapshot: worklib.{REPLAY_TOP}:sv" in build_log
            and snapshot in build_log and snapshot in smoke_log
            and f"Loading snapshot worklib.{REPLAY_TOP}:sv" in smoke_log
            and smoke_log.splitlines().count("LINKED_CONTEXT_SMOKE_PASS merged=576 restored=576") == 1
            and smoke_log.count("Simulation complete via $finish(1)") == 1
            and not re.search(r"\*[EF],", build_log + smoke_log)
            and "Exiting on " in smoke_log.splitlines()[-1],
            "The selected native smoke replay did not complete on the candidate snapshot")
    mapped = inventory(code, linked["top"])
    check_native_census(smoke_log.splitlines(), f"{REPLAY_TOP}.dut.", mapped)
    topology = audit_topology(code, linked["top"], targets)
    memory = audit_memory(mapped, included, reference, pin)
    for helper in (inventory, array_registers, module_index, capacities_by_owner, check_native_census):
        pin(Path(helper.__code__.co_filename))
    require(all(sha(path) == expected for path, expected in evidence.items()), "Evidence changed during audit")
    label = targets["silicon"]["sram_published_KB"]
    total = memory["compiled_bytes"]
    return {
        "state": "mapped_decoder_local_redundancy_topology_and_native_memory_verified",
        "candidate_netlist_sha256": netlist_sha, "mapped_top": linked["top"],
        "topology": topology, "memory": memory, "paper_sram_label_kb": label,
        "compiled_kibibytes": total / 1024,
        "difference_from_binary_label_bytes": total - label * 1024,
        "difference_from_decimal_label_bytes": total - label * 1000,
        "paper_byte_convention_confirmed": False,
        "scope": "Mapped decoder hierarchy, selected local control connections, and native compiled-memory "
                 "census. The top command controller, on-chip clock generation and memory transport at "
                 "the physical chip boundary require separate candidate evidence.",
        "input_sha256": evidence,
    }


if __name__ == "__main__":
    resource.setrlimit(resource.RLIMIT_AS, (2**31, 2**31))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=lambda value: Path(value).resolve())
    parser.add_argument("replay", type=lambda value: Path(value).resolve())
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = audit(args.candidate, args.replay)
    with args.output.open("x") as stream:
        stream.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(result["state"], len(result["topology"]["clusters"]), result["memory"]["compiled_instances"],
          result["memory"]["compiled_bytes"], flush=True)
