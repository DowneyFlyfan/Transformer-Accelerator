"""Bind the two-phase weight storage into the joined command-layer source."""

import argparse
import re
from pathlib import Path

from prepare_tri_oracle_activation_bank_overlap import (
    ACTIVATION_MACRO, TIMED_ACTIVATION_MACRO, broadcast_chip_activation, prepare_activation_cluster,
    prepare_activation_core, schedule_next_activation_tile,
)
from prepare_tri_oracle_cluster_weight_phase import (
    ROOT, TIMED_MACRO, TS5_MACRO, distribute_weight_macro_inputs, edit, prepare_cluster, prepare_core,
    prepare_mapped_fabric_adapter,
)
from prepare_tri_oracle_phase_macro_boundary import REPAIRED_CLOCK_BOUNDARY
from prepare_tri_oracle_backpressured_weight_transport import RAW, raw_loader
from prepare_tri_oracle_weight_tile_prefetch import (
    bind_weight_guards, check_guarded_weight_writes, guard_weight_ingress, prepare_guard_stress_bench,
    register_scheduler_tile_length, schedule_weight_prefetch,
)


INCLUDE = re.compile(r'(?m)^`include "([^"]+)"$')
JOINED = ROOT / ".cache/physical/wide_weight_loader/dual_lane_joined_chip"
PHASE_INPUTS = """    input wire weight_memory_clk,
"""
PHASE_PORTS = """  input logic memory_clk,
  input logic [4:0] phase_address,
  input logic [63:0] phase_ce_n,
  input logic phase_we_n,
  input logic [31:0] phase_rows,
  input logic [2047:0] phase_data,
  output logic [3:0] phase_read_cores,
"""
CLOCK_SOURCE = """  logic clk, weight_memory_clk=1, divider_reset_n=0;
  always #0.431 weight_memory_clk=~weight_memory_clk;
  initial begin
    repeat (2) @(posedge weight_memory_clk);
    divider_reset_n=1;
  end
  tri_oracle_weight_phase_clock divider (
    .memory_clk(weight_memory_clk), .rst_n(divider_reset_n), .core_clk(clk)
  );"""
DERIVED_CLOCK_PEER = """  logic weight_memory_clk=1, external_rst_n=1;
  wire clk = dut.core_clk;
  always #431ps weight_memory_clk=~weight_memory_clk;
  initial begin
    #1ps;
    external_rst_n=0;
    repeat (2) @(posedge weight_memory_clk);
    #17ps;
    external_rst_n=1;
  end"""
RESET_PEER_CHECK = """  always @(posedge clk) if (rst_n && dut.core_rst_n !== 1'b1)
    $fatal(1, "PHASE_CHIP_COMMAND_BEFORE_CORE_RESET_RELEASE");
endmodule
"""


def clock_port(source, declaration, connection=None, copies=1):
    if source.count(declaration) != copies:
        raise ValueError(f"Unexpected clock declarations: {declaration}")
    source = source.replace(declaration, declaration.replace("clk", "clk, weight_memory_clk", 1))
    if connection:
        source = edit(source, [(connection, " .weight_memory_clk, " + connection)])
    return source


def transform_fabric(source):
    return edit(source, [
        ("    input wire clk,rst_n,load_valid,\n", PHASE_INPUTS+"    input wire clk,rst_n,load_valid,\n"),
        ("    assign load_error=(|load_errors) || (load_valid && load_core>=20);", """    logic [4:0][3:0] phase_read_cores;
    logic [4:0][4:0] phase_address;
    logic [4:0][63:0] phase_ce_n;
    logic [4:0] phase_we_n;
    logic [4:0][31:0] phase_rows;
    logic [4:0][2047:0] phase_data;
    logic phase_error;
    assign load_error=(|load_errors) || (load_valid && load_core>=20) || phase_error;
    tri_oracle_phase_weight_ingress weight_ingress (
        .clk, .memory_clk(weight_memory_clk), .rst_n,
        .read_cores(phase_read_cores), .read_address(cmd_weight),
        .scalar_valid(load_valid && load_kind==0), .scalar_core(load_core),
        .scalar_address(load_addr), .scalar_rows(load_row_enable), .scalar_data(load_payload),
        .wide_valid(wide_load_valid), .wide_core(wide_load_core), .wide_address(wide_load_addr),
        .wide_group(wide_load_group), .wide_rows(wide_load_enable), .wide_data(wide_load_payload),
        .error(phase_error), .phase_address, .phase_ce_n, .phase_we_n, .phase_rows, .phase_data
    );"""),
        ("""        wire write_lane0 = wide_load_valid[0] && wide_load_core[0][4:2]==3'(cluster);
        wire write_lane1 = wide_load_valid[1] && wide_load_core[1][4:2]==3'(cluster);
        wire wide_write = write_lane0 || write_lane1;
""", ""),
        ("""            .clk(clk),.rst_n(rst_n),
            .load_valid(wide_write || (load_valid && load_core[4:2]==3'(cluster))),
            .load_core(wide_write ? wide_load_core[write_lane1][1:0] : load_core[1:0]),
            .load_kind(wide_write ? 2'b00 : load_kind),
            .load_addr(wide_write ? wide_load_addr[write_lane1] : load_addr),.load_payload(load_payload),
            .load_row_enable(wide_write ? wide_load_enable[write_lane1] : load_row_enable),
            .load_error(load_errors[cluster]),
            .wide_load_valid(wide_write),.wide_load_group(wide_load_group[write_lane1]),
            .wide_load_payload(wide_load_payload[write_lane1]),""", """            .clk(clk),.rst_n(rst_n),.memory_clk(weight_memory_clk),
            .phase_address(phase_address[cluster]), .phase_ce_n(phase_ce_n[cluster]),
            .phase_we_n(phase_we_n[cluster]), .phase_rows(phase_rows[cluster]), .phase_data(phase_data[cluster]),
            .phase_read_cores(phase_read_cores[cluster]),
            .load_valid(load_valid && load_kind!=0 && load_core[4:2]==3'(cluster)),
            .load_core(load_core[1:0]), .load_kind, .load_addr, .load_payload, .load_row_enable,
            .load_error(load_errors[cluster]),"""),
    ])


def transform_cluster_adapter(source):
    header, _ = source.split("  logic [2047:0] load_data, scalar_load_data;", 1)
    return edit(header, [
        ("  input logic clk,\n", "  input logic clk,\n" + PHASE_PORTS),
        ("  input logic wide_load_valid,\n  input logic [1:0] wide_load_group,\n"
         "  input logic [511:0] wide_load_payload,\n", ""),
    ]) + """  logic [2047:0] load_data;
  tri_oracle_load_payload_decode decode_load_payload (.*);
  tri_oracle_sram_compute_cluster #(
      .MERGE_FEATURES(MERGE_FEATURES), .AGGREGATOR_MERGE_TABLE(AGGREGATOR_MERGE_TABLE),
      .LOCAL_TOKEN_SIZES(LOCAL_TOKEN_SIZES), .LOCAL_TOKEN_MERGE(LOCAL_TOKEN_MERGE),
      .MERGE_TABLE_ENTRIES(MERGE_TABLE_ENTRIES), .MERGE_TABLE_START(MERGE_TABLE_START),
      .CORE_STRIP_PREDICTOR(CORE_STRIP_PREDICTOR), .CORE_HEAD_PREDICTOR(CORE_HEAD_PREDICTOR)
  ) block_instance (.*);
endmodule
"""


def derive_chip_clock(source):
    source = edit(source, [
        ("  input logic clk, weight_memory_clk,\n", "  input logic weight_memory_clk,\n"),
        ("  logic [5:0] layer_command_valid;", """  logic core_clk, core_rst_n;
  tri_oracle_phase_chip_clock clock_source (
    .memory_clk(weight_memory_clk), .rst_n(rst_n), .core_clk, .core_rst_n
  );
  logic [5:0] layer_command_valid;"""),
    ])
    for bound, internal in ((".clk(clk)", ".clk(core_clk)"), (".rst_n(rst_n),\n", ".rst_n(core_rst_n),\n")):
        if source.count(bound) != 2:
            raise ValueError(f"expected clock or reset binding at both command sinks: {bound}")
        source = source.replace(bound, internal)
    return source


def transform_chip(sources, buffered):
    command_layer = "tri_oracle_chip_command_layer.sv"
    sources[command_layer] = clock_port(sources[command_layer], "  input logic clk,\n",
        ".clk(clk),\n    .rst_n(rst_n),\n    .cfg_valid(layer_command_valid[0]),")
    sources["boundary.sv"] = edit(sources["boundary.sv"], [
        (") (clk, rst_n, cfg_valid,", ") (clk, weight_memory_clk, rst_n, cfg_valid,"),
        ("  input clk;\n", "  input clk;\n  input weight_memory_clk;\n"),
        (""".PERSIST_LAYER_CONTEXT(1), .PACKED_FEEDFORWARD_WEIGHTS(PACKED_FEEDFORWARD_WEIGHTS)) layer (
""", """.PERSIST_LAYER_CONTEXT(1), .PACKED_FEEDFORWARD_WEIGHTS(PACKED_FEEDFORWARD_WEIGHTS)) layer (
    .weight_memory_clk,
"""),
    ])
    for module, declaration, connection, copies in (
        ("tri_oracle_shared_layer437", "    input logic clk, rst_n, cfg_valid,", None, 1),
        ("tri_oracle_batched_learned406", "    input logic clk, rst_n, cfg_valid,",
         ".clk(clk), .rst_n(rst_n), .cfg_valid(launch_compute)", 2),
        ("tri_oracle_batched_frame393", "  input logic clk,rst_n,cfg_valid,", ".clk(clk),.rst_n(rst_n),", 2),
        ("tri_oracle_batched_shared392", "  input logic clk,rst_n,cfg_valid,",
         ".clk(clk),.rst_n(rst_n),.cfg_valid(accept)", 1),
        ("tri_oracle_batched_tensor390", "  input logic clk,rst_n,cfg_valid,",
         ".clk(clk),.rst_n(backend_rst_n),.load_valid", 1),
    ):
        name = module + ".sv"
        sources[name] = clock_port(sources[name], declaration, connection, copies)
    sources["tri_oracle_compute_fabric.sv"] = transform_fabric(sources["tri_oracle_compute_fabric.sv"])
    sources["cluster_adapter.sv"] = transform_cluster_adapter(sources["cluster_adapter.sv"])
    cluster = "tri_oracle_sram_compute_cluster.sv"
    sources[cluster] = prepare_cluster(edit(sources[cluster], [
        ("&& !load_valid && count < 16", "&& (!load_valid || load_kind == 0) && count < 16"),
    ]))
    core = "tri_oracle_sram_memory_compute.sv"
    sources[core] = prepare_core(sources[core])
    if buffered:
        sources[core] = distribute_weight_macro_inputs(sources[core])
    return sources


def prepare(output, buffered=False, derived_clock=False, activation_broadcast=False, activation_prefetch=False,
            weight_prefetch=False, registered_tile_length=False):
    bundle = (JOINED / "bundle.sv").read_text()
    paths = [Path(name) for name in INCLUDE.findall(bundle)]
    prepared_names = (
        "tri_oracle_chip_command_layer.sv", "boundary.sv", "tri_oracle_shared_layer437.sv",
        "tri_oracle_batched_learned406.sv", "tri_oracle_batched_frame393.sv", "tri_oracle_batched_shared392.sv",
        "tri_oracle_batched_tensor390.sv", "tri_oracle_compute_fabric.sv", "cluster_adapter.sv",
        "tri_oracle_sram_compute_cluster.sv", "tri_oracle_sram_memory_compute.sv",
    )
    output.mkdir(parents=True, exist_ok=True)
    work_sources = {}
    for name in prepared_names:
        path, = (path for path in paths if path.name == name)
        work_sources[name] = path.read_text()
        bundle = edit(bundle, [(str(path), str(output / name))])
    transform_chip(work_sources, buffered)
    if derived_clock:
        top = "tri_oracle_chip_command_layer.sv"
        work_sources[top] = derive_chip_clock(work_sources[top])
    if activation_broadcast:
        tensor, fabric = "tri_oracle_batched_tensor390.sv", "tri_oracle_compute_fabric.sv"
        work_sources[tensor], work_sources[fabric] = broadcast_chip_activation(
            work_sources[tensor], work_sources[fabric])
        core = "tri_oracle_sram_memory_compute.sv"
        cluster = "tri_oracle_sram_compute_cluster.sv"
        work_sources[core] = prepare_activation_core(work_sources[core], timed=activation_prefetch)
        work_sources[cluster] = prepare_activation_cluster(work_sources[cluster])
        if activation_prefetch:
            work_sources[tensor] = schedule_next_activation_tile(work_sources[tensor])
        if weight_prefetch:
            work_sources[tensor] = schedule_weight_prefetch(work_sources[tensor])
            work_sources[fabric] = bind_weight_guards(work_sources[fabric])
        if registered_tile_length:
            work_sources[tensor] = register_scheduler_tile_length(work_sources[tensor])
    for name, contents in work_sources.items():
        (output / name).write_text(contents)
    pe, = (path for path in paths if path.name == "tri_oracle_pe_array.sv")
    booth = ROOT / ".cache/physical/whole_chip_xcelium_speed/booth_multiplier/sparse_reduce_trial/array/array.sv"
    bundle = edit(bundle, [(str(pe), str(booth))])
    weight, = (path for path in paths if path.name == "ts5n28hpcpsvta32x128m2fw_130a_tt1v25c.v")
    model = weight.read_text(encoding="latin-1")
    timed = output / "weight_timed.v"
    timed.write_text(model.replace(TS5_MACRO, TIMED_MACRO).replace(
        "`ifdef UNIT_DELAY", "`ifdef TRI_ORACLE_WEIGHT_UNIT_DELAY"), encoding="latin-1")
    rtl = ROOT / "verilog"
    sources = [timed] + [rtl / (name + ".sv") for name in (
        "tri_oracle_weight_phase_clock", "tri_oracle_weight_phase_port", "tri_oracle_cluster_weight_phase",
        "weight_stream_write_arbiter", "tri_oracle_weight_write_buffer",
    )]
    fabric, ingress = (rtl / (name + ".sv") for name in (
        "tri_oracle_weight_phase_fabric", "tri_oracle_phase_weight_ingress",
    ))
    if buffered:
        mapped = (REPAIRED_CLOCK_BOUNDARY / "controller.v" if derived_clock else
                  ROOT / ".cache/cluster_weight_phase/macro_boundary_distributed/controller.v")
        adapter = output / "mapped_fabric_adapter.sv"
        adapter.write_text(prepare_mapped_fabric_adapter(fabric.read_text()))
        bound = output / ingress.name
        ingress_source = edit(ingress.read_text(), [
            ("tri_oracle_weight_phase_fabric weight_port (", "tri_oracle_weight_phase_fabric_adapter weight_port ("),
        ])
        if weight_prefetch:
            ingress_source = guard_weight_ingress(ingress_source)
        bound.write_text(ingress_source)
        sources += [mapped, adapter, bound]
    else:
        sources += [fabric, ingress]
    if derived_clock:
        mapped_clock = REPAIRED_CLOCK_BOUNDARY / "clock.v"
        if not mapped_clock.is_file():
            raise ValueError("run the clock mapping before building the single-clock candidate")
        sources.append(mapped_clock)
    if activation_prefetch:
        model, = (path for path in paths if path.name == "ts5n28hpcpsvta512x64m4f_130a_tt1v25c.v")
        text = model.read_text(encoding="latin-1")
        if text.count(f"module {ACTIVATION_MACRO} (") != 1 or "`ifdef UNIT_DELAY" not in text:
            raise ValueError("expected the original activation memory timing model")
        activation_model = output / "activation_timed.v"
        activation_model.write_text(text.replace(ACTIVATION_MACRO, TIMED_ACTIVATION_MACRO).replace(
            "`ifdef UNIT_DELAY", "`ifdef TRI_ORACLE_ACTIVATION_UNIT_DELAY"), encoding="latin-1")
        sources.extend((activation_model, rtl / "tri_oracle_activation_tile_prefetch_probe.sv"))
    if weight_prefetch:
        raw = output / (RAW + ".sv")
        raw.write_text(raw_loader((rtl / "tri_oracle_parallel_weight_loader.sv").read_text()))
        probe = output / "guarded_weight_probe.sv"
        probe.write_text(check_guarded_weight_writes((rtl / "tri_oracle_phase_chip_probe.sv").read_text()))
        sources.extend((raw, rtl / "tri_oracle_projection_weight_reuse.sv",
                        rtl / "tri_oracle_weight_tile_prefetch_probe.sv", probe))
    (output / "bundle.sv").write_text(bundle + "".join(f'`include "{path}"\n' for path in sources))
    clock_peer = DERIVED_CLOCK_PEER if derived_clock else CLOCK_SOURCE
    command_clock_ports = ("    .weight_memory_clk,\n    .rst_n(external_rst_n)," if derived_clock
                           else "    .clk(clk),\n    .weight_memory_clk,\n    .rst_n(rst_n),")
    bench_changes = [
        ("  logic clk=0;always #5 clk=~clk;", clock_peer),
        ("    .clk(clk),\n    .rst_n(rst_n),", command_clock_ports),
    ]
    if derived_clock:
        bench_changes.append(("endmodule\n", RESET_PEER_CHECK))
    for source, target in (("trained_tb.sv", "bench.sv"), ("full_native/trained_tb.sv", "trained_bench.sv")):
        (output / target).write_text(edit((JOINED / source).read_text(), bench_changes))
    if weight_prefetch:
        test = prepare_guard_stress_bench((output / "bench.sv").read_text())
        (output / "weight_prefetch_stress_bench.sv").write_text(test)
    if activation_prefetch:
        bench = (output / "bench.sv").read_text()
        fault = edit(bench, [
            ("      sign_fault_address(read_address));", """      (FAULT==17 && activation_address(read_address)
       && dut.layer.layer.feedforward.compute.compute.tensor.prefetch_inflight)
      || sign_fault_address(read_address));"""),
            ("      if(rsp_error)fault_seen<=1;",
             """      if(rsp_error)begin
        if(FAULT==17 && rsp_last) $fatal(1,"CHIP_PREFETCH_FAULT_REQUIRED_DRAIN");
        fault_seen<=1;
      end"""),
            ("FAULT<=4 || FAULT==7 || FAULT==11", "FAULT<=4 || FAULT==7 || FAULT==11 || FAULT==17"),
        ])
        (output / "prefetch_fault_bench.sv").write_text(fault)
    scalar = JOINED.parent / "parallel_chip_load_address/trained_tb.sv"
    (output / "scalar_bench.sv").write_text(edit(scalar.read_text(), bench_changes + [
        ("dut.layer.layer.feedforward.predictor.activation_path.cfg_valid && "
         "dut.layer.layer.feedforward.predictor.activation_path.cfg_ready",
         "dut.layer.layer.feedforward.scalar_signs.predictor.activation_path.cfg_valid && "
         "dut.layer.layer.feedforward.scalar_signs.predictor.activation_path.cfg_ready"),
    ]))
    attention = JOINED.parent / "parallel_chip_v3/attention_tb.sv"
    attention_clock_ports = "    .weight_memory_clk,\n"
    if derived_clock:
        attention_clock_ports += "    .rst_n(external_rst_n),\n"
    attention_changes = [
        ("    logic clk=0,rst_n=0;\n    always #5 clk=~clk;", "    logic rst_n=0;\n" + clock_peer),
        ("    tri_oracle_chip_command_layer dut (\n",
         "    tri_oracle_chip_command_layer dut (\n" + attention_clock_ports),
    ]
    if derived_clock:
        attention_changes.append(("endmodule\n", RESET_PEER_CHECK))
    (output / "attention_bench.sv").write_text(edit(attention.read_text(), attention_changes))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--buffered-boundary", action="store_true")
    parser.add_argument("--derived-clock", action="store_true")
    parser.add_argument("--activation-broadcast", action="store_true")
    parser.add_argument("--activation-prefetch", action="store_true")
    parser.add_argument("--weight-prefetch", action="store_true")
    parser.add_argument("--registered-tile-length", action="store_true")
    args = parser.parse_args()
    if args.derived_clock and not args.buffered_boundary:
        parser.error("use the verified buffered weight boundary with the derived clock")
    if args.activation_broadcast and not args.derived_clock:
        parser.error("the activation broadcast uses the internally divided chip clock")
    if args.activation_prefetch and not args.activation_broadcast:
        parser.error("tile prefetch uses the verified activation broadcast")
    if args.weight_prefetch and not args.activation_prefetch:
        parser.error("early weight fetch uses the next activation tile")
    if args.registered_tile_length and not args.weight_prefetch:
        parser.error("registered tile length requires the weight-prefetch scheduler")
    prepare(args.output.resolve(), args.buffered_boundary, args.derived_clock,
            args.activation_broadcast, args.activation_prefetch, args.weight_prefetch, args.registered_tile_length)
