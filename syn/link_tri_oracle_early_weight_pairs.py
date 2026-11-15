"""Link the two independently mapped decoder cuts in the early-write parser."""

import argparse
from pathlib import Path
import re

from audit_tri_oracle_packed_weight_path import pins


DECODER = "weight_decode_flush"
MODULE = re.compile(rb"(?ms)^module weight_decode_flush\s*\((.*?)\)\s*;(.*?)^endmodule\b")
PORT = re.compile(rb"(?m)^\s*(?:input|output)\b[^;]*;")
WIRE = re.compile(rb"(?m)^\s*wire\b[^;]*;")


def link(parser, decoder):
    abstract, = MODULE.finditer(parser)
    implementation, = MODULE.finditer(decoder)
    if abstract[1].split() != implementation[1].split() or [
        line.split() for line in PORT.findall(abstract[2])
    ] != [line.split() for line in PORT.findall(implementation[2])]:
        raise ValueError("Mapped decoder ports differ from the parser abstract")
    if WIRE.sub(b"", PORT.sub(b"", abstract[2])).strip():
        raise ValueError("Parser decoder abstract already has an implementation")
    if not WIRE.sub(b"", PORT.sub(b"", implementation[2])).strip():
        raise ValueError("Mapped decoder implementation is empty")

    port_names = {token.strip().decode() for token in abstract[1].split(b",")}
    connections = []
    for lane in range(2):
        connections.append(pins(parser, DECODER, rf"\word_decoder[{lane}].decoder"))
        if connections[-1].keys() != port_names:
            raise ValueError(f"Incomplete named connections at decoder cut {lane}")
    if connections[0]["weights"] == connections[1]["weights"]:
        raise ValueError("Both decoder cuts drive the same payload")

    return parser[:abstract.start()] + implementation[0] + parser[abstract.end():]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("parser_netlist", type=Path)
    parser.add_argument("decoder_netlist", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_bytes(link(args.parser_netlist.read_bytes(), args.decoder_netlist.read_bytes()))


if __name__ == "__main__":
    main()
