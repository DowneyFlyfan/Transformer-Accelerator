"""Generate and compare sparse signed Booth multipliers under one synthesis recipe."""

from argparse import ArgumentParser
from decimal import Decimal
import json
from pathlib import Path
import re

from verify_tri_oracle_booth8 import (
    CELL_MODELS,
    MAPPED_PASS,
    RTL_PASS,
    SLOW_LIB,
    ROOT,
    WORK as BASE,
    digest,
    simulation,
)

OUT = BASE / "sparse_reduce_trial"
VARIANTS = (("mapped_add", False), ("block_lookahead", True))


def emit(use_lookahead):
    source = (ROOT / "verilog/tri_oracle_booth8.sv").read_text()
    prefix = source.split("    wire [15:0] row [0:3];")[0]
    statements = [
        prefix,
        "    wire [8:0] partial [0:3];",
        """
    for (genvar i = 0; i < 4; i++) begin : encode
        wire low = digits[2*i];
        wire middle = digits[2*i+1];
        wire high = digits[2*i+2];
        wire single = middle ^ low;
        wire double = !single && (high ^ middle);
        assign partial[i] = ((once & {9{single}}) | (twice & {9{double}})) ^ {9{high}};
    end
""",
    ]
    columns = [[] for _ in range(16)]

    def put(column, expression, level):
        if column < 16:
            columns[column].append((level, expression))

    # The original correction constant is 0xab00. The two low sign
    # correction bits combine with ~partial[0][8] into s,s,~s.
    for row in range(4):
        for bit in range(8):
            put(2 * row + bit, f"partial[{row}][{bit}]", 1)
        sign = f"partial[{row}][8]"
        if row == 0:
            put(8, sign, 1)
            put(9, sign, 1)
            put(10, f"~{sign}", 1)
        else:
            put(2 * row + 8, f"~{sign}", 1)
            put(2 * row + 9, "1'b1", 0)
        put(2 * row, f"digits[{2 * row + 2}]", 0)

    adders = {"half": 0, "full": 0}
    for target in (4, 3, 2):
        for column, bits in enumerate(columns):
            while len(bits) > target:
                count = 3 if len(bits) - target >= 2 else 2
                bits.sort()
                operands, bits[:] = bits[:count], bits[count:]
                max_level = max(level for level, _ in operands)
                index = adders["half"] + adders["full"]
                name = f"add_{index}"
                a, b, *extra = (f"({expression})" for _, expression in operands)
                if extra:
                    adders["full"] += 1
                    (c,) = extra
                    carry = f"({a} & {b}) | (({a} | {b}) & {c})"
                    total = f"{a} ^ {b} ^ {c}"
                else:
                    adders["half"] += 1
                    carry = f"{a} & {b}"
                    total = f"{a} ^ {b}"
                statements.append(f"    wire {name}_sum = {total};")
                put(column, f"{name}_sum", max_level + 1)
                if column < 15:
                    statements.append(f"    wire {name}_carry = {carry};")
                    put(column + 1, f"{name}_carry", max_level + 1)
    assert all(len(bits) <= 2 for bits in columns)
    for row, name in enumerate(("x", "y")):
        bits = [col[row][1] if len(col) > row else "1'b0" for col in reversed(columns)]
        statements.append(f"    wire [15:0] {name} = {{{', '.join(bits)}}};")
    if use_lookahead:
        statements.extend(lookahead())
    else:
        statements.append("    assign p = x + y;")
    statements.append("endmodule\n")
    return "\n".join(statements), adders


def lookahead():
    def terms(propagate, generate, low, high):
        return [
            "("
            + " & ".join(
                [f"{propagate}[{i}]" for i in range(high, bit, -1)]
                + [f"{generate}[{bit}]"]
            )
            + ")"
            for bit in range(low, high + 1)
        ]

    statements = [
        "    wire [15:0] pr = x ^ y;",
        "    wire [15:0] gen = x & y;",
        "    wire [3:0] blk_p, blk_g;",
        "    wire [15:0] into;",
        "    assign into[0] = 1'b0;",
    ]
    for group in range(4):
        start = 4 * group
        end = start + 3
        term = " | ".join(terms("pr", "gen", start, end))
        statements.append(f"    assign blk_p[{group}] = &pr[{end}:{start}];")
        statements.append(f"    assign blk_g[{group}] = {term};")
        if group > 0:
            term = " | ".join(terms("blk_p", "blk_g", 0, group - 1))
            statements.append(f"    assign into[{start}] = {term};")
        for bit in range(start + 1, end + 1):
            parts = terms("pr", "gen", start, bit - 1)
            path = " & ".join(f"pr[{i}]" for i in range(start, bit))
            parts.append(f"({path} & into[{start}])")
            term = " | ".join(parts)
            statements.append(f"    assign into[{bit}] = {term};")
    statements.append("    assign p = pr ^ into;")
    return statements


def prepare():
    for name, use_lookahead in VARIANTS:
        path = OUT / name
        path.mkdir(exist_ok=True)
        rtl, counters = emit(use_lookahead)
        (path / "booth8.sv").write_text(rtl)
        (path / "product.sv").write_bytes((BASE / "booth/product.sv").read_bytes())
        print(name, counters)


def verify():
    work = OUT
    reference = Path("records/tri_oracle_booth_multiplier.json")
    synthesis = Path("syn/tri_oracle_synthesize_multiplier_unit.tcl")
    rtl_tb = Path("verilog/tri_oracle_booth8_tb.sv")
    mapped_tb = Path("verilog/tri_oracle_booth8_mapped_tb.sv")
    evidence = [
        CELL_MODELS,
        SLOW_LIB,
        reference,
        synthesis,
        rtl_tb,
        mapped_tb,
        Path(__file__).resolve().relative_to(ROOT),
        work / "run.py",
        work / "red/console.log",
    ]
    assert (
        "BOOTH8_MISMATCH -128 * -128 got=16896 expected=16384"
        in (work / "red/console.log").read_text()
    )
    variants = {}
    for name in ("baseline", "mapped_add", "block_lookahead"):
        folder = work / name
        rtl, mapped, synth_log, area, setup, product = (
            folder / file
            for file in (
                "booth8.sv",
                "netlist.v",
                "console.log",
                "area.rpt",
                "setup.rpt",
                "product.sv",
            )
        )
        assert product.read_bytes() == (work.parent / "booth/product.sv").read_bytes()
        console = synth_log.read_text()
        assert "MULTIPLIER_UNIT_MAPPED\n" in console and "Normal exit." in console
        assert SLOW_LIB.name in console and SLOW_LIB.stem in area.read_text()
        n_cells, area_um2 = re.search(
            r"(?m)^product\s+NA\s+(\d+)\s+([\d.]+)", area.read_text()
        ).groups()
        sites = Decimal(area_um2) / Decimal("0.168")
        assert sites == int(sites)
        slacks = [
            int(val) for val in re.findall(r"Slack:=\s+(-?\d+)", setup.read_text())
        ]
        assert slacks
        variants[name] = dict(
            mapped_cells=int(n_cells),
            row_sites=int(sites),
            setup_slack_ps=min(slacks),
            signed_rtl_pairs=65536,
            mapped_operand_enable_cases=131072,
        )
        evidence.extend(simulation(folder / "rtl", RTL_PASS, (rtl, rtl_tb), "tb"))
        evidence.extend(
            simulation(
                folder / "mapped",
                MAPPED_PASS,
                (CELL_MODELS, mapped, mapped_tb),
                "mapped_product_tb",
            )
        )
        evidence.extend((rtl, mapped, synth_log, area, setup, product))
    original = json.loads(reference.read_text())["variants"]["booth"]
    assert variants["baseline"]["row_sites"] == original["sites"]
    assert (
        variants["baseline"]["setup_slack_ps"] == original["prelayout_setup_slack_ps"]
    )
    result = dict(
        state="signed_sparse_booth_unit_characterization_verified",
        variants=variants,
        scope="Single registered signed multiplier at 580 MHz under the same slow timing library and external allowances. Genus timing excludes physical wires. Full-array area and placement timing require separate evidence.",
        evidence_sha256={str(path): digest(path) for path in evidence},
    )
    assert (work / "baseline/booth8.sv").read_bytes() == (
        ROOT / "verilog/tri_oracle_booth8.sv"
    ).read_bytes()
    for name, use_lookahead in VARIANTS:
        expected, _ = emit(use_lookahead)
        assert (work / name / "booth8.sv").read_text() == expected
    return result


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "verify"))
    if parser.parse_args().action == "prepare":
        prepare()
    else:
        print(json.dumps(verify(), indent=2, sort_keys=True))
