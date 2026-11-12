"""Resolve archived bench observations against the mapped chip hierarchy."""

import argparse
from functools import lru_cache
import json
from pathlib import Path
import re
import resource

from audit_linked_layer_memory import inventory
from prepare_tri_oracle_chip_command_layer import TOP
from prepare_tri_oracle_packed_tensor import rewrite
from prepare_tri_oracle_parallel_chip_synthesis import includes, pin, read, verify
from replay_tri_oracle_parallel_chip import image_bench
from run_tri_oracle_parallel_chip_synthesis import wait_for_receipt
from verify_linked_placed_topology import module_index, parse_module
from verify_tri_oracle_packed_down_weights import ROOT, sha256


PHYSICAL = ROOT / ".cache/physical"
CONTEXT = PHYSICAL / "context_external/shared_decoder"
REFERENCE = PHYSICAL / "shared_memory_layer_boundary"
OBSERVATION = re.compile(r"\bdut(?:\.[A-Za-z_][\w$]*)+")
RESTORE = (
    "        if (checking_restore && dut.layer.layer.attention_pipeline.attention.row_map_valid &&\n"
    "            dut.layer.layer.attention_pipeline.attention.row_map_ready) begin"
)
RESTORE_FALLBACK = "        if (checking_restore && dut.layer.layer.merge_table_request[21]) begin"


def inspect_hierarchy(sources):
    modules = {}
    for source in sources:
        index = module_index(source)
        assert not modules.keys() & index.keys()
        modules.update({name: (source, span) for name, span in index.items()})

    @lru_cache(maxsize=None)
    def view(master):
        _, _, nets, children, _ = parse_module(*modules[master])
        return nets, {name.removeprefix("\\"): child for name, (child, _) in children.items()}

    def resolve(top, path):
        *instances, signal = path.split(".")[1:]
        master = top
        try:
            for instance in instances:
                master = view(master)[1][instance]
            return view(master)[0][signal]
        except KeyError as error:
            raise ValueError(f"Mapped observation {path} is missing in {master}") from error

    return resolve


def audit_observations(text, top, resolve):
    return {path: resolve(top, path) for path in sorted(set(OBSERVATION.findall(text)))}


def adapt_observations(text, top, resolve):
    original = set(OBSERVATION.findall(text))
    replacements = {}
    if RESTORE in text:
        shape = resolve(top, "dut.layer.layer.merge_table_request")
        assert shape == (21, 0)
        text = rewrite(text, ((RESTORE, RESTORE_FALLBACK),))

    def adapt(match):
        path = match[0]
        old_alias = re.fullmatch(r"dut\.layer\.(?:layer_(\w+)|(context_(?:req|rsp|wr)\w+))", path)
        if old_alias is None:
            resolve(top, path)
            return path
        moved = "dut.layer.layer." + (old_alias[1] or old_alias[2])
        shape = resolve(top, moved)
        try:
            original_shape = resolve(top, path)
        except ValueError:
            original_shape = shape
        assert original_shape == shape, (path, moved, original_shape, shape)
        assert replacements.setdefault(path, moved) == moved
        return moved

    text = OBSERVATION.sub(adapt, text)
    bound = audit_observations(text, top, resolve)
    removed = original - bound.keys() - replacements.keys()
    if removed:
        assert removed == {"dut.layer.layer.attention_pipeline.attention." + name
                           for name in ("row_map_valid", "row_map_ready")}
    return text, bound, replacements, sorted(removed)


def audit_baseline(output):
    pins = {}
    attention = CONTEXT / "chip_command_context_mapped"
    attention_result = attention / "receipt.json"
    proof = read(attention_result)
    assert proof["state"] == "mapped_chip_controller_restored_context_on_corrected_gate_decoder"
    assert proof["elaboration"]["native_exit_status"] == proof["smoke"]["native_exit_status"] == 0
    gate = CONTEXT / "linked_context_decoder_complete_attention/candidate.v"
    wrapper = CONTEXT / "chip_structural_interface_preflight/chip_wrapper.v"
    wrapper_result = wrapper.with_name("receipt.json")
    pin(pins, wrapper, read(wrapper_result)["chip_wrapper_sha256"])
    pin(pins, gate, proof["decoder_netlist_sha256"])
    bench = attention / "attention_tb.sv"
    pin(pins, bench, proof["input_sha256"][str(bench)])
    pin(pins, attention_result)
    pin(pins, wrapper_result)
    observation = audit_observations(bench.read_text(), TOP, inspect_hierarchy((gate.read_text(), wrapper.read_text())))

    trained = REFERENCE / "mapped_trained_replay"
    trained_result = trained / "receipt.json"
    proof = read(trained_result)
    assert proof["state"] == "mapped_shared_memory_layer_replayed_exact_trained_workload"
    assert proof["native"]["native_exit_status"] == 0 and proof["counters"]["exact_outputs"] == 32768
    gate = REFERENCE / "linked/candidate.v"
    bench = trained / "trained_tb.sv"
    for path in (gate, bench):
        pin(pins, path, proof["input_sha256"][str(path)])
    pin(pins, trained_result)
    top = read(REFERENCE / "linked/receipt.json")["top"]
    trained_observations = audit_observations(bench.read_text(), top, inspect_hierarchy((gate.read_text(),)))
    for path in (Path(__file__).resolve(), Path(parse_module.__code__.co_filename).resolve()):
        pin(pins, path)
    verify(pins)
    result = {"state": "mapped_attention_and_trained_bench_observations_bound",
              "mapped_attention_observations": observation, "mapped_trained_observations": trained_observations,
              "input_sha256": pins}
    with output.open("x") as stream:
        stream.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(result["state"], len(observation), len(trained_observations), flush=True)


def prepare(synthesis, candidate, output):
    linked = synthesis / "linked_chip"
    linked_receipt = linked / "receipt.json"
    link = read(linked_receipt)
    assert link["state"] == "parallel_chip_parent_linked_with_verified_mapped_imports"
    pins = link["input_sha256"].copy()
    verify(pins)
    pin(pins, linked_receipt)
    gate = linked / "chip.v"
    pin(pins, gate, link["chip_sha256"])
    source = candidate / "prepared.json"
    preflight = read(synthesis / "prepared.json")
    assert preflight["input_sha256"][str(source.relative_to(ROOT))] == sha256(source)
    pin(pins, source)
    dual = read(source)
    assert dual["state"] == "source_chip_connects_two_packed_read_lanes_to_compiled_clusters"
    original_bundle = candidate / "bundle.sv"
    pin(pins, original_bundle, dual["input_sha256"][str(original_bundle.relative_to(ROOT))])
    models = [path for path in includes(original_bundle) if path.parent.name in ("VERILOG", "library") and path.suffix == ".v"]
    assert len(models) == 7
    for path in models:
        pin(pins, path, dual["input_sha256"][str(path.relative_to(ROOT))])

    top = link["top"]
    code = gate.read_text()
    resolve = inspect_hierarchy((code,))
    memories = inventory(code, top)
    assert len(memories) == sum(link["compiled_memories"].values()) == 623
    assert set(memories.values()) == link["compiled_memories"].keys()
    output.mkdir()
    census = output / "memory_census.sv"
    census.write_text("""`timescale 1ns/1ps
module tri_oracle_linked_memory_probe #(parameter string MASTER="") ();
  initial $display("TRI_ORACLE_MAPPED_CENSUS %s %m", MASTER);
endmodule
""" + "".join(f'bind {master} tri_oracle_linked_memory_probe #(.MASTER("{master}")) mapped_hierarchy_probe ();\n'
              for master in sorted(set(memories.values()))))
    observations = {}
    for mode in ("attention", "trained"):
        original = candidate / f"{mode}_tb.sv"
        pin(pins, original, dual["input_sha256"][str(original.relative_to(ROOT))])
        text = original.read_text()
        if mode == "trained":
            text = image_bench(text)
            text = rewrite(text, ((f"{TOP} #(.PACKED_FEEDFORWARD_WEIGHTS(PACKED)) dut (", f"{top} dut ("),))
        else:
            text = rewrite(text, ((f"{TOP} dut (", f"{top} dut ("),))
        text, bound, aliases, restore = adapt_observations(text, top, resolve)
        bench = output / original.name
        bench.write_text(text)
        bundle = output / f"{mode}_bundle.sv"
        bundle.write_text("`define UNIT_DELAY\n" +
                          "".join(f'`include "{path}"\n' for path in (*models, gate, bench, census)))
        observations[mode] = {"bound": bound, "retargeted_aliases": aliases, "restore_handshake_rebound": restore}
        pin(pins, bench)
        pin(pins, bundle)
    for path in (census, Path(__file__).resolve(), Path(parse_module.__code__.co_filename).resolve()):
        pin(pins, path)
    verify(pins)
    result = {"state": "linked_parallel_chip_gate_replay_prepared", "top": top,
              "candidate_sha256": link["chip_sha256"], "observations": observations,
              "expected_memory_census": memories, "input_sha256": pins}
    (output / "prepared.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(result["state"], len(observations["attention"]["bound"]), len(observations["trained"]["bound"]), flush=True)


if __name__ == "__main__":
    resource.setrlimit(resource.RLIMIT_AS, (2**31, 2**31))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=lambda value: Path(value).resolve())
    parser.add_argument("--synthesis", type=lambda value: Path(value).resolve())
    parser.add_argument("--candidate", type=lambda value: Path(value).resolve())
    parser.add_argument("--link-worker", type=int)
    args = parser.parse_args()
    if args.synthesis is None:
        assert args.candidate is None and args.link_worker is None
        audit_baseline(args.output)
    else:
        assert args.candidate is not None
        if args.link_worker is not None:
            wait_for_receipt(args.synthesis / "linked_chip/receipt.json", args.link_worker,
                             "link_tri_oracle_parallel_chip.py")
        prepare(args.synthesis, args.candidate, args.output)
