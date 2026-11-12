"""Prepare a tensor source with the scalar write address independent of response-valid."""

import argparse
from pathlib import Path


def predict_address(source):
    select = "    if(state==LOAD_MASK)begin\n"
    address = "      load_addr=10'(chunk_word)+10'(beat_index);\n"
    response = "    end else if(valid_response && !activation_mode)begin\n"
    if source.count(select) != 1 or source.count(address) != 1 or source.count(response) != 1:
        raise ValueError("Expected one scalar load address in the valid-response branch")
    body = source.split(response, 1)[1].split("\n    end\n", 1)[0]
    if address not in body:
        raise ValueError("The scalar load address is outside the expected response branch")
    return source.replace(address, "").replace(
        select, "    // The write enable qualifies this address at every memory consumer.\n"
                "    if(state==RESPONSE && !activation_mode)\n"
                "      load_addr=10'(chunk_word)+10'(beat_index);\n" + select,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    candidate = predict_address(args.source.read_text())
    with args.output.open("x") as stream:
        stream.write(candidate)
