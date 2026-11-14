"""Expose four existing compiled input banks on the current placement export."""

import argparse
from collections import Counter, defaultdict
from hashlib import file_digest
import json
import mmap
from pathlib import Path
import re

from audit_tri_oracle_mapped_redundancy import CHILD, ENDMODULE, MODULE, TOP, hierarchy


ROOT = Path.cwd()
COMMON = ("layer", "layer", "feedforward", "compute", "compute", "tensor", "fabric",
          r"\clusters[0].unit", r"\selected_bank0.block_instance", "source_cluster", "implementation")
PORTS = {b"residual_lease": (b"input", 1), b"residual_ce_n": (b"input", 1),
         b"residual_we_n": (b"input", 1), b"residual_addr": (b"input", 9),
         b"residual_d": (b"input", 256), b"residual_q": (b"output", 256)}
MACRO = "TS5N28HPCPSVTA512X64M4F"
PIN = re.compile(rb"\.(\w+)\s*\(([^()]*)\)")


def digest(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def extend(body, width):
    header, beginning, remaining = body.partition(b");")
    assert beginning and all(name not in body for name in PORTS)
    declarations = []
    for name, (direction, size) in PORTS.items():
        size = width if size == 256 else size
        vector = b" [%d:0]" % (size - 1) if size > 1 else b""
        declarations.append(b"   %s%s %s;\n" % (direction, vector, name))
    return header.rstrip() + b",\n   " + b", ".join(PORTS) + b");\n" + b"".join(declarations) + remaining


def connect(body, child, bank):
    match, = (match for match in CHILD.finditer(body) if match[2].decode() == child)
    end = body.index(b");", match.end())
    connections = []
    for name in PORTS:
        signal = name
        if bank is not None and name in {b"residual_d", b"residual_q"}:
            signal += b"[%d:%d]" % (bank * 64 + 63, bank * 64)
        connections.append(b"\n      .%s(%s)" % (name, signal))
    return body[:end].rstrip() + b"," + b",".join(connections) + body[end:]


def route_bank(body):
    declaration, = (match for match in CHILD.finditer(body)
                    if match[1].decode() == MACRO and match[2] == rb"\inputs[1]")
    begin = declaration.end() - 1
    end = body.index(b");", begin)
    original = body[begin:end]
    pins = dict(PIN.findall(original))
    assert pins.keys() == {b"Q", b"CLK", b"CEB", b"WEB", b"A", b"D"}, pins.keys()
    signals = {b"CEB": b"tapped_ce_n", b"WEB": b"tapped_we_n", b"A": b"tapped_addr", b"D": b"tapped_data"}
    changed = PIN.sub(lambda match: b"." + match[1] + b"(" + signals[match[1]] + b")"
                      if match[1] in signals else match[0], original)
    bridge = b"""
   assign residual_q = %s;
   tri_oracle_residual_bank_pin_mux residual_input_bank_lease (
      .rst_n(rst_n), .lease(residual_lease),
      .native_ce_n(%s), .native_we_n(%s), .native_addr(%s), .native_data(%s),
      .residual_ce_n(residual_ce_n), .residual_we_n(residual_we_n),
      .residual_addr(residual_addr), .residual_data(residual_d),
      .memory_ce_n(tapped_ce_n), .memory_we_n(tapped_we_n),
      .memory_addr(tapped_addr), .memory_data(tapped_data));
""" % tuple(pins[name] for name in (b"Q", b"CEB", b"WEB", b"A", b"D"))
    declarations = b"\n   wire tapped_ce_n, tapped_we_n;\n   wire [8:0] tapped_addr;\n   wire [63:0] tapped_data;\n"
    start = declaration.start()
    return (body[:start] + declarations + body[start:begin] + changed
            + body[end:-len(b"endmodule")] + bridge + b"endmodule")


def run(mux, mux_log, result):
    placement = json.loads((ROOT / "records/tri_oracle_partial_pad_repeater_placement.json").read_text())
    original, = (ROOT / path for path in placement["evidence_sha256"] if path.endswith("/placed/candidate.v"))
    identity = placement["candidate_placement_netlist_sha256"]
    assert digest(original) == identity
    assert "\nRESIDUAL_INPUT_BANK_PIN_MUX_MAPPED\n" in mux_log.read_text()
    graph = hierarchy(original, include_memory=True)
    parents = Counter(master for children in graph.values() for master in children.values())
    connections, widths, leaves = defaultdict(dict), {}, {}
    for bank in range(4):
        master = TOP
        steps = (*COMMON, rf"\cores[{bank}]", "compute")
        for level, child in enumerate(steps):
            widths[master] = 64 if level > len(COMMON) else 256
            selection = bank if level == len(COMMON) else None
            assert connections[master].setdefault(child, selection) == selection
            master = graph[master][child]
            assert parents[master] == 1, (master, parents[master])
        assert graph[master][r"\inputs[1]"] == MACRO and master not in leaves
        leaves[master] = bank
        widths[master] = 64

    touched = []
    block_size = 8 * 1024**2
    with original.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as source, result.open("xb") as target:
        cursor = 0
        for definition in MODULE.finditer(source):
            master = definition[1].decode()
            if master not in widths:
                continue
            end = ENDMODULE.search(source, definition.end()).end()
            body = extend(source[definition.start():end], widths[master])
            for child, bank in connections[master].items():
                body = connect(body, child, bank)
            if master in leaves:
                body = route_bank(body)
            for start in range(cursor, definition.start(), block_size):
                target.write(source[start:min(start + block_size, definition.start())])
            target.write(body)
            cursor = end
            touched.append(master)
        for start in range(cursor, len(source), block_size):
            target.write(source[start:start + block_size])
        target.write(b"\n" + mux.read_bytes())
    assert set(touched) == widths.keys() and len(leaves) == 4
    assert digest(original) == identity
    print(json.dumps(dict(parent_sha256=identity, netlist_sha256=digest(result), mux_sha256=digest(mux),
                          altered_definitions=touched, bank_owners=leaves), indent=2, sort_keys=True))


if __name__ == "__main__":
    assert Path("/.dockerenv").is_file() and __debug__
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mux", type=Path, required=True)
    parser.add_argument("--mux-log", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assert args.output.resolve().is_relative_to(ROOT / ".cache")
    run(args.mux, args.mux_log, args.output)
