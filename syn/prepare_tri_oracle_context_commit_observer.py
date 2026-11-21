"""Export accepted metadata commits from the existing mapped memory owner.

The added two-input AND cell observes commit_valid and commit_ready. It does
not replace the owner's readiness logic or change an existing connection.
"""

import argparse
import hashlib
import json
from pathlib import Path


OWNER = "tri_oracle_packed_outlier_replay_CORE_STRIP_PREDICTOR1"
SOURCE_SHA256 = "c44d6a96d79c9c341e16f327718f405a236dba89cb04089eb6b2f65ee0ec8cd9"
OUTPUT_SHA256 = "6382f2015a3cdf585a93e79a2691034ce26b786e13bed6418da1b99dc6faae38"
OLD_PORT_END = "context_metadata_idle);"
NEW_PORT_END = "context_metadata_idle, context_metadata_commit);\n  output context_metadata_commit;\n"
GATE = (
    "AN2D1BWP12T40P140 context_commit_gate "
    "(.A1(commit_valid),.A2(commit_ready),.Z(context_metadata_commit));\n"
)


def add_commit_observer(source: bytes) -> bytes:
    """Require the reviewed owner and preserve all original bytes reversibly."""
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError("Input is not the reviewed mapped metadata owner")
    text = source.decode()
    if text.count(f"module {OWNER} (") != 1 or text.count("endmodule") != 1:
        raise ValueError("Expected exactly one metadata-owner module")
    if text.count(OLD_PORT_END) != 1 or "context_metadata_commit" in text:
        raise ValueError("Unexpected metadata-owner port list")
    changed = text.replace(OLD_PORT_END, NEW_PORT_END).replace("endmodule", GATE + "endmodule")
    recovered = changed.replace(GATE, "").replace(NEW_PORT_END, OLD_PORT_END)
    result = changed.encode()
    if recovered.encode() != source or hashlib.sha256(result).hexdigest() != OUTPUT_SHA256:
        raise ValueError("Commit observation changed more than the reviewed port and cell")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("owner", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = add_commit_observer(args.owner.read_bytes())
    with args.output.open("xb") as stream:
        stream.write(result)
    print(json.dumps({
        "source_sha256": SOURCE_SHA256,
        "output_sha256": OUTPUT_SHA256,
        "added_standard_cells": {"AN2D1BWP12T40P140": 1},
        "original_owner_byte_exactly_recoverable": True,
        "whole_chip_verified": False,
    }))


if __name__ == "__main__":
    main()
