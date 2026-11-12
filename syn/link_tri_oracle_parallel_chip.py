"""Verify reusable mapped definitions and link them into the synthesized parent."""

import argparse
from collections import Counter
from contextlib import ExitStack
from functools import lru_cache
from hashlib import sha256 as hash_bytes
import json
import mmap
from pathlib import Path
import re
import resource

from audit_tri_oracle_wac_parent_hdl_export import declarations
from prepare_tri_oracle_parallel_chip_synthesis import LOADER_CUT, includes, pin, read, verify
from run_tri_oracle_parallel_chip_synthesis import check_netlist, wait_for_receipt
from verify_tri_oracle_packed_down_weights import ROOT


PHYSICAL = ROOT / ".cache/physical"
DECODER = PHYSICAL / "context_external/shared_decoder/linked_context_decoder_complete_attention/candidate.v"
DISPATCH = PHYSICAL / "chip_dispatch/mapped_flat/netlist.v"
LOADER = PHYSICAL / "wide_weight_loader/parallel_loader/mapped_adapter/mapped.v"
STANDARD_MODELS = PHYSICAL / "library/tcbn28hpcplusbwp12t40p140.v"
MODULE = re.compile(rb"(?m)^[ \t]*module\s+([\w$]+)\s*\(")
INSTANCE = re.compile(rb"(?m)^[ \t]+([\w$]+)\s+(?:\\\S+|[\w$]+)\s*\(\s*\.")
MEMORY_PREFIXES = ("TS5N28", "TS6N28")


def index(source):
    modules = {}
    for module in MODULE.finditer(source):
        start = module.start()
        end = source.find(b"\nendmodule", module.end())
        name = module[1].decode()
        assert end > start and name not in modules, name
        modules[name] = source, start, end + len(b"\nendmodule")
    assert modules
    return modules


def definition(entry):
    source, start, end = entry
    return source[start:end]


def signature(entry):
    return {name: [direction, list(span) if span is not None else None]
            for name, (direction, span) in declarations(definition(entry).decode())[0].items()}


def catalog(stack, *paths):
    result = {}
    for path in paths:
        handle = stack.enter_context(path.open("rb"))
        source = stack.enter_context(mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ))
        modules = index(source)
        assert not result.keys() & modules.keys(), path
        result.update(modules)
    return result


def library_masters(pins, synthesis):
    models = [path for path in includes(synthesis / "elaborate.sv") if path.parent.name == "VERILOG"]
    assert len(models) == 6
    masters = set()
    for path in (STANDARD_MODELS, *models):
        name = str(path.relative_to(ROOT))
        pin(pins, path, pins[name])
        local = {match[1].decode() for match in MODULE.finditer(path.read_bytes())}
        assert local and not masters & local, path
        masters.update(local)
    return masters


def scan(modules, library, roots):
    active = set()

    @lru_cache(maxsize=None)
    def visit(master):
        assert master not in active, ("recursive module", master)
        active.add(master)
        reachable = {master}
        memories = Counter()
        source, start, end = modules[master]
        for leaf, count in Counter(match[1].decode() for match in INSTANCE.finditer(source, start, end)).items():
            if leaf in modules:
                children, child_memories = visit(leaf)
                reachable.update(children)
                for name, instances in child_memories.items():
                    memories[name] += count * instances
            else:
                assert leaf in library, (master, "unresolved instance master", leaf)
                if leaf.startswith(MEMORY_PREFIXES):
                    memories[leaf] += count
        active.remove(master)
        return frozenset(reachable), memories

    return {master: visit(master) for master in roots}


def audit_imports(modules, library, preserved, expected_memories):
    masters = [cut["mapped_master"] for cut in preserved.values()]
    assert len(masters) == len(set(masters)) == 11
    assert set(masters) <= modules.keys()
    coverage = scan(modules, library, masters)
    imported = set()
    by_cut = {}
    memories = Counter()
    for path, cut in preserved.items():
        master = cut["mapped_master"]
        assert signature(modules[master]) == cut["ports"], ("mapped cut signature", path, master)
        reachable, memory = coverage[master]
        imported.update(reachable)
        memories.update(memory)
        by_cut[path] = {"master": master, "ports": len(cut["ports"]), "reachable_definitions": len(reachable),
                        "compiled_memories": sum(memory.values()),
                        "definition_sha256": hash_bytes(definition(modules[master])).hexdigest()}
    assert memories == expected_memories, (memories, expected_memories)
    return imported, by_cut


def load_setup(synthesis):
    preflight = synthesis / "preflight_receipt.json"
    recorded = ROOT / "records/wac_parallel_chip_synthesis_preflight_result.json"
    record = read(recorded)
    pins = {}
    pin(pins, recorded)
    pin(pins, preflight, record["evidence_sha256"][str(preflight.relative_to(ROOT))])
    proof = read(preflight)
    assert proof["state"] == "parallel_chip_preserved_synthesis_interfaces_verified"
    pins.update(proof["input_sha256"])
    prepared = synthesis / "prepared.json"
    pin(pins, prepared, record["evidence_sha256"][str(prepared.relative_to(ROOT))])
    setup = read(prepared)
    assert setup["state"] == "parallel_chip_synthesis_partition_prepared"
    verify(pins)
    for path, expected in ((DECODER, setup["mapped_decoder_sha256"]), (DISPATCH, setup["controller_sha256"]),
                           (LOADER, setup["preserved"][LOADER_CUT]["netlist_sha256"])):
        pin(pins, path, expected)
    topology = ROOT / "records/wac_mapped_paper_topology_result.json"
    pin(pins, topology)
    native = read(topology)
    assert native["candidate_netlist_sha256"] == setup["mapped_decoder_sha256"]
    complete = Counter({master: entry["instances"] for master, entry in native["memory"]["by_master"].items()})
    # The feed-forward predictor replay metadata is synthesized with the parent.
    parent_only = Counter({"TS5N28HPCPSVTA512X64M4F": 2})
    assert native["memory"]["bytes_by_role"]["feedforward_prediction_metadata"] == 2 * 512 * 64 // 8
    assert sum(complete.values()) == 623
    pin(pins, Path(__file__).resolve())
    pin(pins, Path(declarations.__code__.co_filename).resolve())
    return setup, pins, complete, complete - parent_only


def replace_abstracts(parent, cuts, imported):
    aliases = {item["abstract_master"]: item["mapped_master"] for item in cuts.values()}
    assert len(aliases) == len(cuts) and aliases.keys() <= parent.keys()
    assert (parent.keys() - aliases.keys()).isdisjoint(imported), "Parent and mapped imports define the same module"
    tokens = b"|".join(map(re.escape, sorted((name.encode() for name in aliases), key=len, reverse=True)))
    pattern = re.compile(rb"(?m)^([ \t]+)(" + tokens + rb")(?=\s+(?:\\\S+|[\w$]+)\s*\(\s*\.)")
    replaced = Counter()

    def substitute(match):
        old = match[2].decode()
        replaced[old] += 1
        return match[1] + aliases[old].encode()

    for name, entry in parent.items():
        if name not in aliases:
            yield pattern.sub(substitute, definition(entry))
    assert replaced == Counter(aliases.keys()), replaced


def run(synthesis, output, link):
    setup, pins, complete, expected = load_setup(synthesis)
    library = library_masters(pins, synthesis)
    with ExitStack() as stack:
        assets = catalog(stack, DECODER, DISPATCH, LOADER)
        imported, by_cut = audit_imports(assets, library, setup["preserved"], expected)
        definitions = {name: hash_bytes(definition(assets[name])).hexdigest() for name in sorted(imported)}
        result = {
            "state": "parallel_chip_mapped_import_signatures_and_memory_inventory_verified",
            "cuts": by_cut, "checked_cut_ports": sum(cut["ports"] for cut in by_cut.values()),
            "imported_definitions": len(imported), "imported_compiled_memories": dict(expected),
            "imported_definitions_sha256": hash_bytes(json.dumps(definitions, sort_keys=True).encode()).hexdigest(),
        }
        if link:
            native = synthesis / "native_parent"
            receipt = native / "receipt.json"
            proof = read(receipt)
            assert proof["state"] == "dual_lane_chip_parent_mapped_and_preserved_cut_signatures_verified"
            assert proof["native"]["native_exit_status"] == 0 and proof["native"]["stop_reason"] is None
            verify(proof["input_sha256"])
            verify(proof["output_sha256"])
            pin(pins, receipt)
            parent_path = native / "netlist.v"
            pin(pins, parent_path, proof["output_sha256"][str(parent_path.relative_to(ROOT))])
            top, cuts = check_netlist(parent_path.read_text(), setup)
            assert top == proof["top"] and cuts == proof["preserved_cuts"]
            parent = catalog(stack, parent_path)
            output.mkdir()
            netlist = output / "chip.v"
            with netlist.open("xb") as stream:
                for block in replace_abstracts(parent, cuts, imported):
                    stream.write(block + b"\n")
                for name in sorted(imported):
                    stream.write(definition(assets[name]) + b"\n")
            linked = catalog(stack, netlist)
            reachable, actual = scan(linked, library, [top])[top]
            assert imported <= reachable and actual == complete
            assert all(hash_bytes(definition(linked[name])).hexdigest() == digest for name, digest in definitions.items())
            pin(pins, netlist)
            result.update(state="parallel_chip_parent_linked_with_verified_mapped_imports",
                          top=top, compiled_memories=dict(actual),
                          chip_sha256=pins[str(netlist.relative_to(ROOT))])
    verify(pins)
    result["input_sha256"] = pins
    receipt = output / "receipt.json" if link else output
    with receipt.open("x") as stream:
        stream.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(result["state"], len(by_cut), result["imported_definitions"], sum(expected.values()), flush=True)


if __name__ == "__main__":
    resource.setrlimit(resource.RLIMIT_AS, (2**31, 2**31))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("synthesis", type=lambda value: Path(value).resolve())
    parser.add_argument("output", type=lambda value: Path(value).resolve())
    parser.add_argument("--link", action="store_true")
    parser.add_argument("--parent-worker", type=int)
    args = parser.parse_args()
    if args.parent_worker is not None:
        assert args.link
        wait_for_receipt(args.synthesis / "native_parent/receipt.json", args.parent_worker,
                         "run_tri_oracle_parallel_chip_synthesis.py")
    run(args.synthesis, args.output, args.link)
