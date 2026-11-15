"""Link the wider indexed weight controller and verified native write path."""

import argparse
import json
import mmap
from pathlib import Path
import re

from audit_tri_oracle_placed_chip_boundary import digest
from link_tri_oracle_indexed_whole_chip import (
    LOADER, RAW_CUT, STAGE, TOP, TRANSPORT, module_at, pins, remove_abstract, signature,
    spans, stream_copy, update_instance,
)


WIDE_TRANSPORT = "tri_oracle_dual_group_weight_transport"
WIDE_TILE = "tri_oracle_dual_group_tile"
DECODER = "weight_decode_flush"
NARROW = b"[511:0]"
WIDE = b"[1023:0]"


def widen_association(body, name):
    declaration = b"   wire " + NARROW + b" " + name + b";"
    assert body.count(declaration) == 1, name
    return body.replace(declaration, declaration.replace(NARROW, WIDE), 1)


def change_tensor(body, before, after, fabric):
    old_ports = signature(before)
    for lane in range(2):
        old_ports[f"load_payload[{lane}]"] = (b"output", WIDE)
    assert old_ports == signature(after)
    ingress = pins(body, TRANSPORT, "packed_loader")
    stage = pins(body, STAGE, "packed_write_stage")
    egress = pins(body, fabric, "fabric")
    for lane in range(2):
        inbound = stage[f"load_payload[{lane}]"]
        outbound = stage[f"write_payload[{lane}]"]
        assert ingress[f"load_payload[{lane}]"] == inbound
        assert egress[f"wide_load_payload[{lane}]"] == outbound
        body = widen_association(widen_association(body, inbound), outbound)
    return update_instance(body, TRANSPORT, "packed_loader", replacement=WIDE_TRANSPORT)


def isolate_controller(control, tile, source, old_index):
    control, parser_cut = remove_abstract(control, spans(control), WIDE_TILE)
    control, raw_cut = remove_abstract(control, spans(control), RAW_CUT)
    assert signature(raw_cut) == signature(module_at(source, old_index, LOADER))
    control = update_instance(control, RAW_CUT, "raw_loader", replacement=LOADER)

    tiles = spans(tile)
    assert set(tiles) == {DECODER, WIDE_TILE}
    assert module_at(tile, tiles, DECODER) == module_at(source, old_index, DECODER)
    parser = module_at(tile, tiles, WIDE_TILE)
    assert signature(parser) == signature(parser_cut)

    collisions = set(spans(control)) & old_index.keys()
    assert WIDE_TRANSPORT not in collisions and WIDE_TILE not in old_index
    if collisions:
        names = b"|".join(re.escape(name.encode()) for name in sorted(collisions))
        line = re.compile(rb"(?m)^( *(?:module )?)(" + names + rb")(?=[ \t]*\(|[ \t]+[^ \t\r\n(]+[ \t]*\()")
        control = line.sub(rb"\1dual_group_\2", control)
    additions = spans(control)
    assert not additions.keys() & old_index.keys()
    assert WIDE_TRANSPORT in additions
    return control, additions, parser


def link(candidate, manifest, write_path, control, tile, output):
    assert digest(candidate) == manifest["candidate_sha256"]
    with candidate.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as source:
        index = spans(source)
        prepared = spans(write_path)
        fabric, = (name for name in prepared if name.startswith("tri_oracle_compute_fabric_"))
        clusters = {name for name in prepared if name.startswith("tri_oracle_partitioned_cluster_")}
        assert len(clusters) == 5 and prepared.keys() == clusters | {STAGE, fabric}
        assert prepared.keys() <= index.keys()
        owner, = (name for name in manifest["edited_modules"] if name.startswith("tri_oracle_batched_tensor390_"))
        control, additions, parser = isolate_controller(control, tile, source, index)
        tensor = change_tensor(module_at(source, index, owner), module_at(source, index, TRANSPORT),
                               module_at(control, additions, WIDE_TRANSPORT), fabric)
        edits = {name: module_at(write_path, prepared, name) for name in prepared}
        edits[owner] = tensor
        with output.open("xb") as stream:
            cursor = 0
            for name in sorted(edits, key=lambda name: index[name][0]):
                start, end = index[name]
                stream_copy(stream, source, cursor, start)
                stream.write(edits[name])
                cursor = end
            stream_copy(stream, source, cursor, len(source))
            stream.write(b"\n" + control + b"\n" + parser + b"\n")
        with output.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as updated:
            result = spans(updated)
            assert result.keys() == index.keys() | additions.keys() | {WIDE_TILE}
            for name in edits:
                assert module_at(updated, result, name) == edits[name]
            assert module_at(updated, result, TOP) == module_at(source, index, TOP)
    print(f"DUAL_GROUP_WHOLE_CHIP_LINKED {digest(output)} modules_changed={len(edits)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("candidate", "manifest", "write_path", "control", "tile", "output"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    link(args.candidate, json.loads(args.manifest.read_text()), args.write_path.read_bytes(),
         args.control.read_bytes(), args.tile.read_bytes(), args.output)


if __name__ == "__main__":
    main()
