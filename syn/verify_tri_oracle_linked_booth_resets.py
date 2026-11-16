"""Replay all twenty Booth array modules extracted from the linked chip."""

import argparse
import json
import mmap
from pathlib import Path
import subprocess

from link_tri_oracle_indexed_whole_chip import module_at, signature, spans
from verify_tri_oracle_booth8 import simulation
from verify_tri_oracle_booth_chip_link import OLD_ARRAY, WORK, shadow_resets
from verify_tri_oracle_gated_compute_array import (
    PASS,
    ROOT,
    WORK as ORIGINAL,
    digest,
    read,
)
from verify_tri_oracle_host_status import arguments

DEST = WORK / "array_reset_replay"
LINK_PROOF = WORK / "link_proof.json"
MARKER = "BOOTH_LINKED_RESET_REPLAY arrays=20"


def suite():
    proof = read(LINK_PROOF)
    netlist = WORK / "linked.v"
    assert digest(netlist) == proof["evidence_sha256"][str(netlist)]
    expected = {
        entry["predecessor"]: entry["shadow_reset_nets"]
        for entry in proof["unchanged_array_associations"]
    }
    with (
        netlist.open("rb") as stream,
        mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data,
    ):
        definitions = spans(data)
        helpers = [name for name in definitions if name.startswith("tri_booth_i_")]
        arrays = sorted(name for name in definitions if OLD_ARRAY.fullmatch(name))
        assert (
            len(arrays) == proof["mapped_arrays"] == 20
            and set(arrays) == expected.keys()
        )
        modules = b"\n".join(
            module_at(data, definitions, name) for name in (*helpers, *arrays)
        )
        wrapper = """module tri_oracle_pe_array_decoupled (
    input wire clk, rst_n, in_valid, out_ready,
    input wire [2047:0] operand_a, operand_b,
    input wire [255:0] lane_enable,
    output wire in_ready, out_valid,
    output wire [607:0] out_sums
);
    wire [19:0] ready_by_array, valid_by_array;
    wire [607:0] sums_by_array [0:19];
    assign in_ready = ready_by_array[0];
    assign out_valid = valid_by_array[0];
    assign out_sums = sums_by_array[0];
"""
        stable_pins = set(
            "clk rst_n in_valid out_ready operand_a operand_b lane_enable".split()
        )
        for index, name in enumerate(arrays):
            module = module_at(data, definitions, name)
            assert shadow_resets(module) == expected[name]
            ports = signature(module)
            aliases = set(expected[name]) - {"rst_n"}
            pins = {pin: pin for pin in stable_pins} | {
                alias: "rst_n" for alias in aliases
            }
            pins.update(
                in_ready=f"ready_by_array[{index}]",
                out_valid=f"valid_by_array[{index}]",
                out_sums=f"sums_by_array[{index}]",
            )
            assert pins.keys() == ports.keys()
            wrapper += f"    {name} array_{index} (\n        "
            wrapper += ", ".join(f".{pin}({pins[pin]})" for pin in sorted(pins))
            wrapper += ");\n"
    wrapper += f"""    initial $display("{MARKER}");

    always @(posedge clk) begin
        for (int i = 1; i < 20; i++) begin
            if ({{ready_by_array[i], valid_by_array[i]}} !== {{in_ready, out_valid}})
                $fatal(1, "Linked array %0d handshake mismatch", i);
            if (out_valid && sums_by_array[i] !== out_sums)
                $fatal(1, "Linked array %0d payload mismatch", i);
        end
    end
endmodule
"""
    return modules + b"\n" + wrapper.encode(), sorted(
        {tuple(pattern) for pattern in expected.values()}
    )


def fixture_arguments():
    argv = arguments(ORIGINAL / "replay/xrun.history")
    prior = (ORIGINAL / "replay/decoupled_mapped.v").resolve()
    argv[argv.index(str(prior))] = str((DEST / "arrays.v").resolve())
    return argv


def run():
    DEST.mkdir(exist_ok=True)
    data, _ = suite()
    (DEST / "arrays.v").write_bytes(data)
    argv = fixture_arguments()
    command = [
        "docker",
        "exec",
        "-e",
        "USER=downeyflyfan",
        "-e",
        "LOGNAME=downeyflyfan",
        "-e",
        "CDS_LIC_FILE=5280@localhost",
        "-e",
        "LM_LICENSE_FILE=5280@localhost",
        "-w",
        str(DEST.resolve()),
        "tri-oracle-eda",
        "/opt/cadence/bin/xrun",
        *argv,
    ]
    with (DEST / "console.log").open("w") as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)


def verify():
    data, variants = suite()
    mapped = DEST / "arrays.v"
    assert mapped.read_bytes() == data
    reports = simulation(DEST, PASS, [mapped], "decoupled_lockstep_tb")
    assert (DEST / "console.log").read_text().splitlines().count(MARKER) == 1
    assert arguments(DEST / "xrun.history") == fixture_arguments()
    paths = (LINK_PROOF, mapped, *reports, Path(__file__).resolve().relative_to(ROOT))
    return dict(
        state="all_linked_booth_array_reset_bindings_verified",
        arrays_replayed=20,
        reset_partitions=len(variants),
        delivered_lockstep_transactions_per_array=786,
        scope="Exact linked array modules and their reset bindings were replayed together. Each reset phase "
        "uses the same logical signal on the physical reset aliases.",
        evidence_sha256={str(path): digest(path) for path in paths},
    )


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("action", choices=("run", "verify"))
    if cli.parse_args().action == "run":
        run()
    print(json.dumps(verify(), indent=2, sort_keys=True))
