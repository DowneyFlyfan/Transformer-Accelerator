"""Connect the mapped controller to the 320 original SRAM timing models."""

import argparse
import re
from pathlib import Path

from prepare_tri_oracle_cluster_weight_phase import ROOT, TS5_MACRO


MAPPING = ROOT / ".cache/cluster_weight_phase/fabric_mapping/mapped.v"
CLUSTERS, CORES, BANKS_PER_CORE = 5, 4, 16
CLOCK_MAPPING = ROOT / ".cache/phase_chip_clock/mapping/mapped.v"
REPAIRED_CLOCK_BOUNDARY = ROOT / ".cache/phase_chip_clock/macro_boundary_repaired"


def boundary(distribute, derived_clock=False):
    top = """module tri_oracle_phase_macro_boundary(
  input memory_clk, core_clk, rst_n,
  input [19:0] read_cores,
  input [4:0] read_address,
  input [1:0] write_pending, write_allowed,
  input [9:0] write_core,
  input [19:0] write_address,
  input [63:0] write_rows,
  input [2047:0] write_payload,
  output [1:0] write_retired
);
  wire [4:0] memory_we_n;
"""
    connections = [f".{port}({port})" for port in (
        "memory_clk", "core_clk", "rst_n", "read_address", "write_pending",
        "write_allowed", "write_retired", "memory_we_n",
    )]
    if derived_clock:
        top = top.replace("input memory_clk, core_clk, rst_n,", "input memory_clk, rst_n,")
        top += """  wire core_clk, core_rst_n;
  tri_oracle_phase_chip_clock clock_source (
    .memory_clk(memory_clk), .rst_n(rst_n), .core_clk(core_clk), .core_rst_n(core_rst_n)
  );
"""
        connections[2] = ".rst_n(core_rst_n)"
    for port, count, width in (
        ("read_cores", CLUSTERS, CORES), ("write_core", 2, 5), ("write_address", 2, 10),
        ("write_rows", 2, 32), ("write_payload", 2, 1024),
    ):
        for index in range(count):
            connections.append(f".\\{port}[{index}] ({port}[{width*(index+1)-1}:{width*index}])")
    for cluster in range(CLUSTERS):
        for port, width in (("memory_address", 5), ("memory_ce_n", 64), ("memory_rows", 32), ("memory_data", 2048)):
            top += f"  wire [{width-1}:0] {port}_{cluster};\n"
            connections.append(f".\\{port}[{cluster}] ({port}_{cluster})")
    top += "  tri_oracle_weight_phase_fabric controller (\n    " + ",\n    ".join(connections) + "\n  );\n"
    for cluster in range(CLUSTERS):
        groups = CORES if distribute else 1
        for group in range(groups):
            name = f"{cluster}_{group}"
            top += f"  wire [31:0] byte_we_n_{name};\n"
            for row in range(2*BANKS_PER_CORE):
                drive = 8 if distribute else 1
                top += (f"  INVD{drive}BWP12T40P140 row_inv_{name}_{row} "
                        f"(.I(memory_rows_{cluster}[{row}]), .ZN(byte_we_n_{name}[{row}]));\n")
        for core in range(CORES):
            address, write_enable = f"memory_address_{cluster}", f"memory_we_n[{cluster}]"
            name = f"{cluster}_{core}" if distribute else f"{cluster}_0"
            if distribute:
                top += f"  wire [4:0] local_address_{name};\n  wire local_we_n_{name};\n"
                for bit in range(5):
                    top += (f"  BUFFD4BWP12T40P140 addr_buf_{name}_{bit} "
                            f"(.I({address}[{bit}]), .Z(local_address_{name}[{bit}]));\n")
                top += (f"  BUFFD8BWP12T40P140 we_buf_{name} "
                        f"(.I({write_enable}), .Z(local_we_n_{name}));\n")
                address, write_enable = f"local_address_{name}", f"local_we_n_{name}"
            for bank in range(BANKS_PER_CORE):
                first_bit, last_bit = 128*bank, 128*(bank+1)-1
                low, high = f"byte_we_n_{name}[{2*bank}]", f"byte_we_n_{name}[{2*bank+1}]"
                enables = "{{64{" + high + "}},{64{" + low + "}}}"
                ce = core*BANKS_PER_CORE + bank
                top += (f"  {TS5_MACRO} weight_bank_{cluster}_{core}_{bank} (\n"
                        f"    .CLK(memory_clk), .A({address}),\n"
                        f"    .CEB(memory_ce_n_{cluster}[{ce}]), .WEB({write_enable}),\n"
                        f"    .D(memory_data_{cluster}[{last_bit}:{first_bit}]), .BWEB({enables}), .Q()\n  );\n")
    return top + "endmodule\n"


def delay_phase_logic(netlist):
    # Only combinational uses carry the sampled phase bit. Arbiter clock pins
    # retain the original core clock route.
    def rewire(match):
        prefix, pin = match.groups()
        if pin == "CP":
            return match[0]
        if pin not in {"A", "A1", "A2", "B", "B1", "B2", "I", "I0", "I1", "S"}:
            raise ValueError(f"unexpected core-clock pin {pin}")
        return prefix + "phase_select)"
    updated = re.sub(r"(\.(\w+)\s*\(\s*)core_clk\s*\)", rewire, netlist)
    if updated.count("phase_select)") < 10 or ".CP (core_clk)" not in updated:
        raise ValueError("phase buffer would affect the wrong clock sinks")
    declaration = "  wire memory_clk, core_clk, rst_n;\n"
    if updated.count(declaration) != 1:
        raise ValueError("expected original clock net declarations")
    updated = updated.replace(declaration, declaration + "  wire phase_delay_0, phase_delay_1, phase_select;\n")
    cells = """  BUFFD2BWP12T40P140 phase_buf_0 (.I(core_clk), .Z(phase_delay_0));
  BUFFD2BWP12T40P140 phase_buf_1 (.I(phase_delay_0), .Z(phase_delay_1));
  BUFFD8BWP12T40P140 phase_buf_2 (.I(phase_delay_1), .Z(phase_select));
"""
    header, end = updated.split("endmodule\n", 1)
    if end.strip():
        raise ValueError("expected a flattened phase controller")
    return header + cells + "endmodule\n"


def distribute_cluster_reset(netlist):
    counts = [0] * CLUSTERS
    cell = re.compile(r"(?ms)^(  [A-Z0-9]+\s+\\phase_cluster\[([0-4])\][^(]+\()(.*?\);)")
    reset_pin = r"\.(CDN|SDN)\s*\(\s*rst_n\s*\)"

    def rewire(match):
        header, cluster, pins = match.groups()
        updated, count = re.subn(reset_pin, rf".\1 (cluster_rst_n[{cluster}])", pins)
        counts[int(cluster)] += count
        return header + updated

    netlist = cell.sub(rewire, netlist)
    if counts != [75] * CLUSTERS or re.search(reset_pin, netlist):
        raise ValueError(f"unexpected reset fanout by cluster: {counts}")
    declaration = "  wire phase_delay_0, phase_delay_1, phase_select;\n"
    if netlist.count(declaration) != 1:
        raise ValueError("expected the buffered phase controller")
    netlist = netlist.replace(declaration, declaration + "  wire [4:0] cluster_rst_n;\n")
    cells = "".join(f"  BUFFD8BWP12T40P140 reset_buf_{cluster} (.I(rst_n), .Z(cluster_rst_n[{cluster}]));\n"
                    for cluster in range(CLUSTERS))
    return netlist.replace("endmodule\n", cells + "endmodule\n")


def delay_clock_hold_paths(netlist):
    for net, delayed in (("n_0", "divider_feedback"), ("memory_release[0]", "memory_sync_data"),
                         ("core_release[0]", "core_sync_data")):
        old = f".D ({net})"
        if netlist.count(old) != 1:
            raise ValueError(f"unexpected clock-mapping path: {net}")
        netlist = netlist.replace(old, f".D ({delayed})")
    declaration = "  wire n_0;\n"
    if netlist.count(declaration) != 1:
        raise ValueError("expected the original clock-mapping wires")
    netlist = netlist.replace(declaration, declaration + "  wire divider_feedback, memory_sync_data, core_sync_data;\n")
    cells = """  BUFFD1BWP12T40P140 divider_hold (.I(n_0), .Z(divider_feedback));
  BUFFD1BWP12T40P140 memory_sync_hold (.I(memory_release[0]), .Z(memory_sync_data));
  BUFFD1BWP12T40P140 core_sync_hold (.I(core_release[0]), .Z(core_sync_data));
"""
    return netlist.replace("endmodule\n", cells + "endmodule\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--distribute", action="store_true")
    parser.add_argument("--delay-phase", action="store_true")
    parser.add_argument("--derived-clock", action="store_true")
    parser.add_argument("--repair-reset", action="store_true")
    args = parser.parse_args()
    if args.repair_reset and not (args.derived_clock and args.delay_phase and args.distribute):
        parser.error("the reset repair requires the derived clock and buffered memory interface")
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    top = boundary(args.distribute, args.derived_clock)
    if top.count(" weight_bank_") != 320:
        raise ValueError("incorrect SRAM inventory")
    mapped = MAPPING.read_text()
    if args.delay_phase:
        mapped = delay_phase_logic(mapped)
    if args.repair_reset:
        mapped = distribute_cluster_reset(mapped)
    (output / "controller.v").write_text(mapped)
    if args.derived_clock:
        clock = CLOCK_MAPPING.read_text()
        if args.repair_reset:
            clock = delay_clock_hold_paths(clock)
        (output / "clock.v").write_text(clock)
        mapped += "\n" + clock
    (output / "macro_boundary.v").write_text(mapped + "\n" + top)


if __name__ == "__main__":
    main()
