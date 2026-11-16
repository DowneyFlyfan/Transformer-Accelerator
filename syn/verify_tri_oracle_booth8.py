"""Prepare the fixed-width Booth trial and verify the mapped multiplier comparison."""

import argparse
from decimal import Decimal
import json
from pathlib import Path
import re

from verify_tri_oracle_gated_compute_array import (
    CELL_SITE_AREA,
    ROOT,
    RTL,
    RTL_PROOF,
    SLOW_LIB,
    WORK as BASE,
    compile_script,
    digest,
    read,
)
from verify_tri_oracle_host_status import arguments

WORK = BASE.with_name("booth_multiplier")
MULTIPLIER = Path("verilog/tri_oracle_booth8.sv")
SOURCES = {
    "booth8.sv": MULTIPLIER,
    "unit_tb.sv": Path("verilog/tri_oracle_booth8_tb.sv"),
    "mapped_unit_tb.sv": Path("verilog/tri_oracle_booth8_mapped_tb.sv"),
    "unit.tcl": Path("syn/tri_oracle_synthesize_multiplier_unit.tcl"),
}
CELL_MODELS = SLOW_LIB.with_name("tcbn28hpcplusbwp12t40p140.v")
RTL_PASS = "BOOTH8_EXHAUSTIVE_PASS cases=65536"
MAPPED_PASS = "MAPPED_PRODUCT_EXHAUSTIVE_PASS cases=131072 enabled=65536 disabled=65536"


def unit_source(variant):
    prefix = """module product(
    input logic clk, enable,
    input logic signed [7:0] a, b,
    output logic signed [15:0] q
);
"""
    if variant == "booth":
        prefix += (
            "    wire signed [15:0] p;\n    tri_oracle_booth8 multiplier(a, b, p);\n"
        )
    expr = "p" if variant == "booth" else "$signed(a) * $signed(b)"
    return (
        prefix
        + f"""    always_ff @(posedge clk) begin
        if (enable)
            q <= {expr};
        else
            q <= '0;
    end
endmodule
"""
    )


def array_source():
    assert digest(RTL) == read(RTL_PROOF)["evidence_sha256"][str(RTL)]
    original = RTL.read_text()
    value = "        reg signed [2*DATA_W-1:0] value;\n"
    original_multiply = """                    value <= $signed(operand_a[p*DATA_W +: DATA_W]) *
                             $signed(operand_b[p*DATA_W +: DATA_W]);"""
    assert original.count(value) == original.count(original_multiply) == 1
    new_multiply = """        wire signed [2*DATA_W-1:0] multiplied;
        if (DATA_W == 8) begin : recoded
            tri_oracle_booth8 signed_multiplier(
                .a(operand_a[p*DATA_W +: DATA_W]),
                .b(operand_b[p*DATA_W +: DATA_W]),
                .p(multiplied)
            );
        end else begin : generic_product
            assign multiplied = $signed(operand_a[p*DATA_W +: DATA_W]) *
                                $signed(operand_b[p*DATA_W +: DATA_W]);
        end
"""
    array_rtl = original.replace(value, value + new_multiply).replace(
        original_multiply, "                    value <= multiplied;"
    )
    return array_rtl + "\n" + MULTIPLIER.read_text()


def prepare():
    WORK.mkdir(exist_ok=True)
    for name, source in SOURCES.items():
        (WORK / name).write_bytes(source.read_bytes())
    for variant in ("base", "booth"):
        folder = WORK / variant
        folder.mkdir(exist_ok=True)
        (folder / "product.sv").write_text(unit_source(variant))
    array = WORK / "array"
    array.mkdir(exist_ok=True)
    (array / "array.sv").write_text(array_source())
    (array / "synthesize.tcl").write_text(compile_script())


def simulation(folder, marker, sources, top):
    log, history = (folder / name for name in ("console.log", "xrun.history"))
    text = log.read_text()
    assert (
        text.splitlines().count(marker)
        == text.count("Simulation complete via $finish(1)")
        == 1
    )
    assert not re.search(r"\*[EF],", text)
    argv = arguments(history)
    assert argv[argv.index("-top") + 1] == top
    assert all(str(path.resolve()) in argv for path in sources)
    return [log, history]


def verify():
    for filename, source in SOURCES.items():
        assert (WORK / filename).read_bytes() == source.read_bytes()
    for name, source in (
        ("array.sv", array_source()),
        ("synthesize.tcl", compile_script()),
    ):
        assert (WORK / "array" / name).read_text() == source
    evidence = [
        *SOURCES.values(),
        *(WORK / name for name in SOURCES),
        RTL_PROOF,
        RTL,
        WORK / "array/array.sv",
        WORK / "array/synthesize.tcl",
        SLOW_LIB,
        CELL_MODELS,
        Path(__file__).resolve().relative_to(ROOT),
    ]
    evidence.extend(
        simulation(
            WORK / "green", RTL_PASS, (WORK / "booth8.sv", WORK / "unit_tb.sv"), "tb"
        )
    )
    variants = {}
    for name in ("base", "booth"):
        folder = WORK / name
        rtl, mapped, console, area, setup = (
            folder / filename
            for filename in (
                "product.sv",
                "netlist.v",
                "console.log",
                "area.rpt",
                "setup.rpt",
            )
        )
        assert rtl.read_text() == unit_source(name)
        assert (
            "MULTIPLIER_UNIT_MAPPED\n" in console.read_text()
            and "Normal exit." in console.read_text()
        )
        assert SLOW_LIB.name in console.read_text()
        assert SLOW_LIB.stem in area.read_text()
        cells, area_um2 = re.search(
            r"(?m)^product\s+NA\s+(\d+)\s+([\d.]+)", area.read_text()
        ).groups()
        sites = Decimal(area_um2) / CELL_SITE_AREA
        assert sites == int(sites)
        setup_slack = min(map(int, re.findall(r"Slack:=\s+(-?\d+)", setup.read_text())))
        variants[name] = dict(
            mapped_cells=int(cells),
            sites=int(sites),
            area_um2=float(area_um2),
            prelayout_setup_slack_ps=setup_slack,
            mapped_operand_enable_cases=131072,
        )
        evidence.extend(
            simulation(
                folder / "mapped_replay",
                MAPPED_PASS,
                (CELL_MODELS, mapped, WORK / "mapped_unit_tb.sv"),
                "mapped_product_tb",
            )
        )
        evidence.extend((rtl, mapped, console, area, setup))
    saved = variants["base"]["sites"] - variants["booth"]["sites"]
    assert saved > 0
    return dict(
        state="exhaustively_verified_signed_multiplier_unit_mapping",
        clock_megahertz=580,
        variants=variants,
        row_sites_saved_per_multiplier=saved,
        rtl_signed_operand_pairs=65536,
        scope="One registered signed multiplier. Genus timing excludes physical wires. The array and whole-chip "
        "area depend on synthesis and placement of the complete design.",
        evidence_sha256={str(path): digest(path) for path in evidence},
    )


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("action", choices=("prepare", "verify"))
    if cli.parse_args().action == "prepare":
        prepare()
    else:
        print(json.dumps(verify(), indent=2, sort_keys=True))
