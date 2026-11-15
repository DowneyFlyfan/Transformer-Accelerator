"""Carry the residual write-back scales in the feed-forward command descriptor."""

import argparse
import json
import mmap
from pathlib import Path
import re

from audit_tri_oracle_mapped_redundancy import ENDMODULE, MODULE, TOP
from link_tri_oracle_writeback_control import copy_region, replace_once, sha


ROOT = Path(__file__).resolve().parents[1]
SCALES = "wb_frame_down_shifts"


def connect(top):
    # Opcode zero captures 15 64-bit words. Its compute descriptor ends at
    # bit 949. The writer samples these two 5-bit scales when that command
    # launches, even if memory-bank arbitration delayed its acceptance.
    port, = re.findall(rf"(?m)^[ \t]+{SCALES},[ \t]*\n", top)
    top = replace_once(top, port, "")
    top = replace_once(top, f"   input [9:0] {SCALES};\n", "")
    top = replace_once(
        top,
        f".frame_down_shifts({SCALES})",
        ".frame_down_shifts(layer_command_payload[959:950])",
    )
    if re.search(rf"\b{SCALES}\b", top):
        raise ValueError("An external write-back scale connection remains")
    return top


def link(candidate, output):
    parent_record = ROOT / "records/tri_oracle_residual_command_request_mapping.json"
    expected = json.loads(parent_record.read_bytes())["candidate_sha256"]
    if sha(candidate) != expected:
        raise ValueError("Unexpected autonomous-command candidate")
    with candidate.open("rb") as stream, mmap.mmap(
        stream.fileno(), 0, access=mmap.ACCESS_READ
    ) as source:
        definitions = list(MODULE.finditer(source))
        top, = (match for match in definitions if match[1].decode() == TOP)
        end = ENDMODULE.search(source, top.end()).end()
        rewritten = connect(source[top.start():end].decode())
        with output.open("xb") as destination:
            copy_region(source, destination, 0, top.start())
            destination.write(rewritten.encode())
            copy_region(source, destination, end, len(source))
    if sha(candidate) != expected:
        raise ValueError("Candidate changed while linking write-back scales")
    return {
        "parent_candidate_sha256": expected,
        "candidate_sha256": sha(output),
        "unchanged_module_definitions": len(definitions) - 1,
        "removed_input_bits": 10,
        "feedforward_payload_words": 15,
        "writer_scale_bits": [959, 950],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(link(args.candidate, args.output), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
