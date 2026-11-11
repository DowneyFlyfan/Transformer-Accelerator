"""Account for the compiled memories in a particular weight-attention layer replay."""

import argparse
from collections import Counter
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path
import re

from audit_tri_oracle_memory355_accounting import capacity_bytes
from check_tri_oracle_paper300_gate import PAPER_RELATIVE, PAPER_SHA256
from prepare_tri_oracle_wac_outlier_layer import ROOT, read, sha, verify
from replay_mapped_cluster_fixture import BENCH, CENSUS, census, expected_types

FABRIC = f"{BENCH}.dut.feedforward.compute.compute.tensor.fabric"
CLUSTER = re.compile(rf"{re.escape(FABRIC)}\.clusters\[([0-4])\]\.unit\.selected_bank\1\.block_instance\.")
CORE = re.compile(r"source_cluster\.implementation\.cores\[([0-3])\]\.compute\.(.+)")
MODEL = re.compile(r"\bmodule\s+(TS[56]N28\w+)\b")
CORE_ROLES = {"weights": "weight", "inputs": "input", "outputs": "output", "masks": "skip_mask"}
LABELED_CORE_KB = {"weight": 8, "input": 8, "output": 2, "skip_mask": 1}
AGGREGATE = "source_cluster.implementation.aggregate_memory"
MERGE = "source_cluster.implementation.local_merge.token_merge"


def memory_inventory(lines, expected):
    memory = {}
    for line in lines:
        if not line.startswith(CENSUS + " TS"):
            continue
        _, master, hierarchy = line.split(maxsplit=2)
        assert master in expected and hierarchy.endswith(".mapped_hierarchy_probe"), line
        instance = re.sub(r"[\\\s]", "", hierarchy).removesuffix(".mapped_hierarchy_probe")
        assert instance not in memory, instance
        memory[instance] = master
    assert Counter(memory.values()) == expected
    return memory


def capacities_by_owner(memory, mapped_inventory, geometries):
    core_memory = {(cluster, core): {} for cluster in range(5) for core in range(4)}
    core_bytes = {owner: Counter() for owner in core_memory}
    roles = Counter()
    cluster_roles = [Counter() for _ in range(5)]
    cluster_bytes = [0] * 5
    parent = {}
    for instance, master in memory.items():
        size = geometries[master]
        cluster = CLUSTER.match(instance)
        if cluster is None:
            parent[instance] = master
            continue
        bank = int(cluster[1])
        cluster_bytes[bank] += size
        member = instance[cluster.end():]
        core = CORE.fullmatch(member)
        if core:
            owner = (bank, int(core[1]))
            core_memory[owner][core[2]] = master
            role = CORE_ROLES[core[2].split("[", 1)[0]]
            core_bytes[owner][role] += size
        elif re.fullmatch(rf"{re.escape(AGGREGATE)}\[\d+\]", member):
            role = "aggregator_input_output"
        elif re.fullmatch(rf"{re.escape(MERGE)}\.similarity\.shard\.compiled\.compact\.slices\[\d+\]", member):
            role = "survived_sign"
        elif re.fullmatch(rf"{re.escape(MERGE)}\.sizes\.local_sizes\.table_bank\.compiled\.(full|tail)\.entries", member):
            role = "token_merge_table"
        else:
            raise ValueError(f"Unclassified cluster memory: {instance}")
        cluster_roles[bank][role] += size
        roles[role] += size
    assert all(masters == mapped_inventory for masters in core_memory.values())
    assert all(totals == {role: kb * 1024 for role, kb in LABELED_CORE_KB.items()} for totals in core_bytes.values())
    assert all(totals["aggregator_input_output"] == 2 * 1024 for totals in cluster_roles)
    assert parent == {f"{BENCH}.dut.feedforward.predictor.replay_table.{side}_metadata": "TS5N28HPCPSVTA512X64M4F"
                      for side in ("lower", "upper")}
    parent_bytes = sum(geometries[master] for master in parent.values())
    roles["feedforward_prediction_metadata"] = parent_bytes
    return cluster_bytes, parent_bytes, roles, cluster_roles


def audit(case, mapping):
    setup_path = case / "receipt.json"
    setup = read(setup_path)
    assert setup["outlier_owner"] == "core_simd_round_robin" and setup["mapped_banks"] == []
    xcelium = case / "xcelium"
    raw_path = xcelium / "receipt.json"
    raw = read(raw_path)
    assert raw["state"] == "mapped_clusters_passed_integrated_attention_fixture"
    assert raw["elaboration"]["native_exit_status"] == raw["replay"]["native_exit_status"] == 0
    qualification_path = xcelium / ("mapped_wac_qualification.json" if setup.get("mapped_core_netlist")
                                    else "head_offload_qualification.json")
    qualified = read(qualification_path)
    assert qualified["state"] == ("twenty_mapped_compute_cores_replayed_archived_attention" if setup.get("mapped_core_netlist")
                                  else "dynamic_head_offload_replayed_on_twenty_core_layer")
    pins = raw["input_sha256"].copy()
    for path, digest in qualified["input_sha256"].items():
        assert pins.get(path, digest) == digest, path
        pins[path] = digest
    assert pins[str(setup_path)] == sha(setup_path)
    log = xcelium / "positive/console.log"
    assert raw["replay"]["log_sha256"] == pins[str(log)] == sha(log)
    lines = log.read_text().splitlines()
    targets = expected_types(case, setup)
    groups, counts = census(lines, targets, [])
    assert groups == raw["census_groups"] == {"cluster": 5, "source_core": 20, "memory": 623}
    assert counts == raw["elaborated_instances_by_module"]
    expected = {master: count for master, (group, count) in targets.items() if group == "memory"}
    memory = memory_inventory(lines, expected)

    map_path = mapping / "receipt.json"
    mapped = read(map_path)
    assert mapped["state"] == "mapped_core_preserved_verified_processing_array"
    assert mapped["native"]["native_exit_status"] == 0 and mapped["memories"] == 28
    assert mapped["native"]["log_sha256"] == sha(mapping / "console.log")
    for path, digest in mapped["input_sha256"].items():
        assert pins.get(path, digest) == digest, path
        pins[path] = digest
    if setup.get("mapped_core_netlist"):
        assert Path(setup["mapped_core_netlist"]) == mapping / "netlist.v"
        assert pins[setup["mapped_core_netlist"]] == sha(mapping / "netlist.v")
    after = mapping / "after.memory.tsv"
    assert after.read_bytes() == (mapping / "before.memory.tsv").read_bytes()
    mapped_inventory = dict(tuple(line.split()) for line in after.read_text().splitlines())
    assert len(mapped_inventory) == len(after.read_text().splitlines()) == 28

    geometries = {}
    for name in setup["memory_model_paths"]:
        path = Path(name)
        assert pins[str(path)] == sha(path)
        source = path.read_text()
        master, = (module for module in MODEL.findall(source) if module in expected)
        assert master not in geometries, master
        geometries[master] = capacity_bytes(source, master)
    assert geometries.keys() == expected.keys()

    cluster_bytes, parent_bytes, roles, cluster_roles = capacities_by_owner(memory, mapped_inventory, geometries)
    total = sum(cluster_bytes) + parent_bytes
    assert total == sum(roles.values()) == sum(geometries[master] * count for master, count in expected.items())
    paper = ROOT / PAPER_RELATIVE
    paper_targets = ROOT / "records/paper_result_targets.json"
    assert sha(paper) == PAPER_SHA256 and read(paper_targets)["source"] == PAPER_RELATIVE
    published = read(paper_targets)["silicon"]["sram_published_KB"]
    assert published == 405
    comparison = {}
    for scale, unit in ((1000, "decimal_kilobytes"), (1024, "binary_kibibytes")):
        capacity = Decimal(total) / scale
        comparison[unit] = dict(capacity=float(capacity), difference_bytes=total - scale * published,
                                rounds_to_paper_label=int(capacity.quantize(Decimal(1), rounding=ROUND_HALF_UP)) == published)
    pins.update({str(path): sha(path) for path in (Path(__file__), Path(__file__).with_name("audit_tri_oracle_memory355_accounting.py"),
                 paper, paper_targets, raw_path, qualification_path, map_path, after, mapping / "before.memory.tsv", mapping / "console.log")})
    verify(pins)
    return dict(state="replayed_layer_memory_capacity_measured", mapped_compute_cores=setup.get("mapped_compute_leaf_count", 0),
                compiled_memory_instances=len(memory), per_core_instances=len(mapped_inventory), total_bytes=total,
                cluster_bytes=cluster_bytes, parent_bytes=parent_bytes, paper_capacity_label=published,
                bytes_by_role=dict(roles), cluster_bytes_by_role=[dict(item) for item in cluster_roles],
                paper_labeled_memory=dict(architecture_figure="31.6.2", chip_summary_figure="31.6.7",
                                          core_KB=LABELED_CORE_KB, aggregator_input_output_KB=2,
                                          labeled_total_KB=20 * sum(LABELED_CORE_KB.values()) + 5 * 2),
                comparisons=comparison, paper_unit_convention_confirmed=False, input_sha256=pins)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("case", "mapping", "output"):
        parser.add_argument(name, type=lambda value: Path(value).resolve())
    args = parser.parse_args()
    result = audit(args.case, args.mapping)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(result["state"], result["compiled_memory_instances"], result["total_bytes"], result["comparisons"], flush=True)
