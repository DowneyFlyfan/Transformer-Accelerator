"""Audit a native instance inventory against the disclosed Tri-Oracle topology."""

from collections import Counter, defaultdict
from pathlib import Path
import re


MEMORY_GEOMETRIES = {
    "sram_32x128": (32, 128, 0),
    "sram_512x64": (512, 64, 0),
    "sram_16x128": (16, 128, 0),
}
REDUNDANCY_ROLES = ("token_merger", "head_predictor", "strip_predictor", "causal_token_size")
INVENTORY_ROLES = {
    "cluster", "core", "pe", "similarity_shard", "weight_attention_core",
    *REDUNDANCY_ROLES, *MEMORY_GEOMETRIES,
}


def read_inventory(path: Path, dut: str):
    """Return unique instance paths and native parameters within the selected design."""
    instances = defaultdict(dict)
    seen = set()
    for line in path.read_text().splitlines():
        role, instance, rows, columns, width = line.split()
        if role not in INVENTORY_ROLES:
            raise ValueError(f"Unknown native role: {role}")
        if not instance.startswith(dut + ".") or not instance.endswith(".inventory445"):
            raise ValueError(f"Inventory entry outside the selected design: {instance}")
        instance = instance.removesuffix(".inventory445")
        if instance in seen:
            raise ValueError(f"Duplicate native instance: {instance}")
        seen.add(instance)
        instances[role][instance] = (int(rows), int(columns), int(width))
    return instances


def _parent(instance, owners):
    enclosing = [owner for owner in owners if instance.startswith(owner + ".")]
    if len(enclosing) > 1:
        raise ValueError(f"Ambiguous ownership of {instance}")
    return enclosing[0] if enclosing else None


def _memory_role(instance, cores, clusters, mergers, shards):
    core = _parent(instance, cores)
    if core is not None:
        leaf = instance.removeprefix(core + ".")
        bank = re.fullmatch(r"(weights|inputs|outputs|masks)\[\d+\]", leaf)
        if bank:
            return f"core_{bank[1]}"
    cluster = _parent(instance, clusters)
    if cluster is not None and re.fullmatch(
        r"aggregate_memory\[\d+\]", instance.removeprefix(cluster + ".")
    ):
        return "aggregator_io"
    if _parent(instance, mergers) is not None and re.search(r"\.compiled_signs\.slices\[\d+\]$", instance):
        return "surviving_sign_bank"
    shard = _parent(instance, shards)
    if shard is not None and re.fullmatch(r"compiled\.slices\[\d+\]", instance.removeprefix(shard + ".")):
        return "surviving_sign_bank"
    if instance.endswith((".replay_table.lower_metadata", ".replay_table.upper_metadata")):
        return "prediction_metadata"
    raise ValueError(f"Unrecognized compiled-memory role: {instance}")


def audit(instances):
    """Measure the paper-facing topology dimensions visible in the native source hierarchy."""
    clusters = instances["cluster"]
    cores = instances["core"]
    mergers = instances["token_merger"]
    shards = instances.get("similarity_shard", {})
    core_owner = {core: _parent(core, clusters) for core in cores}
    pe_owner = {pe: _parent(pe, cores) for pe in instances["pe"]}
    if None in core_owner.values() or None in pe_owner.values():
        raise ValueError("Detached compute core or processing-element array")
    work_cores = instances.get("weight_attention_core", {})
    compute_by_work_core = {}
    if work_cores:
        for core in cores:
            owner = _parent(core, work_cores)
            if owner is None or owner in compute_by_work_core or _parent(owner, clusters) != core_owner[core]:
                raise ValueError(f"Invalid weight-attention core ownership: {core}")
            compute_by_work_core[owner] = core
        if set(compute_by_work_core) != set(work_cores):
            raise ValueError("Weight-attention core without a compute block")

    def predictor_owner(unit):
        compute = _parent(unit, cores)
        if compute is not None:
            return compute
        return compute_by_work_core.get(_parent(unit, work_cores))

    shards_by_merger = defaultdict(list)
    shard_aggregators = {}
    shared_mergers = [merger for merger in mergers if _parent(merger, clusters) is None]
    for shard, (features, rows, unused) in shards.items():
        merger = _parent(shard, mergers)
        aggregator = _parent(shard, clusters)
        if merger is None and aggregator is not None and len(shared_mergers) == 1:
            merger = shared_mergers[0]
        if merger is None or rows != mergers[merger][0] or features <= 0 or unused != 0:
            raise ValueError(f"Invalid token-similarity shard: {shard}")
        shards_by_merger[merger].append(shard)
        shard_aggregators[shard] = aggregator
    for merger, children in shards_by_merger.items():
        if sum(shards[shard][0] for shard in children) != mergers[merger][2]:
            raise ValueError(f"Token-similarity shards do not cover all features: {merger}")

    core_counts = Counter(core_owner.values())
    pe_counts = Counter(pe_owner.values())
    per_cluster_mergers = Counter(_parent(merger, clusters) for merger in mergers)
    per_core_heads = Counter(predictor_owner(unit) for unit in instances["head_predictor"])
    per_core_strips = Counter(predictor_owner(unit) for unit in instances["strip_predictor"])

    memory_counts = Counter()
    memory_bytes = Counter()
    shard_banks = Counter()
    for master, geometry in MEMORY_GEOMETRIES.items():
        for instance, parameters in instances[master].items():
            if parameters != geometry:
                raise ValueError(f"Unexpected compiled-memory geometry: {instance} {parameters}")
            role = _memory_role(instance, cores, clusters, mergers, shards)
            memory_counts[role] += 1
            memory_bytes[role] += geometry[0] * geometry[1] // 8
            shard = _parent(instance, shards)
            if shard is not None:
                if master != "sram_32x128":
                    raise ValueError(f"Unexpected compiled sign-memory master: {instance}")
                shard_banks[shard] += 1
    for children in shards_by_merger.values():
        if any(shard_banks[shard] for shard in children):
            for shard in children:
                if shard_banks[shard] != (shards[shard][0] + 127) // 128:
                    raise ValueError(f"Wrong compiled sign-memory slice count: {shard}")

    return {
        "cluster_count": len(clusters),
        "core_count": len(cores),
        "core_counts_by_cluster": sorted(core_counts[cluster] for cluster in clusters),
        "weight_attention_core_count": len(work_cores),
        "array_count": len(pe_owner),
        "array_shapes": sorted(set(instances["pe"].values())),
        "native_similarity_shards": [
            {
                "instance": shard,
                "features": shards[shard][0],
                "compiled_memory_slices": shard_banks[shard],
                "aggregator": shard_aggregators[shard],
            }
            for shard in sorted(shards)
        ],
        "compiled_memory_instances": sum(memory_counts.values()),
        "compiled_memory_bytes": sum(memory_bytes.values()),
        "compiled_memory_roles": {
            role: {"instances": memory_counts[role], "bytes": memory_bytes[role]}
            for role in sorted(memory_counts)
        },
        "native_redundancy_units": {
            role: sorted(instances[role])
            for role in REDUNDANCY_ROLES
        },
        "paper_topology_checks": {
            "five_clusters_with_four_cores_each": len(clusters) == 5 and all(
                core_counts[cluster] == 4 for cluster in clusters
            ),
            "one_32_by_8_eight_bit_array_per_core": len(cores) == 20
            and all(pe_counts[core] == 1 for core in cores)
            and all(shape == (32, 8, 8) for shape in instances["pe"].values()),
            "one_token_merger_per_cluster": len(mergers) == 5 and len(clusters) == 5
            and all(per_cluster_mergers[cluster] == 1 for cluster in clusters),
            "attention_head_predictor_in_each_core": len(instances["head_predictor"]) == 20
            and len(cores) == 20 and all(per_core_heads[core] == 1 for core in cores),
            "strip_predictor_in_each_core": len(instances["strip_predictor"]) == 20
            and len(cores) == 20 and all(per_core_strips[core] == 1 for core in cores),
        },
    }
