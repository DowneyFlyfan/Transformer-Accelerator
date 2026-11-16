"""Verify predictor ownership and mapped data routes on the placed carry-save candidate."""

import argparse
from collections import Counter
from contextlib import ExitStack
from functools import cache
from hashlib import file_digest
import json
from pathlib import Path

from audit_tri_oracle_mapped_redundancy import TOP, hierarchy
from link_tri_oracle_parallel_chip import catalog, definition
from trace_overloaded_resets import read_lib_ports
from verify_linked_placed_topology import bits, parse_module, pin_fields


def digest(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def check_pin(pins, name, nets, expected):
    observed = bits(pins[name], nets)
    wanted = bits(expected, nets)
    if observed != wanted:
        raise ValueError(f"{name} has {observed[:3]}, expected {wanted[:3]}")


def strip_dependencies(nets, cells, assign, library):
    drivers = {}
    for lvalue, rvalue in assign:
        left, right = bits(lvalue, nets), bits(rvalue, nets)
        for output, source in zip(left, right, strict=True):
            assert output not in drivers
            drivers[output] = (source,)
    for master, fields in cells.values():
        pins = pin_fields(fields)
        declared = library[master]
        inputs = tuple(bit for name, value in pins.items() if declared[name] == "input"
                       for bit in bits(value, nets))
        for name, value in pins.items():
            if declared[name] == "output":
                for bit in bits(value, nets):
                    assert bit[0] != "constant" and bit not in drivers
                    drivers[bit] = inputs

    def requests(bit):
        pending = [bit]
        visited = set()
        found = set()
        while pending:
            source = pending.pop()
            if source in visited:
                continue
            visited.add(source)
            if source[:2] == ("vector", "request"):
                found.add(source[2])
            else:
                pending.extend(drivers.get(source, ()))
        return found

    return requests


def check_strip_masks(nets, requests):
    # The response bus carries combined Gate/Up masks in bits 20:13.
    controls = set(range(128, 147))
    for channel in range(8):
        (output,) = bits(f"response[{13 + channel}]", nets)
        up = set(range(8 * channel, 8 * (channel + 1)))
        gate = {64 + item for item in up}
        observed = requests(output)
        if observed - controls != up | gate or not set(range(128, 144)) <= observed:
            raise ValueError(f"Strip channel {channel} has unintended mapped sign dependencies")
    return 8


def verify(candidate, inventory, directions):
    graph = hierarchy(candidate)
    reachable = {}

    def visit(master, scope):
        assert scope not in reachable
        reachable[scope] = master
        for name, child in graph[master].items():
            visit(child, f"{scope}.{name.lstrip(chr(92))}")

    visit(TOP, TOP)
    summaries = []
    with ExitStack() as stack:
        entries = catalog(stack, candidate)

        @cache
        def module(master):
            code = definition(entries[master]).decode()
            _, ports, wires, cells, assigns = parse_module(code, (0, len(code)))
            return ports, wires, cells, assigns

        def child(master, name):
            _, _, cells, _ = module(master)
            part, association = cells[name]
            assert graph[master][name] == part
            return part, pin_fields(association)

        for record in inventory:
            bank = record["bank"]
            owner = reachable[record["instance"]]
            assert owner == record["native_cluster_master"]
            _, owner_nets, _, _ = module(owner)
            merger, merger_pins = child(owner, r"\local_merge.token_merge")
            assert merger == record["native_token_merger_master"]
            for name, wire in (
                ("sign_data", "merge_sign_data"),
                ("sign_control", "merge_sign_control"),
                ("all_sign_counts", "global_sign_counts"),
                (r"\command[threshold]", r"\merge_range_command[threshold] "),
                (r"\result[map_valid]", r"\merge_range_result[map_valid] "),
                (r"\size_command[begin_query]", r"\token_size_bank_command[begin_query] "),
                (r"\size_result[out_count]", r"\token_size_bank_result[out_count] "),
            ):
                check_pin(merger_pins, name, owner_nets, wire)

            _, merger_nets, _, _ = module(merger)
            controller, cp = child(merger, "merge_controller")
            assert controller.startswith("tri_oracle_cumulative_merge447_")
            check_pin(cp, "cfg_minimum_matches", merger_nets, r"\command[threshold] ")
            check_pin(cp, "merge_sign_counts", merger_nets, "all_sign_counts")
            check_pin(cp, "map_valid", merger_nets, r"\result[map_valid] ")
            similarity, sp = child(merger, "similarity")
            features = 512 if bank == 0 else 384
            assert similarity.startswith(f"tri_oracle_aggregator_sign447_FEATURES{features}_")
            similarity_ports, _, _, _ = module(similarity)
            assert similarity_ports["sign_data"] == ("input", (features - 1, 0))
            check_pin(sp, "sign_data", merger_nets, "sign_data")
            check_pin(sp, "control", merger_nets, "sign_control")
            sizes, sz = child(merger, "sizes")
            for name, wire in (
                (r"\command[begin_query]", r"\size_command[begin_query] "),
                (r"\result[out_count]", r"\size_result[out_count] "),
            ):
                check_pin(sz, name, merger_nets, wire)
            assert sizes in entries

            cores = []
            for index in range(4):
                core, _ = child(owner, rf"\cores[{index}]")
                _, core_nets, _, _ = module(core)
                head, head_pins = child(core, r"\head.predict")
                strip, strip_pins = child(core, r"\strip.predict")
                assert head.startswith("tri_oracle_core_head450_")
                assert strip.startswith("tri_oracle_core_strip448_")
                request = bits(head_pins["request"], core_nets)
                response = bits(head_pins["response"], core_nets)
                assert len(request) == 395 and len(response) == 73
                assert request[-256:] == bits("head_request[255:0]", core_nets)
                assert request[:3] == bits("head_request[394:392]", core_nets)
                assert response[:5] == bits("head_response[72:68]", core_nets)
                check_pin(strip_pins, "request", core_nets, "strip_request")
                strip_result = bits(strip_pins["response"], core_nets)
                assert len(strip_result) == 40
                assert strip_result[19:27] == bits("strip_response[20:13]", core_nets)
                _, head_nets, _, _ = module(head)
                classifier, class_pins = child(head, "classifier")
                assert classifier.startswith("tri_oracle_attention_head_classifier410_")
                for name, wire in (("cfg_valid", "request[394]"), ("in_valid", "request[393]"),
                                   ("in_scores", "request[255:0]"), ("out_streaming", "response[68]")):
                    check_pin(class_pins, name, head_nets, wire)
                _, strip_nets, gates, assigns = module(strip)
                requests = strip_dependencies(strip_nets, gates, assigns, directions)
                checked = check_strip_masks(strip_nets, requests)
                cores.append(dict(index=index, head_classifier=classifier, strip_predictor=strip,
                                  strip_mask_channels_bound=checked))
            summaries.append(dict(bank=bank, aggregator=owner, merge_controller=controller,
                                  sign_similarity=similarity, sign_features=features,
                                  token_size_bank=sizes, cores=cores))
    assert Counter(item["bank"] for item in summaries) == dict.fromkeys(range(5), 1)
    assert sum(item["sign_features"] for item in summaries) == 2048
    return summaries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("architecture_receipt", type=Path)
    parser.add_argument("standard_cell_models", type=Path)
    args = parser.parse_args()
    assert __debug__ and not Path("/.dockerenv").exists()
    architecture = json.loads(args.architecture_receipt.read_text())
    observed = digest(args.candidate)
    assert observed == architecture["candidate_sha256"]
    results = verify(args.candidate, architecture["clusters"], read_lib_ports(args.standard_cell_models))
    assert digest(args.candidate) == observed
    print(json.dumps({
        "state": "placed_candidate_local_prediction_port_and_mask_lineage_verified",
        "candidate_sha256": observed,
        "clusters": results,
        "scope": ("Named chip-owned prediction paths and flattened gate fan-in. Terminal masks are "
                  "checked for structurally correct channel sign inputs. Method-level numerical "
                  "behavior, the shared scheduling datapath, and routing require separate checks."),
        "evidence_sha256": {str(path): digest(path) for path in
                            (args.architecture_receipt, args.standard_cell_models, Path(__file__).resolve())},
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
