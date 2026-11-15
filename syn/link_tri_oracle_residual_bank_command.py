"""Bind mapped shared-bank command arbitration to an exact placed export."""

import argparse
import json
import mmap
from pathlib import Path
import re

from audit_tri_oracle_mapped_redundancy import ENDMODULE, MODULE, TOP
from link_tri_oracle_writeback_control import PROCEDURAL, copy_region, replace_once, sha


CONTROL = "tri_oracle_residual_bank_command"
GRANT = "residual_bank_granted"
NEW_WIRES = f"   wire {GRANT}, residual_grouped_valid, residual_grouped_ready;\n"
PINS = {
    "clk": "clk",
    "rst_n": "rst_n",
    "residual_request": "residual_lease",
    "probability_grant": "{probability_grant[3], probability_grant[2], probability_grant[1], probability_grant[0]}",
    "grouped_valid": "batch_start_valid[0]",
    "grouped_core_ready": "residual_grouped_ready",
    "grouped_ready": "batch_start_ready[0]",
    "grouped_core_valid": "residual_grouped_valid",
    "grouped_done_valid": "batch_done_valid[0]",
    "grouped_done_ready": "batch_done_ready[0]",
    "projection_cfg_valid": "direct_cfg_valid",
    "projection_cfg_ready": "direct_cfg_ready",
    "residual_read_valid": "proj_read_valid",
    "residual_read_ready": "proj_read_ready",
    "residual_response_valid": "proj_response_valid",
    "writeback_cfg_valid": "wb_writer_cfg_valid",
    "writeback_cfg_ready": "wb_cfg_ready",
    "writeback_active": "wb_frame_active",
    "residual_granted": GRANT,
}
UPDATES = {
    # Grouped results leave through the raw result ports. The shared external
    # ready pin also serves the transformed feed-forward result stream.
    ("tri_oracle_grouped_cluster_batch_cells", "batch"): {
        "result_ready": ("out_ready", "wb_out_ready"),
    },
    ("tri_oracle_grouped_attention_command_cells_1", "grouped_0"): {
        "command_valid": ("batch_start_valid[0]", "residual_grouped_valid"),
        "command_ready": ("batch_start_ready[0]", "residual_grouped_ready"),
    },
    ("tri_oracle_shared_memory_layer_PACKED_FEEDFORWARD_WEIGHTS1_parallel_chip", "layer"): {
        "residual_lease": ("residual_lease", GRANT),
    },
    ("tri_oracle_projection_bus_normalize", "direct_projection"): {
        "lease_granted": ("residual_lease", GRANT),
    },
    ("tri_oracle_decoder_bank_writeback", "bank_writeback"): {
        "lease_granted": ("residual_lease", GRANT),
    },
}


def connect(top):
    for (master, instance), updates in UPDATES.items():
        pattern = rf"(?ms)^[ \t]+{master} {instance}\s*\(.*?\);"
        original, = re.findall(pattern, top)
        updated = original
        for pin, (old, new) in updates.items():
            updated = replace_once(updated, f".{pin}({old})", f".{pin}({new})")
        top = replace_once(top, original, updated)
    # Only the port and declaration may still name the external request.
    if len(re.findall(r"\bresidual_lease\b(?!\s*\()", top)) != 2:
        raise ValueError("Unexpected direct user of the residual lease")

    top = replace_once(top, "   input residual_lease;\n", "   input residual_lease;\n" + NEW_WIRES)
    pins = ",\n".join(f"      .{pin}({net})" for pin, net in PINS.items())
    return replace_once(
        top, "endmodule", f"   {CONTROL} residual_bank_command (\n{pins}\n   );\nendmodule"
    )


def link(candidate, expected_candidate, control, expected_control, output):
    candidate_id, control_id = sha(candidate), sha(control)
    if (candidate_id, control_id) != (expected_candidate, expected_control):
        raise ValueError("Linked input digest changed")
    mapped = control.read_bytes()
    header, = re.findall(rb"(?ms)^module " + CONTROL.encode() + rb"\s*\((.*?)\);", mapped)
    control_names = [match[1] for match in MODULE.finditer(mapped)]
    if set(re.findall(r"\w+", header.decode())) != PINS.keys() or PROCEDURAL.search(mapped):
        raise ValueError("Unexpected mapped command controller interface")
    if len(set(control_names)) != len(control_names):
        raise ValueError("Duplicate command controller module")
    with candidate.open("rb") as handle, mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as source:
        definitions = list(MODULE.finditer(source))
        if set(control_names).intersection(match[1] for match in definitions):
            raise ValueError("Command controller collides with a placed master")
        original, = (match for match in definitions if match[1].decode() == TOP)
        end = ENDMODULE.search(source, original.end()).end()
        top = connect(source[original.start():end].decode())
        with output.open("xb") as linked:
            copy_region(source, linked, 0, original.start())
            linked.write(top.encode())
            copy_region(source, linked, end, len(source))
            linked.write(b"\n" + mapped)
    if (sha(candidate), sha(control)) != (candidate_id, control_id):
        raise ValueError("Linked inputs changed during export")
    return {
        "parent_cold_export_sha256": candidate_id,
        "mapped_command_sha256": control_id,
        "candidate_sha256": sha(output),
        "unchanged_module_definitions": len(definitions) - 1,
        "added_module_definitions": [name.decode() for name in control_names],
        "command_connections": PINS,
        "changed_pins_by_instance": {
            instance: updates for (_, instance), updates in UPDATES.items()
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("control", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--candidate-sha256", required=True)
    parser.add_argument("--control-sha256", required=True)
    args = parser.parse_args()
    print(json.dumps(link(args.candidate, args.candidate_sha256, args.control,
                          args.control_sha256, args.output), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
