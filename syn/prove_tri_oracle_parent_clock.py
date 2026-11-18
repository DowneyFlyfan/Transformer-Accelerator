"""Prove stable parent clock identity; physical clock quality is not qualified."""

from hashlib import file_digest, sha256
import json
from pathlib import Path
import re
import resource
import time

from prove_tri_oracle_packaged_products import CANDIDATE, PIN, ROOT, memory_guard
from prove_tri_oracle_packaged_reductions import DecisionGraph
from prove_tri_oracle_parent_reset import INSTANCE, ResetHierarchy, identifier


def read_clock_library(path, masters):
    """Accept compiler whitespace without losing or merging Liberty pins."""
    from plan_tri_oracle_grouped_reset import read_library

    raw_names = set(re.findall(r"(?m)^cell\s*\(([^)]+)\)\s*\{", path.read_text()))
    allowed = {name for name in raw_names if name.strip() in masters}
    result = {}
    for (cell, pin), properties in read_library(path, allowed).items():
        key = cell.strip(), pin.strip()
        assert key not in result, "Duplicate normalized library pin"
        result[key] = properties
    return result


def bind_parents(result, expected):
    for name, checksum in result["parent_module_sha256"].items():
        assert expected.get(name) == checksum, ("Captured parent body differs", name)


def capture_candidate(path, expected):
    source = path.read_bytes()
    assert sha256(source).hexdigest() == expected, "Changed candidate snapshot"
    return source


def prove(checker, top, paths):
    """Compare each reachable array input with the packaged top clock."""
    assert paths and len(paths) == len(set(paths)), "Missing or repeated clock targets"
    checker.contexts[""] = top, None, None
    roots, arrays = [], []
    for path in paths:
        checker.guard()
        context = ""
        for instance in path.split("/"):
            context = checker.child(context, instance)
        module = checker.module(checker.contexts[context][0])
        assert (
            module.directions.get("clk") == "input" and module.declared["clk"] is None
        ), "Array clock is not a scalar input"
        roots.append(checker.trace(context, "clk"))
        arrays.append(
            dict(
                path=path,
                module=checker.contexts[context][0],
                array_module_sha256=module.sha256,
            )
        )
    leaves = sorted(set().union(*(checker.graph.dependencies(root) for root in roots)))
    assert leaves == ["top.clk"], (
        "Parent clock identity has constant or foreign dependencies"
    )
    decision = DecisionGraph(leaves)
    identities = decision.convert(checker.graph, roots)
    assert identities == [decision.variable("top.clk")] * len(roots), (
        "Parent clock identity differs"
    )
    for value in (0, 1):
        assert checker.graph.evaluate(roots, {"top.clk": value}) == [value] * len(
            roots
        ), "Integer parent clock identity differs"
    return dict(
        array_count=len(arrays),
        arrays=arrays,
        integer_assignments=2,
        all_array_clocks_equal_top_clock=True,
        parent_module_sha256={
            name: module.sha256 for name, module in checker.modules.items()
        },
    )


def mutations(checker, top, paths):
    """Corrupt actual parent bindings in memory, preserving the input files."""
    rejected = []
    for path in paths:
        checker.guard()
        parent, _, local = path.rpartition("/")
        parent_master = checker.contexts[parent][0]
        original = checker.body(parent_master)
        (instance,) = (
            m for m in INSTANCE.finditer(original) if identifier(m[2].decode()) == local
        )
        for value in (0, 1):
            changed = 0

            def corrupt(pin):
                nonlocal changed
                if identifier(pin[1].decode()) != "clk":
                    return pin[0]
                changed += 1
                return b"." + pin[1] + b"(1'b" + str(value).encode() + b")"

            fields = PIN.sub(corrupt, instance[3])
            assert changed == 1, "Mutation did not change exactly one clock binding"
            altered = (
                original[: instance.start(3)] + fields + original[instance.end(3) :]
            )
            assert altered != original
            mutant = ResetHierarchy(
                lambda name: altered if name == parent_master else checker.body(name),
                checker.masters,
                checker.library,
                checker.states,
                guard=checker.guard,
            )
            mutant.modules = checker.modules.copy()
            mutant.modules.pop(parent_master)
            try:
                prove(mutant, top, [path])
            except (AssertionError, ValueError) as error:
                assert "clock identity" in str(error), (
                    "Unrelated mutation rejection",
                    str(error),
                )
                rejected.append(
                    dict(
                        array=checker.contexts[path][0],
                        stuck_value=value,
                        rejection=str(error),
                    )
                )
            else:
                raise AssertionError(
                    ("Disconnected actual clock accepted", path, value)
                )
    return rejected


def verify(output):
    from link_tri_oracle_indexed_whole_chip import spans

    assert __debug__ and not Path("/.dockerenv").exists()
    assert (
        output.resolve().is_relative_to((ROOT / ".cache").resolve())
        and not output.exists()
    )
    memory_guard(10)
    started, evidence = time.monotonic(), {}

    def pin(path, wanted=None):
        with path.open("rb") as stream:
            actual = file_digest(stream, "sha256").hexdigest()
        assert wanted is None or actual == wanted, ("Changed clock proof input", path)
        assert evidence.setdefault(str(path.relative_to(ROOT)), actual) == actual
        return path

    def record(name, state=None):
        row = json.loads(pin(ROOT / "records" / name).read_text())
        if state:
            assert row["state"] == state
        for name, checksum in row["evidence_sha256"].items():
            pin(ROOT / name, checksum)
        return row

    structure = record(
        "tri_oracle_packaged_compute_structure.json",
        "packaged_register_geometry_and_reachable_prediction_ownership_verified",
    )
    reset = record(
        "tri_oracle_packaged_parent_reset_distribution.json",
        "packaged_parent_combinational_reset_distribution_verified",
    )
    storage = record(
        "tri_oracle_packaged_storage_accounting.json",
        "exact_packaged_candidate_sram_and_standard_cell_state_accounted",
    )
    qualified = [
        record(name, state)
        for name, state in [
            (
                "tri_oracle_packaged_product_next_states.json",
                "packaged_signed_product_next_states_exhaustively_verified",
            ),
            (
                "tri_oracle_packaged_reduction_next_states.json",
                "packaged_signed_reduction_next_states_symbolically_verified",
            ),
            (
                "tri_oracle_packaged_valid_next_states.json",
                "packaged_local_valid_transitions_and_clears_verified",
            ),
        ]
    ]
    for row in [reset, storage, *qualified]:
        assert row["candidate_sha256"] == structure["candidate_sha256"]
    names = set(structure["array_register_inventory"])
    assert len(names) == 20 and all(set(row["arrays"]) == names for row in qualified)
    paths = [row["path"] for row in reset["arrays"]]
    assert len(paths) == 20 and {row["module"] for row in reset["arrays"]} == names
    pin(CANDIDATE, structure["candidate_sha256"])
    (detail_name,) = storage["full_detail_cache"]
    detail = json.loads(
        pin(ROOT / detail_name, storage["full_detail_cache"][detail_name]).read_text()
    )
    states = {
        name: row["state_kinds"]
        for name, row in detail["standard_cell_state_by_master"].items()
    }
    (standard_source,) = (
        ROOT / name
        for name in evidence
        if Path(name).name == "tcbn28hpcplusbwp12t40p140tt1v25c.lib"
    )
    masters = set(
        re.findall(r"(?m)^cell\s*\(([^)]+)\)\s*\{", standard_source.read_text())
    )
    assert set(states) <= masters, "State census includes an unknown standard cell"
    masters.update(storage["compiled_memory_by_master"])
    corners = ("tt1v25c", "ssg0p9v125c", "ffg1p05vm40c")
    libraries = {}
    for corner in corners:
        paths_for_corner = [
            ROOT / name for name in evidence if name.endswith(corner + ".lib")
        ]
        assert len(paths_for_corner) == 7, (
            "Expected standard cells and all six memory libraries"
        )
        table = {}
        for path in paths_for_corner:
            memory_guard()
            rows = read_clock_library(path, masters)
            assert not table.keys() & rows.keys(), "Duplicate library cell/pin"
            table.update(rows)
        libraries[corner] = table
    for path in (
        Path(__file__).resolve(),
        ROOT / "syn/test_tri_oracle_parent_clock.py",
        ROOT / "syn/prove_tri_oracle_parent_reset.py",
    ):
        pin(path)
    with memoryview(
        capture_candidate(CANDIDATE, structure["candidate_sha256"])
    ) as source:
        assert source.readonly, "Candidate snapshot must be immutable"
        definitions = spans(source)
        assert names <= definitions.keys()
        parent_manifest = {
            name: sha256(source[low:high]).hexdigest()
            for name, (low, high) in definitions.items()
        }
        for name, checksum in reset["parent_module_sha256"].items():
            assert parent_manifest.get(name) == checksum, (
                "Reset proof parent body differs",
                name,
            )

        def body(master):
            low, high = definitions[master]
            return bytes(source[low:high])

        checker = ResetHierarchy(
            body, set(definitions), libraries[corners[0]], states, guard=memory_guard
        )
        result = prove(checker, structure["logical_top"], paths)
        bind_parents(result, parent_manifest)
        for row in result["arrays"]:
            assert all(
                row["array_module_sha256"]
                == item["arrays"][row["module"]]["array_module_sha256"]
                for item in qualified
            ), "Clock proof array differs from qualified local state proof"
        for corner in corners[1:]:
            for key in checker.used_library_pins:
                assert {
                    a: libraries[corner][key].get(a) for a in ("direction", "function")
                } == {
                    a: checker.library[key].get(a) for a in ("direction", "function")
                }, ("Corner clock semantics differ", corner, key)
        result["used_library_pins"] = sorted(checker.used_library_pins)
        result["rejected_actual_parent_mutations"] = mutations(
            checker, structure["logical_top"], paths
        )
        assert len(result["rejected_actual_parent_mutations"]) == 40
    for name, checksum in list(evidence.items()):
        pin(ROOT / name, checksum)
    result.update(
        state="packaged_parent_stable_clock_identity_verified",
        candidate_sha256=structure["candidate_sha256"],
        evidence_sha256=evidence,
        wall_seconds=time.monotonic() - started,
        peak_resident_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        advance_to_clock_distribution_or_routing_allowed=False,
        scope="Stable two-state parent clock identity for the twenty reachable array inputs, bound to the local product, reduction and valid-register proofs. This is logical connectivity evidence only: it does not qualify clock-tree synthesis, clock skew, glitches, timing, reset release, complete architecture, trained execution, accuracy, or routing.",
    )
    output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(
        "PARENT_CLOCK_IDENTITY_PASS",
        result["array_count"],
        len(result["rejected_actual_parent_mutations"]),
        flush=True,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    verify(parser.parse_args().output)
