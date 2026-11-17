"""Census the paper's redundancy units in a linked whole-chip netlist."""

import argparse
from collections import Counter
from hashlib import file_digest
import json
import mmap
from pathlib import Path
import re

TOP = "tri_oracle_chip_command_layer_parallel_chip"
CLUSTER = re.compile(r"tri_oracle_sram_compute_cluster_.*_verified_bank([0-4])")
CLUSTER_PATH = re.compile(
    r"\.fabric\.clusters\[([0-4])\]\.unit\.selected_bank([0-4])\.block_instance"
    r"\.source_cluster\.implementation$"
)
CORE = re.compile(r"tri_oracle_sram_strip_core448_.*_verified_bank([0-4])")
MODULE = re.compile(rb"(?m)^[ \t]*module\s+([\w$]+)\s*\(")
ENDMODULE = re.compile(rb"(?m)^[ \t]*endmodule\b")
CHILD = re.compile(rb"(?m)^[ \t]*((?:tri_oracle_|TS[56]N28)\w+)\s+(\\\S+|[\w$]+)\s*\(\s*\.")
CLUSTER_MERGER = "tri_oracle_aggregator_token_merge_unit_"
COPIED_TOKEN_MAP = "tri_oracle_native_token_map_copy_"
MEMORY_COMPUTE = "tri_oracle_sram_memory_compute_verified_bank"
PE_ARRAY = "tri_oracle_pe_array_verified_bank"
HEAD_PREDICTOR = "tri_oracle_core_head450_"
STRIP_PREDICTOR = "tri_oracle_core_strip448_"
SHARED_HEAD = "tri_oracle_attention_head_predictor415_"
SHARED_STRIP = "tri_oracle_packed_outlier_replay_"


def hierarchy(netlist, *, include_memory=False):
    """Retain child hierarchy and named connections between module definitions."""
    with netlist.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as source:
        definitions = list(MODULE.finditer(source))
        modules = {definition[1].decode() for definition in definitions}
        if len(modules) != len(definitions):
            raise ValueError("Repeated module definition")
        result = {}
        for index, definition in enumerate(definitions):
            master = definition[1].decode()
            limit = definitions[index + 1].start() if index + 1 < len(definitions) else len(source)
            end = ENDMODULE.search(source, definition.end(), limit)
            if end is None:
                raise ValueError(f"Unterminated module: {master}")
            children = {}
            for match in CHILD.finditer(source, definition.end(), end.start()):
                child, instance = (field.decode() for field in match.groups())
                is_compiled_memory = child.startswith(("TS5N28", "TS6N28"))
                if is_compiled_memory and not include_memory:
                    continue
                if (child not in modules and not is_compiled_memory) or instance in children:
                    raise ValueError(f"Unresolved master or repeated instance in {master}: {child} {instance}")
                children[instance] = child
            result[master] = children
        return result


def audit(graph, top=TOP):
    """Walk reachable instances and verify their exact cluster and core owners."""
    counts = Counter()
    clusters = {}
    shared = {}

    def walk(master, path, parents):
        if master in parents:
            raise ValueError(f"Recursive hierarchy at {path}")
        counts[master] += 1
        declared = CLUSTER.fullmatch(master)
        bank = declared[1] if declared else None
        owner = CLUSTER_PATH.search(path)
        if owner:
            if owner[1] != owner[2] or bank is not None and bank != owner[1]:
                raise ValueError(f"Compute cluster bank differs from its owner at {path}: {master}")
            bank = owner[1]
        if bank is not None:
            if bank in clusters:
                raise ValueError(f"Multiple compute clusters for bank {bank}")
            clusters[bank] = (path, master)
        for prefix in (SHARED_HEAD, SHARED_STRIP):
            if master.startswith(prefix):
                shared[path] = master
        for child, child_master in graph[master].items():
            instance = child.removeprefix("\\")
            walk(child_master, f"{path}.{instance}", parents | {master})

    def require_child(master, name, prefix):
        children = graph[master]
        matches = [child for child, child_master in children.items() if child_master.startswith(prefix)]
        if matches != [name]:
            raise ValueError(f"Wrong {prefix} ownership in {master}: {matches}")
        return children[name]

    walk(top, top, set())
    if set(clusters) != set("01234"):
        raise ValueError(f"Expected five compute clusters, found {sorted(clusters)}")
    inventory = []
    local_mergers = set()
    for bank, (path, master) in sorted(clusters.items()):
        merger_name = r"\local_merge.token_merge"
        merger = graph[master].get(merger_name, "")
        suffix = f"_verified_bank{bank}"
        if merger.startswith(COPIED_TOKEN_MAP):
            controller = require_child(merger, "merge_controller", "tri_oracle_cumulative_merge447_")
            similarity = require_child(merger, "similarity", "tri_oracle_aggregator_sign447_")
            sizes = graph[merger].get("sizes", "")
            if not (controller.endswith(suffix) and similarity.endswith(suffix)
                    and sizes.startswith(("tri_oracle_token_size_bank", COPIED_TOKEN_MAP))):
                raise ValueError(f"Wrong token-merger submodules in {master}: {merger}")
        else:
            require_child(master, merger_name, CLUSTER_MERGER)
            if not merger.endswith(suffix):
                raise ValueError(f"Wrong token-merger bank in {master}: {merger}")
        local_mergers.add(merger)
        core_children = {name: child for name, child in graph[master].items() if CORE.fullmatch(child)}
        if core_children.keys() != {rf"\cores[{core}]" for core in range(4)}:
            raise ValueError(f"Wrong core ownership in {master}: {sorted(core_children)}")
        for core in core_children.values():
            if CORE.fullmatch(core)[1] != bank:
                raise ValueError(f"Wrong core bank in {master}: {core}")
            compute = require_child(core, "compute", MEMORY_COMPUTE)
            require_child(compute, "compute", PE_ARRAY)
            require_child(core, r"\head.predict", HEAD_PREDICTOR)
            require_child(core, r"\strip.predict", STRIP_PREDICTOR)
        inventory.append(dict(bank=int(bank), instance=path, local_token_mergers=1,
                              cores=len(core_children), local_head_predictors=len(core_children),
                              local_strip_predictors=len(core_children)))

    reachable_mergers = {master for master in counts if master.startswith(CLUSTER_MERGER)} | local_mergers
    if len(local_mergers) != 5 or sum(counts[master] for master in reachable_mergers) != 5:
        raise ValueError("Expected one reachable local token merger per compute cluster")
    for family, expected in ((PE_ARRAY, 20),
                             (HEAD_PREDICTOR, 20), (STRIP_PREDICTOR, 20)):
        observed = sum(count for master, count in counts.items() if master.startswith(family))
        if observed != expected:
            raise ValueError(f"Expected {expected} reachable {family} instances, found {observed}")
    return dict(clusters=inventory, additional_shared_prediction_instances=shared)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("netlist", type=Path)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--top", default=TOP, help="Top of the linked chip hierarchy")
    args = parser.parse_args()
    with args.netlist.open("rb") as stream:
        checksum = file_digest(stream, "sha256").hexdigest()
    if checksum != args.sha256:
        raise ValueError(f"Unexpected candidate netlist digest: {checksum}")
    result = audit(hierarchy(args.netlist), args.top)
    with args.netlist.open("rb") as stream:
        if file_digest(stream, "sha256").hexdigest() != checksum:
            raise ValueError("Candidate netlist changed during the census")
    print(json.dumps(dict(candidate_sha256=checksum, **result), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
