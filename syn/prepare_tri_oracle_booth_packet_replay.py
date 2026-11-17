"""Bind the trained two-row attention fixture to the corrected chip export."""

from hashlib import file_digest
import json
import mmap
from pathlib import Path
import re

from link_tri_oracle_indexed_whole_chip import signature, spans

ROOT = Path(__file__).resolve().parents[1]
WORK = Path(
    ".cache/physical/whole_chip_xcelium_speed/booth_joined_chip/native_glue/retry/packet_replay"
)
STAGE = WORK.parent
BASE = STAGE.parents[2]
LATEST = Path("records/tri_oracle_corrected_booth_placement_roundtrip.json")
SOURCE_TOP = "tri_oracle_chip_host_status_io"
TOP = "tri_oracle_chip_credited_request"
BENCH_TOP = "tri_oracle_chip_packet_io_tb"
PEER = Path("verilog/tri_oracle_booth_packet_peer.svh")


def digest(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def load(path):
    return json.loads(path.read_text())


def replace_once(text, before, after):
    assert text.count(before) == 1, before
    return text.replace(before, after)


def include(path):
    return f'`include "{path.resolve()}"\n'


def prepare():
    evidence = {}

    def pin(path, expected=None):
        actual = digest(path)
        assert expected is None or actual == expected, path
        evidence[str(path)] = actual
        return path

    placement = load(pin(LATEST))
    assert (
        placement["state"]
        == "corrected_booth_placement_reload_and_connectivity_verified"
    )
    cold = STAGE / "cold/cold.v"
    pin(cold, placement["evidence_sha256"][str(cold)])

    earlier = BASE / "host_status_joined/prepared.json"
    previous = load(pin(earlier))
    template = BASE / "host_status_joined/attention_tb.sv"
    pin(template, previous["evidence_sha256"][str(template)])
    original = BASE / "prepared.json"
    original_record = load(pin(original))
    old_fixture = Path(original_record["fixture"]).relative_to(ROOT)
    new_fixture = WORK / "fixture"
    for name in ("map.hex", "signs.hex", "expected.hex", "rows.txt"):
        path = old_fixture / name
        pin(path, original_record["evidence_sha256"][str(path)])
        if name != "rows.txt":
            linked = new_fixture / name
            if linked.is_symlink():
                assert linked.resolve(strict=True) == path.resolve()
            else:
                linked.symlink_to(path.resolve())
    rows = (old_fixture / "rows.txt").read_text().splitlines()
    assert len(rows) == 1 + 32 * 5
    assert len(rows[0].split()) == 1 and len(rows[1].split()) == 6
    assert [int(line.split()[2]) for line in rows[2:4]] == [1, 205]
    (new_fixture / "rows.txt").write_text(
        " ".join(rows[:2]) + "\n" + "\n".join(rows[2:4]) + "\n"
    )

    planned = pin(PEER).read_text()
    with (
        cold.open("rb") as stream,
        mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data,
    ):
        modules = spans(data)
        beginning, end = modules[TOP]
        active = signature(data[beginning:end])
        assert (
            sum(int(width[1:-3]) + 1 if width else 1 for _, width in active.values())
            == 484
        )
        actual = set(
            re.findall(r"\.(\w+)(?:\([^)]*\))?(?=,|\n)", planned.split(");", 1)[0])
        )
        assert actual == set(active), (set(active) - actual, actual - active)
        assert SOURCE_TOP in modules

    request_path = pin(Path("verilog/tri_oracle_memory_request_link.sv"))
    standalone = request_path.read_text().split(
        "module tri_oracle_memory_forward_rx (", 1
    )[1]
    requests = WORK / "request_peer.sv"
    requests.write_text(
        "`timescale 1ns/1ps\nmodule tb_memory_forward_rx (" + standalone
    )
    serializer = pin(Path("verilog/tri_oracle_serial_flit_bridge.sv"))
    fifo = pin(Path("verilog/tri_oracle_credit_bypass_fifo.sv"))
    bridges = WORK / "serial_peers.sv"
    content = serializer.read_text() + "\n" + fifo.read_text()
    for name in (
        "tri_oracle_flit_to_pads",
        "tri_oracle_flit_from_pads",
        "tri_oracle_credit_bypass_fifo",
    ):
        content = content.replace(name, "tb_" + name)
        planned = planned.replace(name, "tb_" + name)
    bridges.write_text(content)

    bench = template.read_text()
    substitution = re.compile(
        r"(?ms)^  tri_oracle_chip_host_status_io dut \(.*?^  \);\n"
    )
    bench, count = substitution.subn(lambda _: planned, bench)
    assert count == 1
    for line, replacement in (
        ("  tri_oracle_memory_forward_rx peer (", "  tb_memory_forward_rx peer ("),
        ("dut.control_valid", "dut.chip.chip.control_valid"),
        ("dut.control_ready", "dut.chip.chip.control_ready"),
        ("dut.chip_status", "dut.chip.chip.chip_status"),
        ("dut.residual_lease", "dut.chip.chip.residual_lease"),
        ("dut.normalization", "dut.chip.chip.normalization"),
        ("#200000;", "#1000000;"),
        (
            '$display("COLD_PACKET_ATTENTION_PASS',
            "if (memory_request_bytes <= 0 || response_chunks[0] <= 0 || response_chunks[1] <= 0)\n"
            '      $fatal(1, "COLD_PACKET_PHYSICAL_LINK_INVENTORY");\n'
            '    $display("COLD_PACKET_PHYSICAL_LINK_PASS outgoing_bytes=%0d incoming_chunks=%0d,%0d",\n'
            "             memory_request_bytes, response_chunks[0], response_chunks[1]);\n"
            '    $display("COLD_PACKET_ATTENTION_PASS',
        ),
    ):
        bench = replace_once(bench, line, replacement)
    testbench = WORK / "attention_tb.sv"
    testbench.write_text(bench)

    compiled = BASE / "booth_joined_chip/simulation.sv"
    native = load(pin(Path("records/tri_oracle_linked_booth_chip.json")))
    pin(compiled, native["evidence_sha256"][str(compiled)])
    bundle = WORK / "bundle.sv"
    text = replace_once(
        compiled.read_text(),
        include(BASE / "booth_joined_chip/linked.v"),
        include(cold),
    )
    for path in map(Path, re.findall(r'(?m)^`include "([^"]+)"$', text)):
        pin(path.relative_to(ROOT))
    for path in (bridges, requests, testbench):
        pin(path)
        text += include(path)
    bundle.write_text(text)
    paths = (
        bundle,
        new_fixture / "rows.txt",
        Path(__file__).resolve().relative_to(ROOT),
    )
    for path in paths:
        pin(path)
    (WORK / "prepared.json").write_text(
        json.dumps(
            {
                "state": "trained_packet_attention_fixture_bound_to_corrected_full_chip",
                "testbench_top": BENCH_TOP,
                "die_netlist": str(cold),
                "netlist_sha256": evidence[str(cold)],
                "testbench_fixture": str(new_fixture),
                "scope": "Two trained reference attention rows with externally supplied, already projected keys and values. The exact cold export handles external host and credit ports.",
                "evidence_sha256": evidence,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


if __name__ == "__main__":
    assert __debug__ and not Path("/.dockerenv").exists()
    assert Path.cwd() == ROOT
    (WORK / "fixture").mkdir(parents=True, exist_ok=True)
    prepare()
