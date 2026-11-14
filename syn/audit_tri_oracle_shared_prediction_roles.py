"""Check which prediction operations remain shared on the mapped Tri-Oracle chip."""

import argparse
from hashlib import file_digest
import json
import mmap
from pathlib import Path
import re

from audit_tri_oracle_mapped_redundancy import ENDMODULE, MODULE, SHARED_HEAD, SHARED_STRIP, audit, hierarchy


CONNECTION = re.compile(rb"\.(\w+)\s*\(([^()]*)\)")
SRAM = re.compile(rb"(?m)^\s*TS5N28HPCPSVTA(512X64M4F|32X128M2FW)\s+(\\\S+|\w+)\s*\(")
SIGN_BANK = "tri_oracle_shared_sign_key_bank"


def named_pins(body, instance):
    pattern = rb"(?m)^[ \t]+\w+\s+" + re.escape(instance) + rb"\s*\(([^;]*)\);"
    matches = re.findall(pattern, body)
    if len(matches) != 1:
        raise ValueError(f"Expected one mapped instance named {instance!r}")
    return dict(CONNECTION.findall(matches[0]))


def scan_head(body, children):
    if set(children) != {"tile"} or not children["tile"].startswith("tri_oracle_attention_tile_batch413_"):
        raise ValueError("Unexpected child in the shared head scheduler")
    pins = named_pins(body, b"tile")
    if pins.get(b"score_valid") != b"head_request[393]" or pins.get(b"score_ready") != b"head_response[71]":
        raise ValueError("Score tile handshake is disconnected from the core classifier")
    streaming_drivers = [dict(CONNECTION.findall(row)) for row in body.split(b";")
                         if re.search(rb"\.Z\s*\(\s*out_streaming\s*\)", row)]
    if len(streaming_drivers) != 1 or b"head_response[68]" not in streaming_drivers[0].values():
        raise ValueError("Streaming decision is disconnected from the core classifier response")
    return {"score_valid_request_bit": 393, "score_ready_response_bit": 71, "streaming_decision_response_bit": 68}


def scan_feedforward(body, children, sign_bank_body):
    if children != {"shared_sign_key_bank": SIGN_BANK}:
        raise ValueError("Unexpected feed-forward replay hierarchy")
    for output, width, start in ((b"outlier_count", 13, 0), (b"skip_mask", 32, 13),
                                 (b"up_nearzero_mask", 32, 45), (b"gate_nearzero_mask", 32, 77)):
        pattern = (rb"(?m)^\s*assign\s+" + output + rb"\[(\d+)\]\s*=\s*strip_response\[(\d+)\]\s*;")
        actual = [(int(left), int(right)) for left, right in re.findall(pattern, body)]
        if sorted(actual) != [(bit, start + bit) for bit in range(width)]:
            raise ValueError(f"Incomplete or crossed core-response wiring for {output!r}")
    metadata = {(master, instance) for master, instance in SRAM.findall(body)}
    expected_metadata = {(b"512X64M4F", b"metadata_memory_lower_words")}
    expected_metadata.update((b"32X128M2FW", rb"\metadata_memory_upper_words[%d].memory" % index)
                             for index in range(5))
    cache_banks = SRAM.findall(sign_bank_body)
    if metadata != expected_metadata or sorted(cache_banks) != [
            (b"32X128M2FW", rb"\banks[%d].bank" % index) for index in range(4)]:
        raise ValueError("Unexpected shared metadata or sign/key memory inventory")
    return {"response_bits_wired_to_masks_and_count": 109, "metadata_macros": 6,
            "metadata_capacity_bytes": 6656, "shared_sign_key_macros": 4,
            "shared_sign_key_capacity_bytes": 2048}


def measure(netlist):
    graph = hierarchy(netlist)
    observed = audit(graph)["additional_shared_prediction_instances"]
    head, = (master for master in observed.values() if master.startswith(SHARED_HEAD))
    feedforward, = (master for master in observed.values() if master.startswith(SHARED_STRIP))
    if len(observed) != 2:
        raise ValueError("Unexpected number of shared prediction-related blocks")
    roles = {}
    with netlist.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as source:
        for definition in MODULE.finditer(source):
            master = definition[1].decode()
            if master in {head, feedforward, SIGN_BANK}:
                end = ENDMODULE.search(source, definition.end()).start()
                roles[master] = source[definition.end():end]
    return {"attention_tile_scheduler": scan_head(roles[head], graph[head]),
            "feedforward_metadata_and_sign_replay": scan_feedforward(roles[feedforward], graph[feedforward],
                                                                    roles[SIGN_BANK])}


def sha(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mapped_netlist", type=Path)
    parser.add_argument("placed_netlist", type=Path)
    parser.add_argument("--mapped-sha256", required=True)
    parser.add_argument("--placed-sha256", required=True)
    args = parser.parse_args()
    readings = []
    for path, checksum in ((args.mapped_netlist, args.mapped_sha256), (args.placed_netlist, args.placed_sha256)):
        if sha(path) != checksum:
            raise ValueError(f"Unexpected netlist digest: {path}")
        readings.append(measure(path))
        if sha(path) != checksum:
            raise ValueError(f"Netlist changed during verification: {path}")
    if readings[0] != readings[1]:
        raise ValueError("Mapped and placed prediction roles differ")
    print(json.dumps(dict(mapped_sha256=args.mapped_sha256, placed_sha256=args.placed_sha256,
                          **readings[0]), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
