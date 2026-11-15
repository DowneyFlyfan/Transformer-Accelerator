"""Replace the simulated write-back glue with mapped gates for physical import."""

import argparse
from hashlib import file_digest
import json
import mmap
from pathlib import Path
import re

from audit_tri_oracle_mapped_redundancy import ENDMODULE, MODULE, TOP


CONTROL = "tri_oracle_linked_writeback_control"
OLD_GLUE = """   assign layer_command_ready[0] = wb_compute_ready && wb_cfg_ready;
   assign layer_done_error[0] = wb_compute_error || wb_failed || wb_packet_error;
   assign out_ready = wb_raw_ready || wb_failed;
   always @(posedge clk or negedge rst_n) begin
      if (!rst_n)
         wb_failed <= 1'b0;
      else if (layer_command_valid[0] && layer_command_ready[0])
         wb_failed <= 1'b0;
      else if (wb_packet_error)
         wb_failed <= 1'b1;
   end
"""
PIN_NETS = {
    "clk": "clk",
    "rst_n": "rst_n",
    "command_valid": "layer_command_valid[0]",
    "compute_ready": "wb_compute_ready",
    "writer_ready": "wb_cfg_ready",
    "compute_done": "layer_done_valid[0]",
    "compute_error": "wb_compute_error",
    "packet_error": "wb_packet_error",
    "writer_raw_ready": "wb_raw_ready",
    "command_ready": "layer_command_ready[0]",
    "compute_cfg_valid": "wb_compute_cfg_valid",
    "writer_cfg_valid": "wb_writer_cfg_valid",
    "done_error": "layer_done_error[0]",
    "out_ready": "out_ready",
    "writer_abort": "wb_writer_abort",
}
PROCEDURAL = re.compile(rb"(?m)^\s*(?:always(?:_ff|_comb|_latch)?|initial)\b")
BLOCK_BYTES = 4 << 20


def sha(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f"Expected one occurrence of {old.splitlines()[0]!r}")
    return text.replace(old, new)


def connect_control(top):
    top = replace_once(
        top,
        "   reg wb_failed;\n",
        "   wire wb_compute_cfg_valid, wb_writer_cfg_valid, wb_writer_abort;\n",
    )
    top = replace_once(
        top,
        ".cfg_valid(layer_command_valid[0] && wb_cfg_ready)",
        ".cfg_valid(wb_compute_cfg_valid)",
    )
    top = replace_once(
        top,
        ".frame_cfg_valid(layer_command_valid[0] && wb_compute_ready)",
        ".frame_cfg_valid(wb_writer_cfg_valid)",
    )
    top = replace_once(
        top,
        ".frame_abort(layer_done_valid[0] && wb_compute_error)",
        ".frame_abort(wb_writer_abort)",
    )
    pins = ",\n".join(f"      .{pin}({net})" for pin, net in PIN_NETS.items())
    top = replace_once(
        top, OLD_GLUE, f"   {CONTROL} writeback_control (\n{pins}\n   );\n"
    )
    if PROCEDURAL.search(top.encode()):
        raise ValueError("The rewritten top contains procedural logic")
    return top.encode()


def copy_region(source, destination, start, end):
    for offset in range(start, end, BLOCK_BYTES):
        destination.write(source[offset : min(offset + BLOCK_BYTES, end)])


def link(candidate, expected, control, libraries, output):
    candidate_sha = sha(candidate)
    if candidate_sha != expected:
        raise ValueError("The linked replay netlist identity changed")
    includes = [*libraries, control]
    pins = {str(path): sha(path) for path in includes}
    mapped_control = control.read_bytes()
    (header,) = re.findall(
        rb"(?ms)^module " + CONTROL.encode() + rb"\s*\((.*?)\);", mapped_control
    )
    actual_pins = {word.decode() for word in re.findall(rb"\w+", header)}
    if actual_pins != PIN_NETS.keys() or PROCEDURAL.search(mapped_control):
        raise ValueError(
            "Unexpected interface or procedural logic in the mapped controller"
        )

    included = {}
    for path in includes:
        data = path.read_bytes()
        masters = [match[1] for match in MODULE.finditer(data)]
        if (
            not masters
            or len(set(masters)) != len(masters)
            or included.keys() & set(masters)
        ):
            raise ValueError(f"Empty library or duplicate module in {path}")
        if PROCEDURAL.search(data):
            raise ValueError(f"Procedural logic in mapped library {path}")
        included.update((master, path) for master in masters)

    with (
        candidate.open("rb") as stream,
        mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as source,
    ):
        definitions = list(MODULE.finditer(source))
        source_masters = {match[1] for match in definitions}
        if len(source_masters) != len(definitions) or source_masters & included.keys():
            raise ValueError("Repeated module in the linked netlist")
        (top,) = (match for match in definitions if match[1].decode() == TOP)
        end = ENDMODULE.search(source, top.end()).end()
        if PROCEDURAL.search(source, 0, top.start()) or PROCEDURAL.search(source, end):
            raise ValueError("Procedural logic outside the mapped top")
        new_top = connect_control(source[top.start() : end].decode())
        with output.open("xb") as linked:
            copy_region(source, linked, 0, top.start())
            linked.write(new_top)
            copy_region(source, linked, end, len(source))
            for path in includes:
                linked.write(b"\n")
                with path.open("rb") as library:
                    while block := library.read(BLOCK_BYTES):
                        linked.write(block)

    if sha(candidate) != candidate_sha or any(
        sha(path) != pins[str(path)] for path in includes
    ):
        raise ValueError("A source input changed during linking")
    return {
        "source_candidate_sha256": candidate_sha,
        "structural_netlist_sha256": sha(output),
        "kept_topology_module_definitions": len(source_masters) - 1,
        "added_library_module_definitions": len(included),
        "writeback_control_pins": PIN_NETS,
        "library_sha256": pins,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("control", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--candidate-sha256", required=True)
    parser.add_argument("--library", action="append", type=Path, required=True)
    args = parser.parse_args()
    result = link(
        args.candidate, args.candidate_sha256, args.control, args.library, args.output
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
