"""Reconcile the cold pad-reserved placement's compiled memory with the paper."""

from collections import Counter, defaultdict
import json
from pathlib import Path
import re

from audit_tri_oracle_memory355_accounting import capacity_bytes
from verify_tri_oracle_buffered_memory import IMPORT, PAPER_SHA256, placed_memory, replay_memory
from verify_tri_oracle_pad_restored_models import ROOT, WORK, sha, verify as verify_restored_models

CLUSTER_PATH = (
    r"layer\.layer\.feedforward\.compute\.compute\.tensor\.fabric\.clusters\[([0-4])\]"
    r"\.unit\.selected_bank\1\.block_instance\.source_cluster\.implementation\."
)
CORE_MEMORY = re.compile(CLUSTER_PATH + r"cores\[([0-3])\]\.compute\.(inputs|weights|outputs|masks)\[\d+\]")
AGGREGATOR_MEMORY = re.compile(CLUSTER_PATH + r"aggregate_memory\[\d+\]")
PAPER_CORE_MEMORY_BYTES = {"inputs": 8192, "weights": 8192, "outputs": 2048, "masks": 1024}
TIMING_SUFFIXES = ("ssg0p9v125c", "tt1v25c", "ffg1p05vm40c")
LOCAL_SIGNS = re.compile(r"\.local_merge\.token_merge\.similarity\.shard\.compiled\.compact\.slices\[\d+\]$")
LOCAL_TABLE = re.compile(r"\.local_merge\.token_merge\.sizes\.local_sizes\.table_bank\.compiled\.(full|tail)\.entries$")
PACKED_PREDICTOR = "layer.layer.feedforward.packed_signs.predictor.replay_table."
METADATA = re.compile(r"metadata_memory_(lower_words|upper_words\[\d+\]\.memory)$")
SIGN_CACHE = re.compile(r"shared_sign_key_bank\.banks\[\d+\]\.bank$")


def compiler_sizes(paths, masters):
    sizes = {}
    for model in (path for path in paths if path.parent.name == "VERILOG"):
        source = model.read_text()
        master, = set(re.findall(r"\bmodule\s+(TS[56]N28\w+)\b", source)) & masters
        folder = model.parent.parent
        abstract = folder / "LEF" / f"{folder.name}.lef"
        assert abstract in paths and re.findall(r"(?m)^MACRO (\w+)$", abstract.read_text()) == [master]
        assert master not in sizes
        size = capacity_bytes(source, master)
        # The compiler Verilog model provides exact depth. Liberty provides
        # bus widths, so different non-power-of-two depths can share a view.
        word_depth = r"\bparameter\s+(?:integer\s+)?(?:numWord|W)\s*=\s*(\d+)\s*;"
        depths = set(map(int, re.findall(word_depth, re.sub(r"/\*.*?\*/|//[^\n]*", "", source, flags=re.S))))
        depth, = depths
        assert depth > 1 and size * 8 % depth == 0
        for suffix in TIMING_SUFFIXES:
            library = folder / "NLDM" / f"{folder.name}_{suffix}.lib"
            assert library in paths
            library_text = library.read_text()
            assert re.findall(r'(?m)^\s*cell\s*\(\s*"?(\w+)"?\s*\)', library_text) == [master]
            memory, = re.findall(r"\bmemory\s*\(\s*\)\s*\{([^{}]*)\}", library_text)
            assert re.findall(r"\btype\s*:\s*(\w+)\s*;", memory) == ["ram"]
            for field, expected in (("address_width", (depth-1).bit_length()), ("word_width", size*8//depth)):
                assert re.findall(rf"\b{field}\s*:\s*(\d+)\s*;", memory) == [str(expected)], (library, field)
        sizes[master] = size
    assert sizes.keys() == masters
    return sizes


def memory_roles(macros, sizes):
    core_banks, aggregators = defaultdict(Counter), Counter()
    support_bytes, support_count = Counter(), Counter()
    support_by_cluster = defaultdict(Counter)
    for path, master in macros.items():
        amount = sizes[master]
        if core := CORE_MEMORY.fullmatch(path):
            core_banks[int(core[1]), int(core[2])][core[3]] += amount
            continue
        if aggregator := AGGREGATOR_MEMORY.fullmatch(path):
            aggregators[int(aggregator[1])] += amount
            continue

        if LOCAL_SIGNS.search(path):
            role = "surviving_token_signs"
        elif LOCAL_TABLE.search(path):
            role = "token_merge_table"
        elif path.startswith(PACKED_PREDICTOR):
            suffix = path.removeprefix(PACKED_PREDICTOR)
            if METADATA.fullmatch(suffix):
                role = "prediction_metadata"
            elif SIGN_CACHE.fullmatch(suffix):
                role = "shared_weight_signs"
            else:
                raise ValueError(f"Unknown predictor memory {path}")
        else:
            raise ValueError(f"Unknown compiled memory role {path}")

        if role in {"surviving_token_signs", "token_merge_table"}:
            cluster, = re.findall(r"\.clusters\[([0-4])\]\.unit\.selected_bank\1\.", path)
            support_by_cluster[int(cluster)][role] += amount
        support_bytes[role] += amount
        support_count[role] += 1

    assert set(core_banks) == {(cluster, core) for cluster in range(5) for core in range(4)}
    assert all(banks == PAPER_CORE_MEMORY_BYTES for banks in core_banks.values())
    assert aggregators == dict.fromkeys(range(5), 2048)
    assert set(support_by_cluster) == set(aggregators)
    assert all(set(roles) == {"surviving_token_signs", "token_merge_table"} for roles in support_by_cluster.values())
    totals = dict(core_memory_bytes=sum(banks.total() for banks in core_banks.values()),
                  aggregator_io_bytes=aggregators.total(), support_memory_bytes=support_bytes.total())
    return dict(core_memory_bytes_per_core=PAPER_CORE_MEMORY_BYTES.copy(),
                aggregator_io_bytes_per_cluster=2048,
                support_bytes_by_role=dict(support_bytes),
                support_macro_count_by_role=dict(support_count),
                local_support_bytes_by_cluster=dict(support_by_cluster), **totals)


def verify():
    assert __debug__ and Path("/.dockerenv").is_file()
    evidence = {}

    def pin(path, expected=None):
        value = sha(path)
        assert expected is None or value == expected, path
        assert evidence.setdefault(str(path.relative_to(ROOT)), value) == value
        return path

    def read(path, expected=None):
        return json.loads(pin(path, expected).read_bytes())

    records = ROOT / "records"
    parent = read(records / "tri_oracle_grouped_active_memory.json")
    graph = read(records / "tri_oracle_grouped_active_graph.json")
    cold_result = read(records / "tri_oracle_partial_pad_native_cold_result.json")
    models = read(records / "tri_oracle_partial_pad_restored_models.json")
    assert verify_restored_models() == models
    assert (parent["candidate_netlist_sha256"] == graph["candidate_netlist_sha256"]
            == cold_result["input_candidate_sha256"] == models["candidate_netlist_sha256"])
    pad = WORK / "partial_pad_seed_keep_tree"
    cold_path = pad / "cold_native/receipt.json"
    cold = read(cold_path, cold_result["evidence_sha256"][str(cold_path.relative_to(ROOT))])
    before = pin(WORK / "grouped_active_eco/apply/active.def", parent["placement_definition_sha256"])
    placed = pin(pad / "native/pad_ring.def", cold_result["placed_def_sha256"])
    restored = pin(pad / "cold_native/cold.def", cold_result["cold_def_sha256"])
    with placed.open() as stream:
        macros = placed_memory(stream)
    for path in (before, restored):
        with path.open() as stream:
            assert placed_memory(stream) == macros, path

    replay = read(records / "tri_oracle_grouped_reset_replay.json")
    assert graph["parent_netlist_sha256"] == replay["buffered_netlist_sha256"]
    assert replay["native"]["xcelium_exit_status"] == 0
    log = WORK / "grouped_reset_xcelium_serial/xrun.log"
    with pin(log, replay["evidence_sha256"][str(log.relative_to(ROOT))]).open() as stream:
        assert replay_memory(stream) == macros

    imported = read(records / "tri_oracle_concurrent_imported_chip_trained_replay.json")
    capacity = read(ROOT / IMPORT / "memory_capacity_receipt.json",
                    imported["evidence_sha256"]["compiled_memory_audit"])
    assert capacity["candidate_sha256"] == imported["netlist_sha256"] == replay["reference_netlist_sha256"]
    native_models = {name: value for name, value in capacity["input_sha256"].items()
                     if Path(name).parent.name in {"LEF", "NLDM", "VERILOG"}}
    assert len(native_models) == 30
    database = pad / "native/pad_ring.db"
    checkpoint_files = cold["checkpoint"]["files"]
    for name, expected in native_models.items():
        path = pin(ROOT / name, expected)
        if path.suffix in {".lef", ".lib"}:
            directory = "lef" if path.suffix == ".lef" else "mmmc"
            relative = f"libs/{directory}/{path.name}"
            assert expected == checkpoint_files[relative]["sha256"]
            pin(database / relative, expected)

    sizes = compiler_sizes({ROOT / name for name in native_models}, set(macros.values()))
    assert sizes == capacity["capacity_bytes_by_master"]
    total = sum(sizes[master] for master in macros.values())
    roles = memory_roles(macros, sizes)
    assert roles["support_memory_bytes"] == capacity["capacity_bytes_outside_labeled_core_and_aggregator"]
    assert total == parent["compiled_memory_bytes"] == sum(
        roles[name] for name in ("core_memory_bytes", "aggregator_io_bytes", "support_memory_bytes"))
    assert len(macros) == replay["memory_macros"] == parent["compiled_memory_instances"] == 631
    assert models["timing_libraries"] - 3 == parent["compiler_timing_views"] == 18
    targets = read(records / "paper_result_targets.json")
    pin(ROOT / targets["source"], PAPER_SHA256)
    label = targets["silicon"]["sram_published_KB"]
    assert (total + 512) // 1024 == label == 405
    for path in (__file__, capacity_bytes.__code__.co_filename, placed_memory.__code__.co_filename,
                 verify_restored_models.__code__.co_filename):
        pin(Path(path).resolve())

    return dict(state="pad_reserved_chip_compiled_memory_roles_verified",
                candidate_netlist_sha256=graph["candidate_netlist_sha256"],
                compiled_macros=len(macros), compiled_bytes=total,
                paper_label_kb=label, difference_from_binary_label_bytes=total - label * 1024,
                difference_from_decimal_label_bytes=total - label * 1000,
                timing_views_checked=18, **roles, evidence_sha256=evidence,
                scope="Cold physical memory, compiler models and a reset-buffered Xcelium inventory. "
                      "The paper does not specify the unit convention. Register storage and runtime memory "
                      "bandwidth are outside this census.")


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2, sort_keys=True))
