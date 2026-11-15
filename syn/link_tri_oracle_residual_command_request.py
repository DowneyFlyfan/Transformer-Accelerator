"""Drive the existing residual arbiter from the validated feed-forward command."""

import argparse
import json
import mmap
from pathlib import Path
import re

from audit_tri_oracle_mapped_redundancy import ENDMODULE, MODULE, TOP
from link_tri_oracle_writeback_control import PROCEDURAL, copy_region, replace_once, sha


ROOT = Path(__file__).resolve().parents[1]
CONTROL = "tri_oracle_residual_command_request"
REQUEST = "residual_dispatch_request"
PINS = {
    "clk": "clk",
    "rst_n": "rst_n",
    "override_request": "residual_lease",
    "command_valid": "layer_command_valid[0]",
    "command_ready": "layer_command_ready[0]",
    "done_valid": "layer_done_valid[0]",
    "done_ready": "layer_done_ready[0]",
    "residual_request": REQUEST,
}


def connect(top):
    arbiter, = re.findall(
        r"(?ms)^[ \t]+tri_oracle_residual_bank_command residual_bank_command\s*\(.*?\);",
        top,
    )
    rewired = replace_once(arbiter, ".residual_request(residual_lease)", f".residual_request({REQUEST})")
    top = replace_once(top, arbiter, rewired)
    declaration = "   input residual_lease;\n"
    top = replace_once(top, declaration, declaration + f"   wire {REQUEST};\n")
    pins = ",\n".join(f"      .{name}({signal})" for name, signal in PINS.items())
    return replace_once(
        top, "endmodule", f"   {CONTROL} residual_command_request (\n{pins}\n   );\nendmodule"
    )


def link(candidate, controller, mapped_sha256, output):
    buffered = ROOT / "records/tri_oracle_residual_grant_buffered_seed.json"
    expected = json.loads(buffered.read_bytes())["candidate_sha256"]
    if sha(candidate) != expected or sha(controller) != mapped_sha256:
        raise ValueError("Unexpected buffered parent or mapped request controller")
    mapped = controller.read_bytes()
    names = [match[1].decode() for match in MODULE.finditer(mapped)]
    header, = re.findall(rb"(?ms)^module " + CONTROL.encode() + rb"\s*\((.*?)\);", mapped)
    if names != [CONTROL] or set(re.findall(r"\w+", header.decode())) != PINS.keys() or PROCEDURAL.search(mapped):
        raise ValueError("Unexpected mapped residual request module")
    with candidate.open("rb") as file, mmap.mmap(file.fileno(), 0, access=mmap.ACCESS_READ) as source:
        definitions = list(MODULE.finditer(source))
        if any(entry[1].decode() == CONTROL for entry in definitions):
            raise ValueError("Request controller is already present")
        baseline, = (entry for entry in definitions if entry[1].decode() == TOP)
        end = ENDMODULE.search(source, baseline.end()).end()
        top = connect(source[baseline.start():end].decode())
        with output.open("xb") as linked:
            copy_region(source, linked, 0, baseline.start())
            linked.write(top.encode())
            copy_region(source, linked, end, len(source))
            linked.write(b"\n" + mapped)
    if sha(candidate) != expected or sha(controller) != mapped_sha256:
        raise ValueError("Input changed while linking residual request controller")
    return dict(candidate_sha256=sha(output), parent_candidate_sha256=expected, mapped_sha256=mapped_sha256,
                unchanged_module_definitions=len(definitions)-1, request_controller_connections=PINS)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("controller", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--control-sha256", required=True)
    args = parser.parse_args()
    print(json.dumps(link(args.candidate, args.controller, args.control_sha256, args.output),
                     indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
