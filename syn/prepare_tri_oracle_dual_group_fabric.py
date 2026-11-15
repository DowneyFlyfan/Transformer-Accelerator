"""Extend the native packed writer to carry two adjacent row groups per lane."""

import argparse
import json
import mmap
from pathlib import Path
import re

from audit_tri_oracle_placed_chip_boundary import digest
from link_tri_oracle_indexed_whole_chip import STAGE, module_at, pins, signature, spans


AO22 = re.compile(rb"(?m)^   AO22D0BWP12T40P140 (\w+) \(([^;]*)\);")
FLOP = re.compile(rb"(?m)^   DFQD2BWP12T40P140 (\\write_payload_reg\[([01])\]\[(\d+)\])\s+\(([^;]*)\);")
FIELD = re.compile(rb"\.(\w+)\(([^()]*)\)")
PORT = re.compile(rb"(?m)^( +(?:input|output|wire) )\[511:0\]( +(?:\\)?(?:load_payload|write_payload|wide_load_payload)(?:\[.*\])?\s*;)$")
BUS_BIT = re.compile(rb"((?:\\(?:load|write|wide_load)_payload\[[^ ]+\]|wide_load_payload) *\[)(\d+)\]")
CLUSTER = re.compile(rb"(?m)^ +(?P<master>tri_oracle_partitioned_cluster_\w+) (?P<name>\\clusters\[(?P<cluster>[0-4])\]\.unit)\s+\(")
CLUSTER_DATA = re.compile(rb"load_data\[(\d+)\]")


def widen_ports(body, expected):
    replaced, count = PORT.subn(rb"\g<1>[1023:0]\2", body)
    assert count == expected, count
    return replaced


def widen_payload_bits(text):
    return BUS_BIT.sub(lambda match: match[1] + str(int(match[2]) + 512).encode() + b"]", text)


def append_cells(body, cells):
    assert body.endswith(b"endmodule")
    return body[:-len(b"endmodule")] + b"\n".join(cells) + b"\nendmodule"


def widen_stage(body):
    observed = set()
    extra = []
    for cell in FLOP.finditer(body):
        lane, bit = cell[2], int(cell[3])
        fields = dict(FIELD.findall(cell[4]))
        assert fields == {
            b"CP": b"clk",
            b"D": b"\\load_payload[" + lane + b"] [" + cell[3] + b"]",
            b"Q": b"\\write_payload[" + lane + b"] [" + cell[3] + b"]",
        }
        assert (lane, bit) not in observed
        observed.add((lane, bit))
        name = b"dual_write_payload_reg_" + lane + b"_" + cell[3]
        extra.append(cell[0].replace(cell[1], name, 1).replace(cell[4], widen_payload_bits(cell[4]), 1))
    assert observed == {(lane, bit) for lane in (b"0", b"1") for bit in range(512)}
    return append_cells(widen_ports(body, 4), extra)


def widen_cluster(body):
    ports = signature(body)
    assert ports["wide_load_group"] == (b"input", b"[1:0]")
    assert ports["wide_load_payload"] == (b"input", b"[511:0]")
    assert body.count(b"wide_load_group") == 8
    group_selectors = [set() for _ in range(4)]
    observed_bits = set()
    for cell in AO22.finditer(body):
        fields = dict(FIELD.findall(cell[2]))
        if not fields[b"A1"].startswith(b"wide_load_payload["):
            continue
        bit = int(CLUSTER_DATA.fullmatch(fields[b"Z"])[1])
        assert bit not in observed_bits
        observed_bits.add(bit)
        assert fields[b"A1"] == b"wide_load_payload[%d]" % (bit % 512)
        assert fields[b"B1"] == b"scalar_load_data[%d]" % bit
        group_selectors[bit // 512].add(fields[b"A2"])
    assert observed_bits == set(range(2048))
    selectors = [name for names in group_selectors for name in names]
    assert len(set(selectors)) == len(selectors) == 4
    assert all(len(names) == 1 for names in group_selectors)

    def adjust(cell):
        fields = dict(FIELD.findall(cell[2]))
        if not fields[b"A1"].startswith(b"wide_load_payload["):
            return cell[0]
        group = int(CLUSTER_DATA.fullmatch(fields[b"Z"])[1]) // 512
        if group in (0, 2):
            return cell[0]
        fields = cell[2].replace(b".A2(" + selectors[group] + b")", b".A2(" + selectors[group-1] + b")")
        fields = widen_payload_bits(fields)
        return cell[0].replace(cell[2], fields, 1)

    return widen_ports(AO22.sub(adjust, body), 1)


def widen_fabric(body):
    observed = set()
    extra = []
    for cell in AO22.finditer(body):
        fields = dict(FIELD.findall(cell[2]))
        dst = re.fullmatch(rb"\\wide_load_payload\[clusters\[([0-4])\]\.write_lane1\] \[(\d+)\]", fields[b"Z"])
        if dst is None:
            continue
        cluster, bit = dst[1], int(dst[2])
        assert {fields[b"A1"], fields[b"B1"]} == {
            b"\\wide_load_payload[" + lane + b"] [" + dst[2] + b"]" for lane in (b"0", b"1")
        }
        assert (cluster, bit) not in observed
        observed.add((cluster, bit))
        extra.append(cell[0].replace(cell[1], b"dual_" + cell[1], 1)
                     .replace(cell[2], widen_payload_bits(cell[2]), 1))
    assert observed == {(str(cluster).encode(), bit) for cluster in range(5) for bit in range(512)}
    clusters = [(match["master"].decode(), match["name"].decode()) for match in CLUSTER.finditer(body)]
    assert len({master for master, _ in clusters}) == len(clusters) == 5
    for master, instance in clusters:
        original = pins(body, master, instance)
        group = original["wide_load_group"]
        assert group.startswith(b"\\wide_load_group[clusters[")
        # Masked rows still receive no write. Bit one chooses the active
        # 16-row half, and both eight-row groups in that half get unique data.
        connection = re.compile(rb"\.wide_load_group\(\s*" + re.escape(group) + rb"\s*\)")
        narrowed = b"{" + group + b" [1], 1'b0}"
        body, count = connection.subn(lambda _: b".wide_load_group(" + narrowed + b")", body)
        assert count == 1
        assert pins(body, master, instance) == original | {"wide_load_group": b"".join(narrowed.split())}
    return append_cells(widen_ports(body, 7), extra), [master for master, _ in clusters]


def build(source, link):
    assert digest(source) == link["candidate_sha256"]
    with source.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as netlist:
        modules = spans(netlist)
        fabric, = (name for name in modules if name.startswith("tri_oracle_compute_fabric_"))
        expanded_fabric, clusters = widen_fabric(module_at(netlist, modules, fabric))
        return {
            STAGE: widen_stage(module_at(netlist, modules, STAGE)),
            fabric: expanded_fabric,
            **{name: widen_cluster(module_at(netlist, modules, name)) for name in clusters},
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("link_manifest", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    extracted = build(args.candidate, json.loads(args.link_manifest.read_text()))
    with args.output.open("xb") as handle:
        handle.write(b"\n".join(extracted.values()) + b"\n")
    print(f"DUAL_GROUP_FABRIC_PREPARED modules={len(extracted)}")


if __name__ == "__main__":
    main()
