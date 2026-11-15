"""Buffer residual grant at the six consumers of the linked command wrapper."""

import argparse
import json
import mmap
from pathlib import Path
import re

from audit_tri_oracle_mapped_redundancy import ENDMODULE, MODULE, TOP
from link_tri_oracle_residual_bank_command import GRANT
from link_tri_oracle_writeback_control import copy_region, replace_once, sha


ROOT = Path(__file__).resolve().parents[1]
CORE_BUFFER = "BUFFD4BWP12T40P140"
BUFFERED_LOCAL = "buffered_residual_grant"
SPECIALISTS = {
    "direct_projection": ("tri_oracle_projection_bus_normalize", "BUFFD2BWP12T40P140"),
    "bank_writeback": ("tri_oracle_decoder_bank_writeback", "BUFFD1BWP12T40P140"),
}


def buffer_instance(cell, name, source, output):
    return f"   {cell} {name} (.I({source}), .Z({output}));\n"


def top_with_buffers(body):
    tail = []
    wires = []
    for instance, (master, cell) in SPECIALISTS.items():
        pattern = rf"(?ms)^[ \t]+{master} {instance}\s*\(.*?\);"
        original, = re.findall(pattern, body)
        signal = f"residual_grant_{instance}"
        wires.append(signal)
        buffered = replace_once(original, f".lease_granted({GRANT})", f".lease_granted({signal})")
        body = replace_once(body, original, buffered)
        tail.append(buffer_instance(cell, f"{instance}_grant_buffer", GRANT, signal))
    declaration = "   input residual_lease;\n"
    body = replace_once(body, declaration, declaration + f"   wire {', '.join(wires)};\n")
    return replace_once(body, "endmodule", "".join(tail) + "endmodule")


def core_with_buffer(body):
    old = ".residual_lease(residual_lease)"
    if body.count(old) != 2:
        raise ValueError("The core guard and memory path must both consume the grant")
    declaration = "   input residual_lease;\n"
    body = replace_once(body, declaration, declaration + f"   wire {BUFFERED_LOCAL};\n")
    body = body.replace(old, f".residual_lease({BUFFERED_LOCAL})")
    gate = buffer_instance(CORE_BUFFER, "residual_grant_buffer", "residual_lease", BUFFERED_LOCAL)
    return replace_once(body, "endmodule", gate + "endmodule")


def link(candidate, output):
    source_record = ROOT / "records/tri_oracle_residual_bank_command_binding.json"
    guard_record = ROOT / "records/tri_oracle_guarded_scalar_whole_chip_cold_reload.json"
    before = json.loads(source_record.read_bytes())["candidate_sha256"]
    core_modules = set(json.loads(guard_record.read_bytes())["verified_load_kind_mappings"])
    if sha(candidate) != before or len(core_modules) != 4:
        raise ValueError("Expected the verified linked command netlist and four guarded cores")
    rewritten = set()
    with candidate.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as source:
        with output.open("xb") as updated:
            cursor = 0
            for entry in MODULE.finditer(source):
                module = entry[1].decode()
                if module not in core_modules and module != TOP:
                    continue
                if module in rewritten:
                    raise ValueError(f"Duplicate module {module}")
                start, end = entry.start(), ENDMODULE.search(source, entry.end()).end()
                original = source[start:end].decode()
                mapped = top_with_buffers(original) if module == TOP else core_with_buffer(original)
                copy_region(source, updated, cursor, start)
                updated.write(mapped.encode())
                cursor = end
                rewritten.add(module)
            copy_region(source, updated, cursor, len(source))
    if rewritten != core_modules | {TOP} or sha(candidate) != before:
        raise ValueError("The buffers could not be bound to the verified candidate")
    return {
        "parent_candidate_sha256": before,
        "candidate_sha256": sha(output),
        "modified_modules": sorted(rewritten),
        "added_buffer_cells": 6,
        "core_buffer": CORE_BUFFER,
        "specialist_buffers": {name: cell for name, (_, cell) in SPECIALISTS.items()},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(link(args.candidate, args.output), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
