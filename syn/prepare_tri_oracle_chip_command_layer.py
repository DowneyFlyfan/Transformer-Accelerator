"""Bind chip command descriptors to the verified shared-memory layer interface."""

import argparse
import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
BOUNDARY = ROOT / ".cache/physical/shared_memory_layer_boundary"
LAYER = "tri_oracle_shared_memory_layer"
TOP = "tri_oracle_chip_command_layer"
CONTROLLER = ROOT / "verilog/tri_oracle_chip_dispatch.sv"

# Descriptor fields are sent in this order, beginning at bit zero.
OPERATIONS = (
    ("feedforward", ("cfg_valid", "cfg_ready"), ("done_valid", "done_ready", "done_error"),
     ("cfg_tag", "done_tag"), (
         "cfg_tokens", "cfg_input_features", "cfg_intermediate_features", "cfg_output_features",
         "cfg_activation_base", "cfg_activation_stride", "cfg_gate_base", "cfg_up_base",
         "cfg_down_base", "cfg_intermediate_base", "cfg_gate_sign_base", "cfg_up_sign_base",
         "cfg_gate_shifts", "cfg_up_shifts", "cfg_down_shifts", "cfg_activation_shifts", "cfg_epsilon_q16")),
    ("projection", ("projection_valid", "projection_ready"),
     ("projection_done_valid", "projection_done_ready", "projection_done_error"),
     ("projection_tag", "projection_done_tag"), (
         "projection_tokens", "projection_first_head", "projection_heads", "projection_slot",
         "projection_activation_base", "projection_weight_base", "projection_cache_base",
         "projection_shifts", "projection_shift_biases")),
    ("token_merge", ("frame_valid", "frame_ready"), ("frame_done_valid", "frame_done_ready", "frame_done_error"),
     (), ("frame_new_image", "frame_layer", "frame_image_start", "frame_minimum_matches")),
    ("token_restore", ("restore_valid", "restore_ready"),
     ("restore_done_valid", "restore_done_ready", "restore_done_error"), (), ("restore_layer",)),
    ("head_prediction", ("head_valid", "head_ready"), ("head_done_valid", "head_done_ready", "head_done_error"),
     ("head_tag", "head_done_tag"), ("head_id", "head_alpha", "head_tokens", "head_ratio_num", "head_ratio_den",
                                   "head_query_base", "head_key_base")),
    ("attention_row", ("row_valid", "row_ready"), ("result_valid", "result_ready", "result_error"),
     ("row_tag", "result_tag"), ("row_head", "row_position", "row_key_count", "row_score_shift",
                               "row_query_addr", "row_key_base")),
)
EXPECTED_WORDS = (15, 9, 1, 1, 3, 3)
HOST = {
    "command_valid": ("input", 1), "command_ready": ("output", 1),
    "command_opcode": ("input", 3), "command_tag": ("input", 32),
    "payload_valid": ("input", 1), "payload_ready": ("output", 1),
    "payload_data": ("input", 64), "payload_last": ("input", 1),
    "response_valid": ("output", 1), "response_ready": ("input", 1),
    "response_error": ("output", 1), "response_opcode": ("output", 3), "response_tag": ("output", 32),
}
WIRES = {
    "layer_command_valid": "[5:0]", "layer_command_ready": "[5:0]",
    "layer_command_tag": "[31:0]", "layer_command_payload": "[959:0]",
    "layer_done_valid": "[5:0]", "layer_done_ready": "[5:0]",
    "layer_done_error": "[5:0]", "layer_done_tag": "[191:0]",
}


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def declared_ports(text):
    header, body = text.split(");", 1)
    order = re.search(rf"\bmodule\s+{LAYER}\s*\((.*)", header, re.S)[1]
    names = [name.strip() for name in order.split(",")]
    ports = {}
    for direction, msb, name in re.findall(r"(?m)^\s*(input|output)\s+(?:\[(\d+):0\]\s+)?(\w+);", body):
        assert name not in ports
        ports[name] = direction, int(msb) + 1 if msb else 1
    assert len(names) == len(ports) and set(names) == ports.keys()
    return {name: ports[name] for name in names}


def connect(ports):
    bound = {}
    descriptors = []
    tag_defaults = []

    def bind(port, direction, width, source):
        assert ports[port] == (direction, width) and port not in bound, port
        bound[port] = source

    for index, (name, command, done, tags, fields) in enumerate(OPERATIONS):
        bind(command[0], "input", 1, f"layer_command_valid[{index}]")
        bind(command[1], "output", 1, f"layer_command_ready[{index}]")
        bind(done[0], "output", 1, f"layer_done_valid[{index}]")
        bind(done[1], "input", 1, f"layer_done_ready[{index}]")
        bind(done[2], "output", 1, f"layer_done_error[{index}]")
        if tags:
            bind(tags[0], "input", 32, "layer_command_tag")
            bind(tags[1], "output", 32, f"layer_done_tag[{32 * index} +: 32]")
        else:
            tag_defaults.append(f"  assign layer_done_tag[{32 * index} +: 32] = '0;\n")
        offset = 0
        layout = {}
        for field in fields:
            width = ports[field][1]
            bind(field, "input", width, f"layer_command_payload[{offset} +: {width}]")
            layout[field] = {"lsb": offset, "width": width}
            offset += width
        words = (offset + 63) // 64
        assert words == EXPECTED_WORDS[index] and offset <= 960
        descriptors.append(dict(operation=name, opcode=index, payload_bits=offset, words=words, fields=layout,
                                layer_completion_tags=tags))
    outside = {name: shape for name, shape in ports.items() if name not in bound}
    assert not HOST.keys() & outside.keys()
    external = outside | HOST
    return external, {name: bound.get(name, name) for name in ports}, descriptors, tag_defaults


def declaration(name, shape):
    direction, width = shape
    vector = f" [{width - 1}:0]" if width > 1 else ""
    return f"  {direction} logic{vector} {name}"


def instance(module, name, connections):
    ports = ",\n".join(f"    .{port}({expression})" for port, expression in connections.items())
    return f"  {module} {name} (\n{ports}\n  );\n"


def main(output):
    source = BOUNDARY / "prepared/boundary.sv"
    link_file = BOUNDARY / "linked/receipt.json"
    linkage = json.loads(link_file.read_text())
    source_hash = sha(source)
    assert linkage["state"] == "shared_memory_boundary_mapped_and_linked"
    assert linkage["input_sha256"][str(source)] == source_hash
    ports = declared_ports(source.read_text())
    bits = sum(width for _, width in ports.values())
    assert bits == linkage["boundary_signal_bits"] == 13299
    external, connections, descriptors, tag_defaults = connect(ports)
    total = sum(width for _, width in external.values())
    wires = "".join(f"  logic {shape} {name};\n" for name, shape in WIRES.items())
    control = {name: name for name in ("clk", "rst_n", *HOST, *WIRES)}
    header = ",\n".join(declaration(name, shape) for name, shape in external.items())
    code = (f"`timescale 1ns/1ps\nmodule {TOP} (\n{header}\n);\n"
            + wires + "".join(tag_defaults) + instance("tri_oracle_chip_dispatch", "dispatch", control)
            + instance(LAYER, "layer", connections) + "endmodule\n")
    output.mkdir()
    wrapper = output / f"{TOP}.sv"
    wrapper.write_text(code)
    result = dict(state="chip_command_layer_port_bindings_prepared", wrapper=TOP, layer=LAYER,
                  shared_layer_netlist_sha256=linkage["candidate_netlist_sha256"],
                  boundary_signal_bits_before=bits, boundary_signal_bits_after=total, operations=descriptors,
                  input_sha256={str(path): sha(path) for path in (source, link_file, CONTROLLER, Path(__file__))},
                  wrapper_sha256=sha(wrapper))
    with (output / "interface.json").open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(result["state"], f"{bits} -> {total} signal bits", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    main(args.output.resolve())
