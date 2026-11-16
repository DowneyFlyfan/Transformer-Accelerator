"""Prepare shared response metadata regressions and the chip boundary."""
import argparse
from pathlib import Path

from link_tri_oracle_narrow_host import declarations, width
from link_tri_oracle_chip_packet_io import instance
from measure_tri_oracle_serial_memory_requests import digest, read, replace
from verify_tri_oracle_host_control import outer_ports


ROOT = Path(__file__).resolve().parents[1]
BASE = Path(".cache/physical/whole_chip_xcelium_speed")
SPLIT = BASE / "split_credit_ingress"
CREDIT = BASE / "credit_ingress"
CONTROLS = Path(".cache/physical/serialized_memory_controls/binding/serial_control_wrapper.v")
PRIOR = Path("records/tri_oracle_split_credit_ingress.json")
SERIAL = Path("records/tri_oracle_serial_control_pads.json")
TOP = "tri_oracle_credit_metadata_ingress"
OLD = "tri_oracle_credit_memory_ingress"
CREDIT_TEST = Path("verilog/tri_oracle_credit_memory_ingress_tb.sv")
WRAPPER = Path("verilog/tri_oracle_credit_metadata_ingress.sv")
PREFIX = "memory_mem_rsp_"
SIDEBAND = ("valid", "last", "error", "compact", "words")


def driver(words, compact, last, error, valid):
    def beat(lane):
        return "{" + ", ".join(f"{name}[{lane}]" for name in (valid, words, compact, last, error)) + "}"
    return f"  wire [6:0] shared_metadata;\n  assign #2 shared_metadata = clk ? {beat(1)} : {beat(0)};\n"


def tests(out):
    base = CREDIT_TEST.read_text()
    credit_driver = driver("words_by_lane", "pad_compact", "pad_last", "pad_error", "pad_valid")
    credit = replace(base, f"  {OLD} dut (.*);", "  wire [1:0][2:0] words_by_lane = pad_words;\n"
                     + credit_driver + f"  {TOP} dut (.pad_metadata(shared_metadata), .*);")
    mixed_driver = "  wire [1:0] offered_valid = pad_valid & pad_ready;\n" + driver(
        "pad_words", "pad_compact", "pad_last", "pad_error", "offered_valid")
    mixed = replace((CREDIT / "mixed_tb.sv").read_text(), f"  {OLD} ingress (\n"
                    "    .clk,.rst_n,.pad_valid(pad_valid & pad_ready),.pad_credit,.protocol_error,\n"
                    "    .pad_last,.pad_error,.pad_compact,.pad_words,.pad_data,",
                    mixed_driver + f"  {TOP} ingress (\n"
                    "    .clk,.rst_n,.pad_metadata(shared_metadata),.pad_credit,.protocol_error,.pad_data,")
    trained_driver = driver("stage_words", "stage_compact", "stage_last", "ddr_peer_staged_error", "credit_valid")
    trained = replace((CREDIT / "trained_tb.sv").read_text(), f"  {OLD} credit_ingress (\n"
                      "    .clk,.rst_n,.pad_data(shared_data),.pad_valid(credit_valid),.pad_credit,.protocol_error,\n"
                      "    .pad_words(stage_words),.pad_compact(stage_compact),.pad_last(stage_last),.pad_error(ddr_peer_staged_error),",
                      trained_driver + f"  {TOP} credit_ingress (\n"
                      "    .clk,.rst_n,.pad_data(shared_data),.pad_metadata(shared_metadata),.pad_credit,.protocol_error,")
    for name, text in (("credit_tb.sv", credit), ("mixed_tb.sv", mixed), ("trained_tb.sv", trained)):
        (out / name).write_text(text)


def bind(out):
    prior_credited = SPLIT / "chip_binding/credit_wrapper.v"
    pin = read(PRIOR)["evidence_sha256"]
    assert digest(prior_credited) == pin[str(prior_credited)]
    assert digest(CONTROLS) == read(SERIAL)["evidence_sha256"][str(CONTROLS)]
    names = {PREFIX + name for name in SIDEBAND}
    meta = PREFIX + "metadata"

    def bridged(source):
        before = outer_ports(source)
        assert {before[pin] for pin in names} == {("INPUT", 2), ("INPUT", 6)}
        after = {name: port for name, port in before.items() if name not in names}
        after[meta] = ("INPUT", 7)
        assert width(before) - width(after) == 7 and after[PREFIX + "data"] == ("INPUT", 448)
        head, body = source.split("\n);\n", 1)
        head = head.split("(\n", 1)[0] + "(\n" + ",\n".join(declarations(after))
        return head + "\n);\n" + body, after

    parent, _ = bridged(prior_credited.read_text())
    parent = replace(parent, "module tri_oracle_chip_credited_memory (", "module tri_oracle_chip_credited_metadata (")
    parent = replace(parent, f"  {OLD} credit_receiver (", f"  {TOP} credit_receiver (")
    for name in SIDEBAND:
        parent = replace(parent, f"    .pad_{name}({PREFIX}{name}),\n", "")
    parent = replace(parent, f"    .pad_data({PREFIX}data),\n",
                     f"    .pad_data({PREFIX}data),\n    .pad_metadata({meta}),\n")

    top, after = bridged(CONTROLS.read_text())
    top = replace(top, "module tri_oracle_chip_serial_controls (", "module tri_oracle_chip_shared_metadata (")
    top = replace(top, "  tri_oracle_chip_credited_memory chip (", "  tri_oracle_chip_credited_metadata chip (")
    for name in SIDEBAND:
        top = replace(top, f"    .{PREFIX}{name}({PREFIX}{name}),\n", "")
    top = replace(top, f"    .{PREFIX}data({PREFIX}data),\n", f"    .{PREFIX}data({PREFIX}data),\n    .{meta}({meta}),\n")
    assert width(after) == 483 and outer_ports(top) == after
    (out / "credit_wrapper.v").write_text(parent)
    (out / "top_wrapper.v").write_text(top)


def bundles(out):
    for name in ("trained_rtl", "trained_mapped"):
        source = SPLIT / f"{name}.sv"
        text = source.read_text()
        assert digest(source) == read(PRIOR)["evidence_sha256"][str(source)]
        text = replace(text, str(ROOT / CREDIT / "trained_tb.sv"), str(out / "trained_tb.sv"))
        if name == "trained_rtl":
            text += f'`include "{ROOT / WRAPPER}"\n'
        else:
            text = replace(text, str(ROOT / SPLIT / "genus/netlist.v"), str(out / "genus/netlist.v"))
        (out / f"{name}.sv").write_text(text)
        run = out / name
        run.mkdir(exist_ok=True)
        for fixture in ("down_index.bin", "down_payload.bin", "projected.hex"):
            target = (SPLIT / name / fixture).resolve(strict=True)
            path = run / fixture
            if path.is_symlink():
                assert path.resolve(strict=True) == target
            else:
                path.symlink_to(target)


def chip_bundle(out):
    linked = SPLIT / "linked.json"
    assert digest(linked) == read(PRIOR)["evidence_sha256"][str(linked)]
    proof = read(linked)["evidence_sha256"]
    prior_bundle = ROOT / SPLIT / "chip_binding/credit_bundle.sv"
    old_receiver = ROOT / SPLIT / "genus/netlist.v"
    old_wrapper = ROOT / SPLIT / "chip_binding/credit_wrapper.v"
    for source in (prior_bundle, old_receiver, old_wrapper):
        assert digest(source) == proof[str(source)], source
    narrow = Path(".cache/physical/serialized_memory_controls/genus/netlist.v")
    assert digest(narrow) == read(SERIAL)["evidence_sha256"][str(narrow)]
    text = replace(prior_bundle.read_text(), str(old_receiver), str(out / "genus/netlist.v"))
    text = replace(text, str(old_wrapper), str(out / "credit_wrapper.v"))
    for source in (ROOT / narrow, out / "top_wrapper.v"):
        text += f'`include "{source}"\n'
    (out / "chip_bundle.sv").write_text(text)


def prepare(out):
    assert Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    assert out.is_relative_to(ROOT / ".cache")
    out.mkdir(parents=True, exist_ok=True)
    pin = read(PRIOR)["evidence_sha256"]
    for path in (CREDIT_TEST, CREDIT / "mixed_tb.sv"):
        assert digest(path) == pin[str(path)], path
    old_trained = CREDIT / "trained_tb.sv"
    source_pin = read(Path("records/tri_oracle_credit_bypass_ingress.json"))["evidence_sha256"]
    assert digest(old_trained) == source_pin[str(old_trained)]
    tests(out)
    bind(out)
    bundles(out)
    chip_bundle(out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=lambda text: Path(text).resolve())
    prepare(parser.parse_args().out)
