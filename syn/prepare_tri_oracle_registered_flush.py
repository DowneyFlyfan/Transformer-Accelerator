"""Generate the registered backend flush for a Tri-Oracle projection sequencer."""

import argparse
from pathlib import Path


def register_flush(source):
    replacements = (
        ("  state_t state;", "  state_t state;\n  logic flush_active;", 1),
        ("backend_rst_n=rst_n && state!=FLUSH;", "backend_rst_n=rst_n && !flush_active;", 1),
        ("state<=IDLE;tag<=0;", "state<=IDLE;flush_active<=0;tag<=0;", 1),
        ("flush_second<=0;state<=FLUSH;", "flush_second<=0;flush_active<=1;state<=FLUSH;", 3),
        (
            "      FLUSH:if(flush_second)state<=DONE;else flush_second<=1;",
            "      FLUSH:if(flush_second)begin\n"
            "        flush_active<=0;\n"
            "        state<=DONE;\n"
            "      end else flush_second<=1;",
            1,
        ),
    )
    for before, after, expected in replacements:
        if source.count(before) != expected:
            raise ValueError(f"Unexpected projection sequencer source near {before!r}")
        source = source.replace(before, after)
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Original or cluster-aware projection sequencer")
    parser.add_argument("output", type=Path, help="Path for the generated SystemVerilog source")
    args = parser.parse_args()
    generated = register_flush(args.source.read_text())
    with args.output.open("x") as stream:
        stream.write(generated)


if __name__ == "__main__":
    main()
