"""Relink the matched response-address logic with the verified buffered layer."""

import argparse
from contextlib import ExitStack
from hashlib import file_digest, sha256
import json
import mmap
from pathlib import Path
import re
import resource
import shutil

from audit_tri_oracle_load_address_cone import audit
from verify_linked_placed_topology import bits, parse_module, pin_fields


ROOT = Path(__file__).resolve().parents[1]
PHYSICAL = ROOT / ".cache/physical"
COMPACT = PHYSICAL / "wac_budgeted_parent_boundary/compact_load_transport"
MATCHED = COMPACT / "weight_data_unmask/response_address_trial/matched_mapping"
BUFFERED = COMPACT / "weight_data_unmask/row_enable_bank_buffer_trial/attention_select_buffer_trial"
MODELS = PHYSICAL / "library/tcbn28hpcplusbwp12t40p140.v"
MODULE = re.compile(rb"(?ms)^module\s+([\w$]+)\s*\(.*?^endmodule\b")


def sha(path):
    with Path(path).open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def read(path):
    return json.loads(path.read_text())


def index(source):
    modules = {}
    for match in MODULE.finditer(source):
        name = match[1].decode()
        assert name not in modules, name
        modules[name] = match.span()
    assert modules
    return modules


def block(source, modules, name):
    return source[slice(*modules[name])]


def parsed(source, modules, name):
    code = block(source, modules, name).decode()
    return parse_module(code, (0, len(code)))


def consumers(source, modules, masters):
    alternatives = b"|".join(re.escape(name.encode()) for name in sorted(masters))
    pattern = re.compile(rb"(?m)^[ \t]+(" + alternatives + rb")\s+([^\s(]+)\s*\(")
    return {(owner, match[2].decode(), match[1].decode()) for owner, (first, last) in modules.items()
            for match in pattern.finditer(source, first, last)}


def open_map(stack, path):
    stream = stack.enter_context(path.open("rb"))
    return stack.enter_context(mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ))


def copy_slice(target, source, start, end):
    chunk = 4 * 1024**2
    for offset in range(start, end, chunk):
        target.write(source[offset:min(offset + chunk, end)])


def run(output):
    resource.setrlimit(resource.RLIMIT_AS, (1024**3,) * 2)
    assert shutil.disk_usage(output.parent).free >= 12 * 2**30
    reference = ROOT / "records/wac_response_address_mapped_result.json"
    verified = read(reference)
    assert verified["state"] == "response_address_decoupling_verified_in_matched_compact_mapping"
    assert not verified["candidate_address_bits_dependent_on_response_valid"]
    assert verified["write_valid_dependency_preserved"] is True
    assert verified["trained_source_exact_outputs"] == 32768
    assert all(sha(ROOT / name) == digest for name, digest in verified["evidence_sha256"].items())

    old_path = BUFFERED / "candidate.v"
    mapped_path = MATCHED / "netlist.v"
    control_path = COMPACT / "mapped_tensor/netlist.v"
    placement_path = BUFFERED / "physical_comparison/receipt.json"
    attention_path = BUFFERED / "integrated_attention/receipt.json"
    setup_path = BUFFERED / "prepared.json"
    setup, attention, placement = map(read, (setup_path, attention_path, placement_path))
    assert attention["state"] == "attention_capture_select_buffer_candidate_replayed_exactly"
    assert attention["replay"]["native_exit_status"] == 0 and attention["compiled_memories"] == 623
    assert sha(old_path) == setup["candidate_sha256"] == attention["candidate_sha256"]
    assert placement["evidence_sha256"][str(old_path)] == sha(old_path)
    paths = (reference, old_path, mapped_path, control_path, placement_path, attention_path,
             setup_path, MODELS, Path(__file__).resolve(), Path(audit.__code__.co_filename).resolve(),
             Path(parse_module.__code__.co_filename).resolve())
    pins = {str(path.relative_to(ROOT)): sha(path) for path in paths}

    tensor = verified["mapped_top"]
    with ExitStack() as stack:
        old, mapped, control = (open_map(stack, path) for path in (old_path, mapped_path, control_path))
        old_modules, mapped_modules, control_modules = map(index, (old, mapped, control))
        old_top, new_top = (parsed(source, modules, tensor) for source, modules in
                            ((old, old_modules), (mapped, mapped_modules)))
        assert old_top[:2] == new_top[:2]
        fabric, sequencer = (old_top[3][name][0] for name in ("fabric", "sequencer"))
        assert [new_top[3][name][0] for name in ("fabric", "sequencer")] == [fabric, sequencer]
        assert {name for name, (master, _) in new_top[3].items() if master in mapped_modules} == {"fabric", "sequencer"}
        cuts = {tensor, sequencer}
        for master in cuts:
            assert block(old, old_modules, master) == block(control, control_modules, master)
        old_seq, new_seq = (parsed(source, modules, sequencer) for source, modules in
                            ((old, old_modules), (mapped, mapped_modules)))
        assert old_seq[:2] == new_seq[:2]
        assert not any(master in mapped_modules for master, _ in new_seq[3].values())
        uses = consumers(old, old_modules, cuts)
        tensor_uses = [entry for entry in uses if entry[2] == tensor]
        assert len(tensor_uses) == 1 and tensor_uses[0][1] == "tensor"
        assert uses - set(tensor_uses) == {(tensor, "sequencer", sequencer)}
        assert consumers(mapped, mapped_modules, cuts) == {(tensor, "sequencer", sequencer)}

        old_fabric, mapped_fabric = (parsed(source, modules, fabric) for source, modules in
                                     ((old, old_modules), (mapped, mapped_modules)))
        assert old_fabric[:2] == mapped_fabric[:2]
        pins_before, pins_after = (pin_fields(view[3]["fabric"][1]) for view in (old_top, new_top))
        assert pins_before.keys() == pins_after.keys()
        assert {pin.removeprefix("\\") for pin in pins_before} == old_fabric[1].keys()
        for pin in pins_before:
            old_width = len(bits(pins_before[pin], old_top[2]))
            new_width = len(bits(pins_after[pin], new_top[2]))
            assert old_width == new_width, pin

        output.mkdir()
        destination = output / "candidate.v"
        with destination.open("xb") as target:
            cursor = 0
            for master in sorted(cuts, key=lambda name: old_modules[name][0]):
                first, last = old_modules[master]
                copy_slice(target, old, cursor, first)
                target.write(block(mapped, mapped_modules, master))
                cursor = last
            copy_slice(target, old, cursor, len(old))
        emitted = open_map(stack, destination)
        emitted_modules = index(emitted)
        assert emitted_modules.keys() == old_modules.keys()
        for name in emitted_modules:
            reference_bytes = block(mapped, mapped_modules, name) if name in cuts else block(old, old_modules, name)
            assert sha256(block(emitted, emitted_modules, name)).digest() == sha256(reference_bytes).digest(), name
        assert consumers(emitted, emitted_modules, cuts) == uses

    assert all(sha(ROOT / name) == digest for name, digest in pins.items())
    result = {
        "state": "mapped_response_address_logic_linked_with_buffered_fabric_preserved",
        "top": setup["top"], "tensor": tensor, "fabric": fabric,
        "replaced_module_definitions": sorted(cuts), "retained_module_definitions": len(old_modules) - len(cuts),
        "verified_fabric_ports": len(pins_after), "candidate_sha256": sha(destination),
        "input_sha256": pins,
        "scope": "Exact mapped tensor and sequencer replacement. The retained fabric and both buffer edits are "
                 "byte-identical to the replayed baseline. Native functional replay and placement timing remain pending.",
    }
    with (output / "receipt.json").open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(result["state"], result["retained_module_definitions"], result["verified_fabric_ports"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=lambda path: Path(path).resolve())
    run(parser.parse_args().output)
