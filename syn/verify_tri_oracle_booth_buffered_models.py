"""Bind the production model files and compiled memory to the repaired placement."""

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

from tri_oracle_artifact_fingerprint import artifact_fingerprint
from verify_tri_oracle_booth_compiled_memory import logical_memories, memory_poses, unique
from verify_tri_oracle_booth_physical_models import (
    INPUTS, MEMORY, PLACEMENT, ROOT, check_load, digest, source_inventory, view_inventory,
)

BUFFERED = Path("records/tri_oracle_corrected_booth_buffered_placement_roundtrip.json")
REPAIR = Path("records/tri_oracle_corrected_booth_pin_load_repair.json")


def verify():
    evidence = {}

    def pin(path, expected=None):
        checksum = digest(path)
        assert expected is None or checksum == expected, path
        evidence[str(path)] = checksum
        return path

    def record(path, expected=None):
        return json.loads(pin(path, expected).read_text())

    placed = record(BUFFERED)
    assert placed["state"] == "corrected_buffer_repair_placement_and_cold_reload_verified"
    files = placed["evidence_sha256"]
    baseline = record(PLACEMENT, files[str(PLACEMENT)])
    repair = record(REPAIR, files[str(REPAIR)])
    inputs = record(INPUTS, baseline["evidence_sha256"][str(INPUTS)])
    memory = record(MEMORY)
    assert memory["state"] == "booth_candidate_compiled_memory_bound_to_netlist_and_seed"

    database = Path(placed["database"])
    fingerprint = artifact_fingerprint(database)
    body = json.dumps(fingerprint, sort_keys=True, separators=(",", ":")).encode()
    database_hash = sha256(body).hexdigest()
    assert database_hash == placed["database_fingerprint_sha256"]
    expected = source_inventory(inputs)
    database_models = unique((path.name, path) for path in (database / "libs").rglob("*")
                             if path.is_file() and path.suffix != ".sdc")
    assert database_models.keys() == expected.keys()
    for name, (source, checksum) in expected.items():
        pin(source, checksum)
        pin(database_models[name], checksum)
    libraries = view_inventory(pin(database / "viewDefinition.tcl"), expected)
    abstracts = {name for name in expected if name.endswith((".lef", ".tlef"))}
    stage = database.parents[1]
    for phase in ("import", "cold"):
        log = stage / phase / "console.log"
        check_load(pin(log, files[str(log)]), libraries, abstracts)

    linked, seed = stage.parent / "buffered.v", stage.parent / "layout.def"
    assert files[str(linked)] == repair["check_after_insertion"]["netlist_sha256"]
    assert files[str(seed)] == repair["check_after_insertion"]["layout_sha256"]
    baseline_stage = Path(baseline["database"]).parents[1]
    baseline_seed = baseline_stage / "seed.def"
    baseline_seed_hash = baseline["evidence_sha256"][str(baseline_seed)]
    assert baseline_seed_hash == memory["evidence_sha256"][str(baseline_seed)]
    baseline_poses = unique(memory_poses(pin(baseline_seed, baseline_seed_hash)))
    repaired_poses = unique(memory_poses(pin(seed, files[str(seed)])))
    assert repaired_poses == baseline_poses
    memories = logical_memories(pin(linked, files[str(linked)]))
    assert memories == {name: pose[0] for name, pose in repaired_poses.items()}
    assert len(memories) == placed["geometry"]["fixed_memory_macros"] == memory["macro_count"]
    counts = Counter(master.decode() for master in memories.values())
    assert counts == {master: spec["macros"] for master, spec in memory["by_master"].items()}
    installed_bytes = sum(count * memory["by_master"][master]["words"] *
                          memory["by_master"][master]["bits_per_word"] // 8
                          for master, count in counts.items())
    assert installed_bytes == memory["installed_bytes"]

    cold = stage / "cold/cold.v"
    pin(cold, files[str(cold)])
    pin(Path(__file__).resolve().relative_to(ROOT))
    return {
        "state": "booth_buffered_candidate_models_and_memory_verified",
        "scope": "Exact production model files, native load logs and memory instance, master, position and halo agreement. Timing slack remains pending.",
        "database_fingerprint_sha256": database_hash,
        "linked_netlist_sha256": files[str(linked)],
        "seed_sha256": files[str(seed)],
        "cold_netlist_sha256": files[str(cold)],
        "memory_instances": len(memories),
        "memory_bytes": installed_bytes,
        "library_files_by_corner": libraries,
        "physical_abstracts": sorted(abstracts),
        "model_file_count": len(expected),
        "evidence_sha256": evidence,
    }


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    print(json.dumps(verify(), indent=2, sort_keys=True))
