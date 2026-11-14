"""Link a mapped projection sequencer and restore its four constant inputs."""
import argparse
import mmap
from pathlib import Path
import re


PORTS = {
    "in_weight_base": "5'b0",
    "in_mask_base": "5'b0",
    "in_activation_base": "10'b0",
    "in_activation_stride": "11'd32",
}
SEQUENCER = b"tri_oracle_batched_projection356_parallel_chip"
GENUS_SEQUENCER = b"tri_oracle_batched_projection356"
INSTANCE = re.compile(rb"(?m)^\s*" + SEQUENCER + rb"\s+sequencer\s*\(")
MODULE = re.compile(rb"(?m)^module\s+(\w+)\s*\(")
PORT = re.compile(rb"(?m)^\s*(input|output)\s+(?:(\[\d+:\d+\])\s+)?([^;]+);")
MACRO = re.compile(rb"(?m)^\s*TS[56]N28\w+\s+(?:\\\S+|\w+)\s*\(")


def restore(mapped, rtl):
    matches = list(INSTANCE.finditer(mapped))
    if len(matches) != 1:
        raise ValueError("Expected exactly one mapped projection sequencer instance")
    instance, = matches
    parents = [header for header in MODULE.finditer(mapped, 0, instance.start())]
    if not parents or not parents[-1][1].startswith(b"tri_oracle_batched_tensor390_"):
        raise ValueError("Unexpected projection sequencer parent")
    parent = parents[-1]
    end = mapped.find(b"\nendmodule", parent.end())
    close = mapped.find(b");", instance.end())
    if not instance.end() < close < end:
        raise ValueError("Incomplete projection sequencer instance")

    raw = mapped[instance.start():close + 2]
    fixed = raw
    unused = set()
    for port, expected in PORTS.items():
        pattern = r"\." + port + r"\(([^()]*)\)"
        if re.findall(pattern, rtl) != [expected]:
            raise ValueError(f"Unexpected source constant for {port}")
        association = re.compile(rb"(\." + port.encode() + rb"\()\{([^{}]*)\}(\))")
        bindings = list(association.finditer(raw))
        if len(bindings) != 1:
            raise ValueError(f"Expected one floating binding for {port}")
        bits = tuple(bit.strip() for bit in bindings[0][2].split(b","))
        if len(bits) != int(expected.split("'")[0]) or len(set(bits)) != len(bits):
            raise ValueError(f"Incorrect floating input width or repeated bits for {port}")
        for bit in bits:
            if not re.fullmatch(rb"UNCONNECTED_HIER_Z\d+", bit) or bit in unused:
                raise ValueError(f"Unexpected floating bit for {port}")
            occurrences = list(re.compile(rb"\b" + bit + rb"\b").finditer(mapped, parent.start(), end))
            if len(occurrences) != 2:
                raise ValueError(f"Floating bit for {port} is used elsewhere")
            unused.add(bit)
        fixed = association.sub(lambda match: match[1] + expected.encode() + match[3], fixed)
    return instance.start(), close + 2, fixed


def module_end(source, header):
    end = source.find(b"\nendmodule", header.end())
    if end == -1:
        raise ValueError(f"Unterminated module {header[1].decode()}")
    return end + len(b"\nendmodule")


def port_signature(module):
    header = MODULE.match(module)
    if not header:
        raise ValueError("Missing sequencer module header")
    declarations = [(name.strip(), direction, width)
                    for direction, width, names in PORT.findall(module)
                    for name in names.split(b",")]
    ordered = tuple(name.strip() for name in
                    module[header.end():module.index(b");", header.end())].split(b","))
    names = {name for name, _, _ in declarations}
    if len(ordered) != len(declarations) or len(ordered) != len(names) or set(ordered) != names:
        raise ValueError("Inconsistent sequencer port declarations")
    return ordered, frozenset(declarations)


def replace_sequencer(parent, replacement):
    definitions = [header for header in MODULE.finditer(parent) if header[1] == SEQUENCER]
    incoming = list(MODULE.finditer(replacement))
    if len(definitions) != 1 or len(incoming) != 1 or incoming[0][1] != GENUS_SEQUENCER:
        raise ValueError("Expected one original sequencer and one mapped replacement module")
    original, = definitions
    new, = incoming
    end = module_end(parent, original)
    before = parent[original.start():end]
    after = replacement[new.start():module_end(replacement, new)]
    if port_signature(before) != port_signature(after):
        raise ValueError("Replacement sequencer port signature differs")
    if MACRO.search(before) or MACRO.search(after):
        raise ValueError("Projection sequencer unexpectedly contains a memory macro")
    start_name, end_name = new.start(1) - new.start(), new.end(1) - new.start()
    return original.start(), end, after[:start_name] + SEQUENCER + after[end_name:]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("netlist", type=Path, help="Mapped chip netlist")
    parser.add_argument("parent_rtl", type=Path, help="SystemVerilog source for the mapped tensor parent")
    parser.add_argument("output", type=Path, help="New repaired Verilog netlist")
    parser.add_argument("--replace-sequencer", type=Path, metavar="NETLIST",
                        help="Link a standalone mapped sequencer before repairing its inputs")
    args = parser.parse_args()
    with args.netlist.open("rb") as source, mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_READ) as mapped:
        edits = [restore(mapped, args.parent_rtl.read_text())]
        if args.replace_sequencer:
            edits.append(replace_sequencer(mapped, args.replace_sequencer.read_bytes()))
        edits.sort()
        if len(edits) == 2 and edits[0][1] > edits[1][0]:
            raise ValueError("Overlapping sequencer edits")
        with args.output.open("xb") as output, memoryview(mapped) as view:
            offset = 0
            for start, end, replacement in edits:
                output.write(view[offset:start])
                output.write(replacement)
                offset = end
            output.write(view[offset:])


if __name__ == "__main__":
    main()
