"""Route four existing upper input banks in cluster zero to a shared residual port."""

import argparse
from pathlib import Path

from prepare_tri_oracle_residual_bank_core import TOP as CORE, replace_once, residual_core

TOP = "tri_oracle_residual_compute_fabric"
CLUSTER = "tri_oracle_residual_compute_cluster"
PORTS = """  input logic residual_reserved, residual_ce_n, residual_we_n,
  input logic [8:0] residual_addr,
  input logic [255:0] residual_d,
  output logic [255:0] residual_q"""
STRIP_PORTS = PORTS.replace("[255:0]", "[63:0]")
LINK = ".residual_reserved, .residual_ce_n, .residual_we_n, .residual_addr, .residual_d, .residual_q"


def add_ports(source, ports):
    head, separator, body = source.partition("\n);")
    if not separator:
        raise ValueError("Expected a module port list")
    return f"{head},\n{ports}{separator}{body}"


def cluster_variant(source):
    cluster = source.split("\nendmodule", 1)[0] + "\nendmodule\n"
    _, separator, strip = source.partition("module tri_oracle_sram_strip_core448")
    if not separator:
        raise ValueError("Expected the native strip core module")
    strip = "module tri_oracle_residual_strip_core" + strip.split("\nendmodule", 1)[0] + "\nendmodule\n"
    cluster = replace_once(cluster, "module tri_oracle_sram_compute_cluster", f"module {CLUSTER}")
    cluster = replace_once(cluster, "tri_oracle_sram_strip_core448 #", "tri_oracle_residual_strip_core #")
    cluster = replace_once(
        cluster, ".read_valid(done_aligned)", f"{LINK},\n    .read_valid(done_aligned)"
    )
    strip = replace_once(strip, "tri_oracle_sram_memory_compute compute", f"{CORE} compute")
    return add_ports(cluster, PORTS) + "\n" + add_ports(strip, STRIP_PORTS)


def fabric_variant(source):
    source = replace_once(source, "module tri_oracle_compute_fabric", f"module {TOP}")
    declaration = "        tri_oracle_compute_cluster #("
    _, separator, tail = source.partition(declaration)
    cluster, terminator, _ = tail.partition("\n        );")
    if not separator or not terminator:
        raise ValueError("Expected the native cluster instantiation")
    original_instance = declaration + cluster + terminator
    routed_instance = (
        original_instance.replace("tri_oracle_compute_cluster", CLUSTER, 1)
        .replace(") unit (", f") unit (\n            {LINK},", 1)
    )
    source = replace_once(
        source, original_instance, f"""        if (cluster == 0) begin : residual
{routed_instance}
        end else begin : native
{original_instance}
        end""",
    )
    return add_ports(source, PORTS)


def prepare(output):
    rtl = Path(__file__).resolve().parents[1] / "verilog"
    core = residual_core((rtl / "tri_oracle_sram_memory_compute.sv").read_text())
    cluster = cluster_variant((rtl / "tri_oracle_sram_compute_cluster.sv").read_text())
    fabric = fabric_variant((rtl / "tri_oracle_compute_fabric.sv").read_text())
    with output.open("x") as stream:
        stream.write(core + "\n" + cluster + "\n" + fabric)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    prepare(parser.parse_args().output)
