"""Keep the feed-forward packet probe inside the chip that already consumes it."""

import argparse
import json
import mmap
from pathlib import Path
import re

from audit_tri_oracle_mapped_redundancy import ENDMODULE, MODULE, TOP
from link_tri_oracle_writeback_control import copy_region, replace_once, sha


ROOT = Path(__file__).resolve().parents[1]
PROBES = {
    "out_ready": 1,
    "out_valid": 1,
    "out_last": 1,
    "out_token": 4,
    "out_tag": 32,
    "out_start": 16,
    "out_count": 8,
    "out_data": 5120,
}


def internalize(source):
    header, body = source.split(");", 1)
    module, port_list = header.split("(", 1)
    ports = port_list.split(",")
    names = [item.strip() for item in ports]
    if len(names) != len(set(names)) or not PROBES.keys() <= set(names):
        raise ValueError("Expected the mapped chip port list with all eight write-back probes")

    writer, = re.findall(r"(?ms)^[ \t]+tri_oracle_decoder_bank_writeback bank_writeback\s*\((.*?)\);", body)
    controller, = re.findall(
        r"(?ms)^[ \t]+tri_oracle_linked_writeback_control writeback_control\s*\((.*?)\);", body
    )
    if ".out_ready(out_ready)" not in controller:
        raise ValueError("The chip controller does not drive feed-forward backpressure")
    for signal, width in PROBES.items():
        if signal != "out_ready" and f".in_{signal[4:]}({signal})" not in writer:
            raise ValueError(f"The on-chip writer is not a consumer of {signal}")
        shape = f"[{width - 1}:0] " if width > 1 else ""
        body = replace_once(body, f"   output {shape}{signal};", f"   wire {shape}{signal};")
    kept = [item for item in ports if item.strip() not in PROBES]
    return module + "(" + ",".join(kept) + ");" + body


def link(candidate, output):
    source_record = ROOT / "records/tri_oracle_descriptor_repeaters_seed.json"
    parent = json.loads(source_record.read_bytes())["candidate_sha256"]
    if sha(candidate) != parent:
        raise ValueError("Unexpected mapped candidate")
    with candidate.open("rb") as file, mmap.mmap(file.fileno(), 0, access=mmap.ACCESS_READ) as source:
        top, = (row for row in MODULE.finditer(source) if row[1].decode() == TOP)
        end = ENDMODULE.search(source, top.end()).end()
        rewritten = internalize(source[top.start():end].decode())
        with output.open("xb") as target:
            copy_region(source, target, 0, top.start())
            target.write(rewritten.encode())
            copy_region(source, target, end, len(source))
    if sha(candidate) != parent:
        raise ValueError("Parent netlist changed while internalizing probe ports")
    return dict(parent_candidate_sha256=parent, candidate_sha256=sha(output),
                removed_output_port_bits=sum(PROBES.values()), modified_module=TOP)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(link(args.candidate, args.output), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
