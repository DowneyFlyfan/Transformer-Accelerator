"""Attach the mapped indexed dispatcher and weight transport to a cold export."""

import argparse
from collections import Counter
import json
import mmap
from pathlib import Path
import re

from audit_tri_oracle_mapped_redundancy import ENDMODULE, MODULE, TOP, hierarchy
from audit_tri_oracle_packed_weight_path import LOADER, STAGE, PIN, loader_paths, pins
from audit_tri_oracle_placed_chip_boundary import digest


OLD_DISPATCH = "tri_oracle_chip_dispatch"
DISPATCH = "tri_oracle_indexed_chip_dispatch"
TRANSPORT = "tri_oracle_controlled_weight_transport"
RAW_CUT = "tri_oracle_parallel_weight_loader"
TILE_CUT = "tri_oracle_early_pair_tile"
MODE = "indexed_weight_format"
PAYLOAD = "selected_weight_payload_"
DECLARATION = re.compile(rb"(?m)^\s*(input|output)\s+(\[\d+:\d+\]\s*)?([^;]+);")
PASSIVE = re.compile(rb"(?m)^\s*(?:input|output|wire)\b[^;]*;")


def spans(source):
    found = {}
    for module in MODULE.finditer(source):
        name = module[1].decode()
        if name in found:
            raise ValueError(f"Duplicate definition of {name}")
        end = ENDMODULE.search(source, module.end())
        if end is None:
            raise ValueError(f"Unterminated definition of {name}")
        found[name] = (module.start(), end.end())
    return found


def signature(module):
    header, sep, body = module.partition(b");")
    if not sep:
        raise ValueError("Expected non-ANSI module declaration")
    opening = MODULE.search(header)
    if opening is None:
        raise ValueError("Missing module declaration")
    ports = {pin.strip().lstrip(b"\\").decode() for pin in header[opening.end():].split(b",")}
    result = {}
    for direction, width, names in DECLARATION.findall(body):
        for name in names.split(b","):
            port = name.strip().lstrip(b"\\").decode()
            if port in result:
                raise ValueError(f"Repeated declaration of {port}")
            result[port] = (direction, width.strip())
    if ports != result.keys():
        raise ValueError(f"Module header differs from port declarations: {ports ^ result.keys()}")
    return result


def update_instance(source, master, name, *, replacement=None, add=None, update=None):
    start = re.escape(f"{master} {name}".encode())
    match, = re.finditer(rb"(?m)^[ \t]*(" + start + rb")\s*\(([^;]*)\);", source)
    before = pins(source, master, name)
    add = {} if add is None else add
    update = {} if update is None else update
    if before.keys() & add.keys() or update.keys() - before.keys():
        raise ValueError(f"Unexpected named connection at {name}")
    def association(pin, value):
        name = f"\\{pin} " if "[" in pin else pin
        return b"." + name.encode() + b"(" + value + b")"
    def replace_pin(item):
        pin = item[1].decode().removeprefix("\\")
        return association(pin, update[pin]) if pin in update else item[0]
    fields = PIN.sub(replace_pin, match[2])
    fields += b"".join(b",\n\t" + association(pin, value) for pin, value in add.items())
    new_master = replacement or master
    changed = source[:match.start(1)] + f"{new_master} {name} (".encode() + fields + b");" + source[match.end():]
    expected = before | update | add
    if pins(changed, new_master, name) != expected:
        raise ValueError(f"An unrelated connection changed at {name}")
    return changed


def declare(source, declarations, port=None):
    header, sep, body = source.partition(b");")
    if not sep or any(name in source for name in (MODE.encode(), PAYLOAD.encode())):
        raise ValueError("Whole-chip source is already wired for indexed weights")
    if port is not None:
        header += b",\n\t" + port.encode()
    return header + sep + b"\n" + declarations + body


def module_at(source, index, name):
    return source[slice(*index[name])]


def replacements(source, index, graph, dispatcher, transport):
    (path, parent), = loader_paths(graph)
    route = []
    master = TOP
    for instance in path.split(".")[1:]:
        child = graph[master][instance]
        route.append((master, instance, child))
        master = child
    if route[-1] != (parent, "packed_loader", LOADER) or graph[TOP]["dispatch"] != OLD_DISPATCH:
        raise ValueError("The existing command path changed")

    counts = Counter()
    pending = [TOP]
    while pending:
        master = pending.pop()
        counts[master] += 1
        pending.extend(graph[master].values())
    if any(counts[m] != 1 for m, _, _ in route):
        raise ValueError("The mode wire would change a shared module definition")

    mode = MODE.encode()
    new = {}
    for master, instance, child in route[:-1]:
        body = module_at(source, index, master)
        if master == TOP:
            body = declare(body, b"   wire " + mode + b";\n")
            old_pins = pins(body, OLD_DISPATCH, "dispatch")
            if signature(dispatcher).keys() != old_pins.keys() | {"layer_feedforward_indexed"}:
                raise ValueError("Indexed dispatcher changed the base interface")
            if signature(dispatcher) != signature(module_at(source, index, OLD_DISPATCH)) | {
                "layer_feedforward_indexed": (b"output", b"")
            }:
                raise ValueError("Indexed dispatcher changed a base port width or direction")
            body = update_instance(body, OLD_DISPATCH, "dispatch", replacement=DISPATCH,
                                   add={"layer_feedforward_indexed": mode})
        else:
            body = declare(body, b"   input " + mode + b";\n", MODE)
        new[master] = update_instance(body, child, instance, add={MODE: mode})

    payload = [f"{PAYLOAD}{lane}".encode() for lane in range(2)]
    tensor = declare(module_at(source, index, parent),
                     b"   input " + mode + b";\n" +
                     b"".join(b"   wire [511:0] " + name + b";\n" for name in payload), MODE)
    transport_ports = signature(transport)
    base_ports = signature(module_at(source, index, LOADER))
    extra_ports = {"cfg_indexed": (b"input", b"")}
    extra_pins = {"cfg_indexed": mode}
    old_stage = pins(tensor, STAGE, "packed_write_stage")
    stage_pins = {}
    for lane, original in enumerate((b"wide_rsp_data", b"aux_rsp_data")):
        stage_pin = f"load_payload[{lane}]"
        if old_stage[stage_pin] != original:
            raise ValueError(f"The raw stage lane {lane} changed")
        extra_ports[f"rsp_data[{lane}]"] = (b"input", b"[511:0]")
        extra_ports[stage_pin] = (b"output", b"[511:0]")
        extra_pins[f"rsp_data[{lane}]"] = original
        extra_pins[stage_pin] = payload[lane]
        stage_pins[stage_pin] = payload[lane]
    if transport_ports != base_ports | extra_ports:
        raise ValueError(f"Transport interface changed: {transport_ports.keys() ^ (base_ports | extra_ports).keys()}")
    tensor = update_instance(tensor, LOADER, "packed_loader", replacement=TRANSPORT, add=extra_pins)
    new[parent] = update_instance(tensor, STAGE, "packed_write_stage", update=stage_pins)
    if signature(new[TOP]) != signature(module_at(source, index, TOP)):
        raise ValueError("The candidate changed the top-level ports")
    return new, path


def remove_abstract(text, index, name):
    abstract = module_at(text, index, name)
    _, _, body = abstract.partition(b");")
    if PASSIVE.sub(b"", body).strip() != b"endmodule":
        raise ValueError(f"The {name} cut is already implemented")
    start, end = index[name]
    return text[:start] + text[end:], abstract


def blocks(source, base_index, control, tile):
    tile_index = spans(tile)
    control, tile_cut = remove_abstract(control, spans(control), TILE_CUT)
    control, raw_cut = remove_abstract(control, spans(control), RAW_CUT)
    if signature(tile_cut) != signature(module_at(tile, tile_index, TILE_CUT)):
        raise ValueError("Mapped early-pair tile has a different cut interface")
    if signature(raw_cut) != signature(module_at(source, base_index, LOADER)):
        raise ValueError("Native raw loader has a different cut interface")
    old = f"{RAW_CUT} raw_loader"
    new = f"{LOADER} raw_loader"
    if control.count(old.encode()) != 1:
        raise ValueError("Expected one preserved raw-loader instance")
    if pins(control, RAW_CUT, "raw_loader").keys() != signature(raw_cut).keys():
        raise ValueError("Incomplete named raw-loader pin bindings")
    return update_instance(control, RAW_CUT, "raw_loader", replacement=LOADER), tile


def stream_copy(output, source, start, end):
    limit = 4 * 1024**2
    for offset in range(start, end, limit):
        output.write(source[offset:min(end, offset+limit)])


def link(base, dispatcher, transport, tile, output, checksum):
    if digest(base) != checksum:
        raise ValueError("Unexpected cold export")
    graph = hierarchy(base)
    dispatch, control, linked_tile = (p.read_bytes() for p in (dispatcher, transport, tile))
    with base.open("rb") as fd, mmap.mmap(fd.fileno(), 0, access=mmap.ACCESS_READ) as source:
        index = spans(source)
        if spans(dispatch).keys() != {DISPATCH}:
            raise ValueError("Unexpected dispatcher module inventory")
        control, tile_data = blocks(source, index, control, linked_tile)
        extra = [spans(text).keys() for text in (dispatch, control, tile_data)]
        extra_names = set().union(*extra)
        if index.keys() & extra_names or len(extra_names) != sum(map(len, extra)):
            raise ValueError("Mapped components contain conflicting module names")
        new, path = replacements(source, index, graph, dispatch,
                                 module_at(control, spans(control), TRANSPORT))
        edits = sorted((index[name], body) for name, body in new.items())
        with output.open("xb") as file:
            start = 0
            for (offset, end), body in edits:
                stream_copy(file, source, start, offset)
                file.write(body)
                start = end
            stream_copy(file, source, start, len(source))
            for text in (dispatch, control, tile_data):
                file.write(b"\n" + text)
    return {"state": "indexed_transport_linked_on_repaired_whole_chip",
            "base_sha256": checksum, "candidate_sha256": digest(output), "loader_path": path,
            "edited_modules": sorted(new), "added_module_count": len(extra_names),
            "input_sha256": {str(p): digest(p) for p in (dispatcher, transport, tile)}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("base", "dispatcher", "transport", "tile", "output"):
        parser.add_argument(field, type=Path)
    parser.add_argument("--sha256", required=True)
    args = parser.parse_args()
    print(json.dumps(link(args.base, args.dispatcher, args.transport, args.tile,
                          args.output, args.sha256), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
