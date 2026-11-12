"""Check the complete linked chip's paper-facing compute and controller hierarchy."""

import argparse
from collections import Counter
import json
from pathlib import Path

from audit_linked_layer_memory import inventory
from check_tri_oracle_paper300_gate import PAPER_RELATIVE, PAPER_SHA256
from prepare_tri_oracle_parallel_chip_synthesis import pin, read, verify
from run_tri_oracle_parallel_chip_synthesis import GIB, memory, wait_for_receipt
from verify_linked_placed_topology import module_index, parse_module, pin_fields
from verify_tri_oracle_mapped_paper_topology import audit_topology
from verify_tri_oracle_packed_down_weights import ROOT


def audit(code, top, targets):
    spans = module_index(code)
    _, ports, _, children, _ = parse_module(code, spans[top])
    assert ports["clk"] == ports["rst_n"] == ("input", None)
    dispatch, dispatch_fields = children["dispatch"]
    decoder, layer_fields = children["layer"]
    assert dispatch == "tri_oracle_chip_dispatch" and decoder in spans
    control, interface = map(pin_fields, (dispatch_fields, layer_fields))
    assert all(pins["clk"] == "clk" and pins["rst_n"] == "rst_n" for pins in (control, interface))
    for signal in ("command_valid", "command_ready", "command_opcode", "command_tag", "payload_valid",
                   "payload_ready", "payload_data", "response_valid", "response_ready", "response_tag"):
        assert signal in ports and control[signal] == signal, signal
    for index, signal in enumerate(("cfg_valid", "projection_valid", "frame_valid", "restore_valid", "head_valid", "row_valid")):
        assert interface[signal] == f"layer_command_valid[{index}]", signal
    assert control["layer_command_valid"] == "layer_command_valid"
    for lane in ("", "aux_"):
        data = lane + "rsp_data"
        assert ports[data] == ("input", (511, 0)) and interface[data] == data
        for signal in ("req_valid", "req_ready", "rsp_valid", "rsp_ready"):
            name = lane + signal
            assert name in ports and interface[name] == name, name
    topology = audit_topology(code, decoder, targets)
    return {"dispatch_module": dispatch, "mapped_decoder_module": decoder,
            "external_clock_direct_to_dispatch_and_decoder": True, "read_response_widths_bits": [512, 512],
            "topology": topology, "compiled_memories": dict(Counter(inventory(code, top).values()))}


def run(linked, output, link_worker=None):
    assert Path("/.dockerenv").is_file()
    receipt = linked / "receipt.json"
    if link_worker is None:
        link = read(receipt)
    else:
        link = wait_for_receipt(receipt, link_worker, "link_tri_oracle_joined_chip.py")
    assert link["state"] in {"parallel_chip_parent_linked_with_verified_mapped_imports",
                              "joined_chip_parent_linked_with_verified_mapped_imports"}
    available, anonymous = memory()
    assert available >= 15 * GIB and anonymous <= 6 * GIB, (available, anonymous)
    pins = {}
    netlist = linked / "chip.v"
    pin(pins, netlist, link["chip_sha256"])
    target = ROOT / "records/paper_result_targets.json"
    for path in (receipt, target, Path(__file__).resolve(), Path(audit_topology.__code__.co_filename).resolve()):
        pin(pins, path)
    pin(pins, ROOT / PAPER_RELATIVE, PAPER_SHA256)
    targets = read(target)
    assert targets["source"] == PAPER_RELATIVE
    measured = audit(netlist.read_text(), link["top"], targets)
    assert measured["compiled_memories"] == link["compiled_memories"]
    cores = [core for cluster in measured["topology"]["clusters"] for core in cluster["cores"]]
    assert len(cores) == 20
    verify(pins)
    result = {"state": "linked_chip_compute_and_command_hierarchy_verified", "candidate_sha256": link["chip_sha256"],
              "top": link["top"], "cores": len(cores), **measured,
              "scope": "Mapped compute, local redundancy units and command wiring. On-chip clock generation, "
                       "system memory integration and workload accuracy require separate verification.",
              "input_sha256": pins}
    with output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(result["state"], len(cores), sum(measured["compiled_memories"].values()), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("linked", "output"):
        parser.add_argument(name, type=lambda value: Path(value).resolve())
    parser.add_argument("--link-worker", type=int)
    run(**vars(parser.parse_args()))
