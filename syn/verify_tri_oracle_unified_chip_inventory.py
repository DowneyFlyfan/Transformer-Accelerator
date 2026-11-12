"""Count the unified chip's elaborated arithmetic arrays and compiled memories."""

import argparse
from collections import Counter
import json
from pathlib import Path
import re

from audit_tri_oracle_memory355_accounting import capacity_bytes
from audit_tri_oracle_wac_memory_capacity import BENCH, capacities_by_owner
from check_tri_oracle_paper300_gate import PAPER_RELATIVE, PAPER_SHA256
from verify_tri_oracle_packed_down_weights import ROOT, sha256


PHYSICAL = ROOT / ".cache/physical"
CHIP = PHYSICAL / "wide_weight_loader/unified_chip"
NATIVE_TOP = "tri_oracle_batched406_learned_tb"
SOURCE_PREFIX = f"{NATIVE_TOP}.dut.layer.layer."
REFERENCE = PHYSICAL / "shared_memory_layer_boundary/physical_inputs/native_memory_partition_receipt.json"
CORE_INVENTORY = PHYSICAL / "wac_mapped_pe_outlier_core/after.memory.tsv"
MEMORY_LINE = "TRI_ORACLE_SOURCE_MEMORY "
ARRAY_LINE = "TRI_ORACLE_SOURCE_ARRAY "


def pin(pins, path, expected=None):
    name = str(path.relative_to(ROOT))
    digest = sha256(path)
    assert expected is None or expected == digest, path
    assert pins.setdefault(name, digest) == digest, path


def verify(pins):
    assert all(sha256(ROOT / path) == expected for path, expected in pins.items())


def prepare(output):
    chip_record = ROOT / "records/wac_unified_chip_commands_result.json"
    result = json.loads(chip_record.read_text())
    assert result["state"] == "mapped_chip_commands_verified_on_unified_read_source_decoder"
    prepared = CHIP / "prepared.json"
    inputs = json.loads(prepared.read_text())
    pins = inputs["input_sha256"]
    pin(pins, prepared, result["evidence_sha256"][str(prepared.relative_to(ROOT))])
    pin(pins, chip_record)
    verify(pins)
    assert inputs["controller_sha256"] == result["controller_sha256"]

    baseline_record = ROOT / "records/wac_shared_memory_layer_native_attention_result.json"
    known = json.loads(baseline_record.read_text())
    assert known["state"] == "fully_mapped_shared_memory_attention_and_memory_inventory_verified"
    pin(pins, baseline_record)
    pin(pins, REFERENCE, known["evidence_sha256"][str(REFERENCE.relative_to(ROOT))])
    reference = json.loads(REFERENCE.read_text())
    assert reference["state"] == "native_memory_inventory_verified"
    for path in (CORE_INVENTORY, ROOT / PAPER_RELATIVE, ROOT / "records/paper_result_targets.json"):
        pin(pins, path, reference["input_sha256"][str(path)])
    assert pins[PAPER_RELATIVE] == PAPER_SHA256
    pe = ROOT / "verilog/tri_oracle_pe_array.sv"
    assert re.findall(r"\$signed\(operand_([ab])\[p\*DATA_W \+: DATA_W\]\)", pe.read_text()) == ["a", "b"]
    assert str(pe.relative_to(ROOT)) in pins

    source = CHIP / "bundle.sv"
    includes = tuple(Path(path) for path in re.findall(r'(?m)^`include "([^"]+)"$', source.read_text()))
    models = {}
    for model in (path for path in includes if path.parent.name == "VERILOG"):
        text = model.read_text()
        master, = (name for name in re.findall(r"(?m)^\s*module\s+(TS[56]N28\w+)\s*\(", text)
                   if name in reference["by_master"])
        assert master in reference["by_master"] and master not in models
        size = reference["by_master"][master]
        assert capacity_bytes(text, master) == size["words"] * size["bits_per_word"] // 8
        pin(pins, model, reference["input_sha256"][str(model)])
        directory = model.parent.parent
        abstract = directory / "LEF" / f"{directory.name}.lef"
        pin(pins, abstract, reference["input_sha256"][str(abstract)])
        for corner in reference["corners"]:
            view, = (Path(name) for name in reference["input_sha256"]
                     if name.endswith(f"_{corner}.lib") and Path(name).parent.parent == directory)
            pin(pins, view, reference["input_sha256"][str(view)])
        models[master] = ("numWord", "numBit") if master.startswith("TS5") else ("W", "N")
    assert models.keys() == reference["by_master"].keys()

    output.mkdir()
    monitor = output / "inventory_probe.sv"
    probe = """`timescale 1ns/1ps
module tri_oracle_source_memory_probe #(parameter string MASTER="", parameter int WORDS=0, WIDTH=0) ();
  initial $display("TRI_ORACLE_SOURCE_MEMORY %s %0d %0d %m", MASTER, WORDS, WIDTH);
endmodule
module tri_oracle_source_array_probe #(parameter int ROWS=0, LANES=0, WIDTH=0) ();
  initial $display("TRI_ORACLE_SOURCE_ARRAY %0d %0d %0d %m", ROWS, LANES, WIDTH);
endmodule
bind tri_oracle_pe_array tri_oracle_source_array_probe #(.ROWS(LINES), .LANES(LANES), .WIDTH(DATA_W)) inventory_probe ();
"""
    monitor.write_text(probe + "".join(
        f'bind {master} tri_oracle_source_memory_probe #(.MASTER("{master}"), '
        f'.WORDS({depth}), .WIDTH({width})) inventory_probe ();\n'
        for master, (depth, width) in sorted(models.items())))
    bundle = output / "bundle.sv"
    bundle.write_text(source.read_text() + f'`include "{monitor}"\n')
    for path in (monitor, bundle, Path(__file__)):
        pin(pins, path)
    (output / "prepared.json").write_text(json.dumps({
        "state": "unified_chip_source_inventory_probe_prepared",
        "controller_sha256": result["controller_sha256"], "input_sha256": pins,
    }, indent=2) + "\n")


def runtime_inventory(text, reference, target, core_inventory):
    memories, arrays, dimensions = {}, {}, {}
    for line in text.splitlines():
        if line.startswith(MEMORY_LINE):
            _, master, depth, width, path = line.split(maxsplit=4)
            path = re.sub(r"[\\\s]", "", path)
            assert path.startswith(SOURCE_PREFIX) and path.endswith(".inventory_probe")
            normalized = f"{BENCH}.dut." + path.removeprefix(SOURCE_PREFIX).removesuffix(".inventory_probe")
            assert normalized not in memories
            shape = int(depth), int(width)
            assert dimensions.setdefault(master, shape) == shape
            memories[normalized] = master
        elif line.startswith(ARRAY_LINE):
            _, rows, lanes, width, path = line.split(maxsplit=4)
            path = re.sub(r"[\\\s]", "", path)
            assert path.startswith(SOURCE_PREFIX) and path.endswith(".inventory_probe")
            assert path not in arrays
            arrays[path] = int(rows), int(lanes), int(width)

    silicon = target["silicon"]
    banks, cores = silicon["clusters"], silicon["cores_per_cluster"]
    rows, lanes = silicon["processing_element_array_per_core"]
    expected_paths = {
        SOURCE_PREFIX + f"feedforward.compute.compute.tensor.fabric.clusters[{bank}].unit."
        f"selected_bank{bank}.block_instance.source_cluster.implementation.cores[{core}].compute.compute.inventory_probe"
        for bank in range(banks) for core in range(cores)
    }
    assert arrays.keys() == expected_paths
    assert set(arrays.values()) == {(rows, lanes, 8)} and silicon["processing_element_precision"] == "signed INT8"

    counts = Counter(memories.values())
    geometry = {master: depth * width // 8 for master, (depth, width) in dimensions.items()}
    actual = {master: {"instances": count, "words": dimensions[master][0], "bits_per_word": dimensions[master][1],
                       "bytes": count * geometry[master]} for master, count in sorted(counts.items())}
    assert actual == reference["by_master"]
    cluster_bytes, parent_bytes, roles, cluster_roles = capacities_by_owner(memories, core_inventory, geometry)
    total = sum(cluster_bytes) + parent_bytes
    assert roles == reference["bytes_by_role"] and cluster_roles == reference["cluster_bytes_by_role"]
    assert len(memories) == reference["compiled_instances"] and sum(roles.values()) == total == reference["bytes"]
    label = silicon["sram_published_KB"]
    peak = len(arrays) * rows * lanes * 2 * target["peak"]["clock_megahertz"] * 10**6
    assert round(peak / 10**12, 2) == target["peak"]["trillion_operations_per_second"]
    return {
        "clusters": banks, "cores": len(arrays), "processing_element_rows": rows, "processing_element_lanes": lanes,
        "signed_operand_bits": 8, "nominal_ops_per_second_at_paper_clock": peak,
        "compiled_instances": len(memories), "compiled_bytes": total, "by_master": actual, "bytes_by_role": roles,
        "paper_capacity_label_kb": label, "compiled_kibibytes": total / 1024,
        "difference_from_binary_label_bytes": total - label * 1024,
        "difference_from_decimal_label_bytes": total - label * 1000,
    }


def audit(output, log):
    prepared = output / "prepared.json"
    setup = json.loads(prepared.read_text())
    assert setup["state"] == "unified_chip_source_inventory_probe_prepared"
    pins = setup["input_sha256"]
    verify(pins)
    text = log.read_text()
    assert text.splitlines().count("UNIFIED_CHIP_FEEDFORWARD_PASS descriptor_words=15 commands=1 responses=1") == 1
    assert text.count("Simulation complete via $finish(1)") == 1 and not re.search(r"\*(?:E|F),", text)
    reference = json.loads(REFERENCE.read_text())
    target = json.loads((ROOT / "records/paper_result_targets.json").read_text())
    core_inventory = dict(line.split() for line in CORE_INVENTORY.read_text().splitlines())
    observed = runtime_inventory(text, reference, target, core_inventory)
    verify(pins)
    for path in (prepared, log):
        pin(pins, path)
    result = {
        "state": "unified_chip_elaborated_source_memory_and_arithmetic_inventory_verified",
        "controller_sha256": setup["controller_sha256"],
        **observed, "input_sha256": pins,
        "scope": "Source elaboration with compiled memory models and mapped chip command controller. "
                 "The paper's KB label is retained and compared using both byte conventions.",
    }
    with (output / "receipt.json").open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(result["state"], observed["cores"], observed["compiled_instances"], observed["compiled_bytes"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "audit"))
    parser.add_argument("output", type=Path)
    parser.add_argument("--log", type=Path)
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args.output.resolve())
    else:
        audit(args.output.resolve(), args.log.resolve())
