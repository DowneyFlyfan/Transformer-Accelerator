"""Bind the two-phase weight port to the compiled four-core replay."""

import argparse
from pathlib import Path

from prepare_tri_oracle_early_weight_pairs import edit


PORTS = """  input logic memory_clk,
  input logic [4:0] phase_address,
  input logic [{banks}:0] phase_ce_n,
  input logic phase_we_n,
  input logic [31:0] phase_rows,
  input logic [2047:0] phase_data,
"""
TS5_MACRO = "TS5N28HPCPSVTA32X128M2FW"
TIMED_MACRO = f"TRI_ORACLE_TIMED_{TS5_MACRO}"
ROOT = Path(__file__).resolve().parents[1]


def prepare_core(source):
    return edit(source, [
        ("  input logic clk,\n", "  input logic clk,\n" + PORTS.format(banks=15)),
        ("  logic [15:0] weight_ceb, weight_web;\n", ""),
        ("logic [4:0] weight_address, mask_address;", "logic [4:0] mask_address;"),
        ("    weight_address = accepted_load ? load_addr[4:0] : cmd_weight;\n", ""),
        ("""      weight_bweb[row*64+:64] = {64{!load_row_enable[row]}};
    for (integer bank = 0; bank < 16; bank++) begin
      weight_web[bank] = !(rst_n && accepted_load && load_kind == 0 && load_addr < 32
                          && (|load_row_enable[bank*2+:2]));
      weight_ceb[bank] = weight_web[bank] && !accept_command;
    end""", "      weight_bweb[row*64+:64] = {64{!phase_rows[row]}};"),
        (f"""  {TS5_MACRO} weights[15:0] (
    .CLK(clk), .CEB(weight_ceb), .WEB(weight_web), .A(weight_address),
    .D(load_data), .BWEB(weight_bweb), .Q(weight_q)
  );""", f"""  {TIMED_MACRO} weights[15:0] (
    .CLK(memory_clk), .CEB(phase_ce_n), .WEB(phase_we_n), .A(phase_address),
    .D(phase_data), .BWEB(weight_bweb), .Q(weight_q)
  );"""),
        ("""load_error <= accepted_load && (load_kind == 3
                                  || ((load_kind == 0 || load_kind == 2) && load_addr >= 32));""",
         """load_error <= accepted_load && (load_kind == 0 || load_kind == 3
                                  || (load_kind == 2 && load_addr >= 32));"""),
    ])


def prepare_cluster(source):
    cluster, public = source.split("`ifdef TRI_ORACLE_SRAM_CLUSTER_BIND_PUBLIC\n")
    _, core = public.split("`endif\n", 1)
    cluster = edit(cluster, [
        ("  input logic clk,\n", "  input logic clk,\n" + PORTS.format(banks=63)
         + "  output logic [3:0] phase_read_cores,\n"),
        ("  assign core_issue = active_cores & {4{issue}};",
         "  assign core_issue = active_cores & {4{issue}};\n  assign phase_read_cores = core_issue;"),
        ("    .clk(clk), .rst_n(rst_n), .load_valid(core_load), .load_kind(load_kind),",
         """    .clk(clk), .memory_clk(memory_clk), .phase_address(phase_address),
    .phase_ce_n(phase_ce_n), .phase_we_n(phase_we_n), .phase_rows(phase_rows),
    .phase_data(phase_data), .rst_n(rst_n), .load_valid(core_load), .load_kind(load_kind),"""),
        ("&& (!load_valid || load_kind == 0) && count < 16", "&& !load_valid && count < 16"),
    ])
    core = edit(core, [("  input logic clk,\n", "  input logic clk,\n" + PORTS.format(banks=15))])
    return cluster + core


def prepare_bench(source):
    bridge = """  assign load_valid = weight_init ? seed_valid : transport_load_valid;
  assign load_core = weight_init ? seed_core : transport_load_core;
  assign load_addr = weight_init ? seed_addr : transport_load_addr;
  assign load_rows = weight_init ? seed_rows : transport_load_rows;
  assign load_payload = weight_init ? seed_payload : transport_load_payload;
  assign cluster_load_valid = init_valid;
  assign cluster_load_core = init_core;
  assign cluster_load_addr = init_addr;
  assign cluster_load_kind = init_kind;
  assign cluster_load_rows = '1;
  assign cluster_load_data = init_data;

  tri_oracle_cluster_weight_phase #(.CLUSTER_ID(3'd2)) weight_port (
    .memory_clk, .core_clk(clk), .rst_n, .read_cores(phase_read_cores),
    .read_address(cmd_weight), .write_pending(staged_pending), .write_allowed,
    .write_core(staged_core), .write_address(staged_addr), .write_rows(staged_rows),
    .write_payload(staged_payload), .write_retired(write_ready),
    .memory_address(phase_address), .memory_ce_n(phase_ce_n), .memory_we_n(phase_we_n),
    .memory_rows(phase_rows), .memory_data(phase_data)
  );

  always @(posedge memory_clk) if (rst_n && (phase_ce_n != '1)) begin
    if (phase_we_n) begin
      if (!clk || phase_ce_n != 0) $fatal(1, "CLUSTER_WEIGHT_BAD_READ_PHASE");
      physical_reads++;
    end else begin
      if (clk) $fatal(1, "CLUSTER_WEIGHT_BAD_WRITE_PHASE");
      if (unread_words[phase_address])
        $fatal(1, "CLUSTER_WEIGHT_PHYSICAL_OVERWRITE word=%0d", phase_address);
      if (!weight_init) physical_writes++;
    end
  end
"""
    return edit(source, [
        ("""  logic clk = 0, rst_n = 0;
  always #5 clk = ~clk;""", """  logic clk, memory_clk = 1, clock_rst_n = 0, rst_n = 0;
  always #0.431 memory_clk = ~memory_clk;
  tri_oracle_weight_phase_clock divider (.memory_clk, .rst_n(clock_rst_n), .core_clk(clk));"""),
        ("  logic serial, ignore_reservation, single_port;", "  logic serial, ignore_reservation;"),
        ("int serial_flag, bypass_flag, single_flag;", "int serial_flag, bypass_flag;"),
        ('    single_port = $value$plusargs("SINGLE_PORT=%d", single_flag) && single_flag != 0;\n', ""),
        ("  byte unsigned indices", """  logic [1:0] write_allowed, transport_load_valid, seed_valid = 0;
  logic [1:0][4:0] transport_load_core, seed_core = 0;
  logic [1:0][9:0] transport_load_addr, seed_addr = 0;
  logic [1:0][31:0] transport_load_rows, seed_rows = 0;
  logic [1:0][1023:0] transport_load_payload, seed_payload = 0;
  logic weight_init = 1;
  logic [3:0] phase_read_cores;
  logic [4:0] phase_address;
  logic [63:0] phase_ce_n;
  logic phase_we_n;
  logic [31:0] phase_rows;
  logic [2047:0] phase_data;
  int physical_reads = 0, physical_writes = 0;
  byte unsigned indices"""),
        ("""    .rsp_ready, .rsp_data, .load_valid, .load_ready, .load_core, .load_addr,
    .load_row_enable(load_rows), .load_payload, .done_valid(transport_done),""",
         """    .rsp_ready, .rsp_data, .load_valid(transport_load_valid),
    .load_ready(weight_init ? 2'b00 : load_ready), .load_core(transport_load_core),
    .load_addr(transport_load_addr), .load_row_enable(transport_load_rows),
    .load_payload(transport_load_payload), .done_valid(transport_done),"""),
        ("assign write_ready[lane] = (ignore_reservation || reserved_address_safe) && !init_valid;",
         "assign write_allowed[lane] = ignore_reservation || reserved_address_safe;"),
        (source[source.index("  assign cluster_load_valid"):source.index("  assign cmd_ready")], bridge),
        ("""  tri_oracle_sram_compute_cluster cluster (
    .clk,""", """  tri_oracle_sram_compute_cluster cluster (
    .clk, .memory_clk, .phase_address, .phase_ce_n, .phase_we_n,
    .phase_rows, .phase_data, .phase_read_cores,"""),
        ("(| (load_valid & ~load_ready))", "(!weight_init && |(load_valid & ~load_ready))"),
        ("if (| (staged_pending & ~write_ready)) blocked_cycles++;",
         "if (| (staged_pending & ~write_allowed)) blocked_cycles++;"),
        ("if (staged_valid[lane]) begin", "if (staged_valid[lane] && !weight_init) begin"),
        ("    repeat (2) @(negedge clk);", """    repeat (2) @(posedge memory_clk);
    clock_rst_n = 1;
    repeat (2) @(negedge clk);"""),
        ("""    for (int core = 0; core < 4; core++) begin
      for (int word = 0; word < 32; word++)
        initialize_word(0, core, word, initial_weights[32*core+word]);
      for (int tile""", """    for (int core = 0; core < 4; core++)
      for (int word = 0; word < 32; word++)
        for (int half = 0; half < 2; half++) begin
          @(negedge clk);
          seed_valid = 2'b01;
          seed_core[0] = 5'(8+core);
          seed_addr[0] = 10'(word);
          seed_rows[0] = 32'hffff << 16*half;
          seed_payload[0] = initial_weights[32*core+word][1024*half+:1024];
          do @(posedge clk); while (!load_ready[0]);
        end
    @(negedge clk);
    seed_valid = 0;
    wait (staged_pending == 0);
    @(negedge clk);
    weight_init = 0;
    for (int core = 0; core < 4; core++) begin
      for (int tile"""),
        ("((serial || single_port) ? concurrent_writes != 0 : concurrent_writes == 0))",
         """(serial ? concurrent_writes != 0 : concurrent_writes == 0) ||
        physical_reads != reads || physical_writes != staged_writes)"""),
        ("""    $display("COMPILED_CLUSTER_WEIGHT_MODE single_port=%0d hold_issue=%0d",
             single_port, hold_issue_cycles);""",
         """    $display("COMPILED_CLUSTER_WEIGHT_PHASE hold_issue=%0d physical_reads=%0d physical_writes=%0d",
             hold_issue_cycles, physical_reads, physical_writes);"""),
        ("""    $fatal(1, "COMPILED_CLUSTER_WEIGHT_TIMEOUT reads=%0d retired=%0d writes=%0d",
           reads, retired, staged_writes);""",
         """    $display("CLUSTER_WEIGHT_TIMEOUT_FLOW requests=%0d,%0d pending=%b allowed=%b load=%b done=%b error=%b phase=%0d,%0d",
             request_count[0], request_count[1], staged_pending, write_allowed, load_valid,
             transport_done, transport_error, physical_reads, physical_writes);
    $fatal(1, "COMPILED_CLUSTER_WEIGHT_TIMEOUT reads=%0d retired=%0d writes=%0d",
           reads, retired, staged_writes);"""),
    ])


def expand_to_five_clusters(source):
    prior_phase_check = """  always @(posedge memory_clk) if (rst_n && (phase_ce_n != '1)) begin
    if (phase_we_n) begin
      if (!clk || phase_ce_n != 0) $fatal(1, "CLUSTER_WEIGHT_BAD_READ_PHASE");
      physical_reads++;
    end else begin
      if (clk) $fatal(1, "CLUSTER_WEIGHT_BAD_WRITE_PHASE");
      if (unread_words[phase_address])
        $fatal(1, "CLUSTER_WEIGHT_PHYSICAL_OVERWRITE word=%0d", phase_address);
      if (!weight_init) physical_writes++;
    end
  end"""
    phase_check = """  always @(posedge memory_clk) if (rst_n) begin
    int writes_this_edge;
    writes_this_edge = 0;
    for (int cluster = 0; cluster < 5; cluster++) begin
      if (phase_ce_n[cluster] != '1) begin
        if (phase_we_n[cluster]) begin
          if (!clk || phase_ce_n[cluster] != 0)
            $fatal(1, "CLUSTER_WEIGHT_BAD_READ_PHASE cluster=%0d", cluster);
          physical_reads++;
        end else begin
          if (clk) $fatal(1, "CLUSTER_WEIGHT_BAD_WRITE_PHASE cluster=%0d", cluster);
          if (unread_words[phase_address[cluster]])
            $fatal(1, "CLUSTER_WEIGHT_PHYSICAL_OVERWRITE cluster=%0d word=%0d",
                   cluster, phase_address[cluster]);
          if (!weight_init) begin
            physical_writes++;
            writes_this_edge++;
            cluster_writes[cluster]++;
          end
        end
      end
    end
    if (writes_this_edge == 2) parallel_writes++;
    if (writes_this_edge > 2) $fatal(1, "CLUSTER_WEIGHT_DUPLICATE_WRITE");
  end"""
    return edit(source, [
        ("  logic [3:0] phase_read_cores;", "  logic [4:0][3:0] phase_read_cores;"),
        ("  logic [4:0] phase_address;", "  logic [4:0][4:0] phase_address;"),
        ("  logic [63:0] phase_ce_n;", "  logic [4:0][63:0] phase_ce_n;"),
        ("  logic phase_we_n;", "  logic [4:0] phase_we_n;"),
        ("  logic [31:0] phase_rows;", "  logic [4:0][31:0] phase_rows;"),
        ("  logic [2047:0] phase_data;", "  logic [4:0][2047:0] phase_data;"),
        ("  int physical_reads = 0, physical_writes = 0;",
         "  int physical_reads = 0, physical_writes = 0, parallel_writes = 0, cluster_writes[5];"),
        ("initial_weights[128]", "initial_weights[640]"),
        ("logic [1023:0] expected[1024]", "logic [5119:0] expected[1024]"),
        ("  logic cluster_load_valid, cluster_load_error, cluster_cmd_ready, cluster_out_valid;",
         "  logic cluster_load_valid;\n  logic [4:0] cluster_load_error, cluster_cmd_ready, cluster_out_valid;"),
        ("  logic [1:0] init_core = '0, init_kind = '0;",
         "  logic [4:0] init_core = '0;\n  logic [1:0] init_kind = '0;"),
        ("  logic [1023:0] cluster_out_data;", "  logic [4:0][1023:0] cluster_out_data;"),
        ("  logic [3:0] cluster_out_slot;", "  logic [4:0][3:0] cluster_out_slot;"),
        (".cfg_count(8'd96), .cfg_tile_start(8'd32), .cfg_keep(160'hffff_ffff << 64)",
         ".cfg_count(8'd160), .cfg_tile_start(8'd32), .cfg_keep('1)"),
        ("assign cluster_load_core = init_core;", "assign cluster_load_core = init_core[1:0];"),
        ("  tri_oracle_cluster_weight_phase #(.CLUSTER_ID(3'd2)) weight_port (",
         "  tri_oracle_weight_phase_fabric weight_port ("),
        (prior_phase_check, phase_check),
        ("assign cmd_ready = allow_issue && cluster_cmd_ready;", "assign cmd_ready = allow_issue && (&cluster_cmd_ready);"),
        (""".backend_out_valid({5{cluster_out_valid}}), .backend_out_ready,
    .backend_out_output({5{cluster_out_slot}}), .backend_out_data({4096'b0, cluster_out_data})""",
         """.backend_out_valid(cluster_out_valid), .backend_out_ready,
    .backend_out_output(cluster_out_slot), .backend_out_data(cluster_out_data)"""),
        ("""  tri_oracle_sram_compute_cluster cluster (
    .clk, .memory_clk, .phase_address, .phase_ce_n, .phase_we_n,
    .phase_rows, .phase_data, .phase_read_cores, .rst_n(projection_rst_n), .load_valid(cluster_load_valid), .load_core(cluster_load_core),""",
         """  for (genvar c = 0; c < 5; c++) begin : clusters
    tri_oracle_sram_compute_cluster cluster (
    .clk, .memory_clk, .phase_address(phase_address[c]), .phase_ce_n(phase_ce_n[c]),
    .phase_we_n(phase_we_n[c]), .phase_rows(phase_rows[c]), .phase_data(phase_data[c]),
    .phase_read_cores(phase_read_cores[c]), .rst_n(projection_rst_n),
    .load_valid(cluster_load_valid && init_core[4:2]==3'(c)), .load_core(cluster_load_core),"""),
        (""".load_row_enable(cluster_load_rows), .load_error(cluster_load_error),
    .cmd_valid(allow_issue && cmd_valid), .cmd_ready(cluster_cmd_ready),""",
         """.load_row_enable(cluster_load_rows), .load_error(cluster_load_error[c]),
    .cmd_valid(cmd_accepted), .cmd_ready(cluster_cmd_ready[c]),"""),
        ("""    .out_valid(cluster_out_valid), .out_ready(backend_out_ready[0]),
    .out_output(cluster_out_slot), .out_data(cluster_out_data),""",
         """    .out_valid(cluster_out_valid[c]), .out_ready(backend_out_ready[c]),
    .out_output(cluster_out_slot[c]), .out_data(cluster_out_data[c]),"""),
        ("""    .strip_rst_n(rst_n), .strip_request('0), .strip_response(), .head_request('0), .head_response()
  );""", """    .strip_rst_n(rst_n), .strip_request('0), .strip_response(), .head_request('0), .head_response()
    );
  end"""),
        ("if (cluster_load_error ||", "if ((|cluster_load_error) ||"),
        ("|| (&staged_valid) ||", "|| ((&staged_valid) && staged_core[0][4:2]==staged_core[1][4:2]) ||"),
        ("staged_core[lane] < 8 || staged_core[lane] > 11", "staged_core[lane] >= 20"),
        ("if (cluster_out_valid && backend_out_ready[0]) begin",
         "if ((&cluster_out_valid) && (&backend_out_ready)) begin"),
        ("cluster_out_slot !== 4'(retired%16)", "cluster_out_slot !== {5{4'(retired%16)}}"),
        ("for (int row = 0; row < 32 && retired", "for (int row = 0; row < 160 && retired"),
        ("if (cluster_out_data[32*row+:32] !==", "if (cluster_out_data[row/32][32*(row%32)+:32] !=="),
        ("retired, row, cluster_out_data[32*row+:32],", "retired, row, cluster_out_data[row/32][32*(row%32)+:32],"),
        ("out_data[1023:0] !== expected", "out_data !== expected"),
        ("init_core = 2'(core);", "init_core = 5'(core);"),
        ("    for (int core = 0; core < 4; core++)\n", "    for (int core = 0; core < 20; core++)\n"),
        ("seed_core[0] = 5'(8+core);", "seed_core[0] = 5'(core);"),
        ("    for (int core = 0; core < 4; core++) begin", "    for (int core = 0; core < 20; core++) begin"),
        ("*4+core]", "*4+core%4]"),
        ("staged_writes != 256", "staged_writes != 1280"),
        ("physical_reads != reads", "physical_reads != 5*reads || parallel_writes == 0"),
        ("32*retired, 32*final_outputs", "160*retired, 160*final_outputs"),
        ("""    $display("COMPILED_CLUSTER_WEIGHT_FLOW out_stall=%0d requests=%0d,%0d",
             output_stall_cycles, request_count[0], request_count[1]);""",
         """    foreach (cluster_writes[c])
      if (cluster_writes[c] != 256) $fatal(1, "CLUSTER_WEIGHT_CLUSTER_WRITES cluster=%0d", c);
    $display("COMPILED_CLUSTER_WEIGHT_FLOW out_stall=%0d requests=%0d,%0d",
             output_stall_cycles, request_count[0], request_count[1]);
    $display("COMPILED_CLUSTER_WEIGHT_FABRIC clusters=5 cores=20 dual_cluster_writes=%0d",
             parallel_writes);"""),
    ])


def prepare_mapped_fabric_adapter(source):
    # Genus writes a separate escaped Verilog port for each outer packed index.
    header = source.split("\n);\n", 1)[0] + "\n);\n"
    header = edit(header, [("module tri_oracle_weight_phase_fabric (",
                            "module tri_oracle_weight_phase_fabric_adapter (")])
    ports = {
        "read_cores": 5, "write_core": 2, "write_address": 2, "write_rows": 2, "write_payload": 2,
        "memory_address": 5, "memory_ce_n": 5, "memory_rows": 5, "memory_data": 5,
    }
    connections = "".join(
        f"    .\\{port}[{index}] ({port}[{index}]),\n"
        for port, count in ports.items() for index in range(count)
    )
    return (header + "  tri_oracle_weight_phase_fabric implementation (\n"
            + connections + "    .*\n  );\nendmodule\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("core", "cluster", "macro", "output"):
        parser.add_argument(name, type=Path)
    parser.add_argument("--all-clusters", action="store_true")
    parser.add_argument("--mapped-fabric", action="store_true")
    args = parser.parse_args()
    if args.mapped_fabric and not args.all_clusters:
        parser.error("the mapped controller requires the five-cluster fixture")
    macro = args.macro.read_text(encoding="latin-1")
    if macro.count(f"module {TS5_MACRO} (") != 1 or "`ifdef UNIT_DELAY" not in macro:
        parser.error("expected the original compiler weight memory model")
    macro = macro.replace(TS5_MACRO, TIMED_MACRO).replace("`ifdef UNIT_DELAY",
                                                          "`ifdef TRI_ORACLE_WEIGHT_UNIT_DELAY")
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "weight_timed.v").write_text(macro, encoding="latin-1")
    bench = prepare_bench((ROOT / "verilog/tri_oracle_compiled_cluster_weight_overlap_tb.sv").read_text())
    if args.all_clusters:
        bench = expand_to_five_clusters(bench)
    if args.mapped_fabric:
        bench = edit(bench, [("tri_oracle_weight_phase_fabric weight_port (",
                             "tri_oracle_weight_phase_fabric_adapter weight_port (")])
        fabric = ROOT / "verilog/tri_oracle_weight_phase_fabric.sv"
        (args.output / "mapped_fabric_adapter.sv").write_text(prepare_mapped_fabric_adapter(fabric.read_text()))
    for path, source in (
        ("core.sv", prepare_core(args.core.read_text())),
        ("cluster.sv", prepare_cluster(args.cluster.read_text())),
        ("bench.sv", bench),
    ):
        (args.output / path).write_text(source)


if __name__ == "__main__":
    main()
