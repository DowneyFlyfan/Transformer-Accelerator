"""Restore the four constant inputs lost during projection sequencer replacement."""
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
INSTANCE = re.compile(rb"(?m)^\s*" + SEQUENCER + rb"\s+sequencer\s*\(")
MODULE = re.compile(rb"(?m)^module\s+(\w+)\s*\(")


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("netlist", type=Path, help="Mapped chip with replaced projection sequencer")
    parser.add_argument("parent_rtl", type=Path, help="SystemVerilog source for the mapped tensor parent")
    parser.add_argument("output", type=Path, help="New repaired Verilog netlist")
    args = parser.parse_args()
    with args.netlist.open("rb") as source, mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_READ) as mapped:
        start, end, instance = restore(mapped, args.parent_rtl.read_text())
        with args.output.open("xb") as output, memoryview(mapped) as view:
            output.write(view[:start])
            output.write(instance)
            output.write(view[end:])


if __name__ == "__main__":
    main()
