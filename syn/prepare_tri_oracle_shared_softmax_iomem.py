"""Connect cluster-resident softmax to the existing aggregator result memories."""

import argparse
import json
from pathlib import Path
import re
import sys

from run_tri_oracle_softmax_iomem import ROOT, RTL, bank_arithmetic, replace, sha

PARENT = ROOT / ".cache/physical/shared437/aggregator_local_merge/cluster_native/partitioned_parent"
sys.path[:0] = [str(PARENT), str(PARENT.parent)]
from prepare_mapped_parent_replay import collect_memory_models
from run_separate_cores_fixture_export_at_reserve import read, verify

OWNER_MONITOR = """
module tri_oracle_softmax_iomem_owner_probe (
    input logic clk, rst_n, reserve, softmax_grant, issue, aggregate_write, output_refill,
    input logic softmax_write_valid, softmax_read_valid
);
    int held, pending, compute_writes, compute_reads, softmax_writes, softmax_reads;
    always @(posedge clk) if (rst_n) begin
        if (softmax_grant && (issue || aggregate_write || output_refill))
            $fatal(1, "SOFTMAX_IOMEM_DOUBLE_OWNER %m");
        if (!softmax_grant && (softmax_write_valid || softmax_read_valid))
            $fatal(1, "SOFTMAX_IOMEM_ACCESS_WITHOUT_GRANT %m");
        if (reserve && issue)
            $fatal(1, "SOFTMAX_IOMEM_ACCEPTED_COMPUTE_DURING_RESERVE %m");
        if (softmax_grant) held++;
        if (reserve && !softmax_grant) pending++;
        if (aggregate_write) compute_writes++;
        if (output_refill && !softmax_grant) compute_reads++;
        if (softmax_write_valid) softmax_writes++;
        if (softmax_read_valid) softmax_reads++;
    end
    final $display("SOFTMAX_IOMEM_OWNER %m held=%0d pending=%0d cw=%0d cr=%0d sw=%0d sr=%0d",
                   held, pending, compute_writes, compute_reads, softmax_writes, softmax_reads);
endmodule
bind tri_oracle_sram_compute_cluster tri_oracle_softmax_iomem_owner_probe iomem_probe (
    .clk, .rst_n, .reserve(softmax_command.reserve), .softmax_grant,
    .issue, .aggregate_write, .output_refill, .softmax_write_valid, .softmax_read_valid
);
"""


def coordinator(text):
    text = replace(text, "    wire begin_row = state == IDLE && cfg_valid && valid_length;",
                   """    logic [BANKS-1:0] grants;
    wire reserve = state != IDLE || (cfg_valid && valid_length);
    wire begin_row = cfg_ready && cfg_valid && valid_length;""")
    text = replace(text, "assign cfg_ready = state == IDLE;",
                   "assign cfg_ready = state == IDLE && (!cfg_valid || !valid_length || (&grants));")
    text = replace(text, "IDLE: if (cfg_valid) begin", "IDLE: if (cfg_valid && cfg_ready) begin")
    text = replace(text, "            begin_row: begin_row, load: bank_load[bank],",
                   """            begin_row: begin_row, load: bank_load[bank],
            reserve: reserve, flush: state == REDUCE_MAX,""")
    return replace(text, "        assign bank_maximum[bank]", "        assign grants[bank] = softmax_response[bank].granted;\n"
                   "        assign bank_maximum[bank]")


def cluster(text):
    before = """  tri_oracle_softmax_bank #(.ENTRIES(MERGE_TABLE_START == 512 ? 204 : 205)) softmax_bank ("""
    after = """  logic softmax_grant, softmax_write_valid, softmax_read_valid;
  logic [5:0] softmax_write_line, softmax_read_line;
  logic [127:0] softmax_write_data;
  logic [1023:0] aggregate_q;
  assign softmax_response.granted = softmax_grant;
  tri_oracle_softmax_iomem_bank softmax_bank ("""
    text = replace(text, before, after)
    text = replace(text, "logic [1023:0] reduced_words, aggregate_q, forwarded_words;",
                   "logic [1023:0] reduced_words, forwarded_words;")
    text = replace(text, "    .probability(softmax_response.probability)",
                   """    .probability(softmax_response.probability), .flush(softmax_command.flush),
    .write_valid(softmax_write_valid), .read_valid(softmax_read_valid),
    .write_line(softmax_write_line), .read_line(softmax_read_line),
    .write_data(softmax_write_data), .memory_q(aggregate_q[511:0])""")
    text = replace(text, "  logic output_forward, aggregate_web, aggregate_reb;",
                   """  logic output_forward, aggregate_web, aggregate_reb;

  // Stop admitting compute work while existing results drain. The row
  // coordinator waits for every cluster's grant before sending any score.
  assign softmax_grant = rst_n && softmax_command.reserve && count == 0 && !out_valid;""")
    text = replace(text, "&& !reserved[cmd_output] && cmd_reduce != 3;",
                   "&& !reserved[cmd_output] && cmd_reduce != 3 && !softmax_command.reserve;")
    old = """  TS6N28HPCPSVTA16X128M2F aggregate_memory[7:0] (
    .CLKW(clk), .CLKR(clk), .WEB(aggregate_web), .REB(aggregate_reb),
    .AA(read_slot), .AB(next_output), .D(reduced_words), .Q(aggregate_q)
  );"""
    shared = """  logic [7:0] iomem_web, iomem_reb;
  logic [7:0][3:0] iomem_write_addr, iomem_read_addr;
  logic [7:0][127:0] iomem_data;
  for (genvar macro = 0; macro < 8; macro++) begin : result_memory_owner
    if (macro < 4) begin : softmax_addressable
      assign iomem_web[macro] = softmax_grant ?
          !(softmax_write_valid && softmax_write_line[5:4] == 2'(macro)) : aggregate_web;
      assign iomem_reb[macro] = softmax_grant ?
          !(softmax_read_valid && softmax_read_line[5:4] == 2'(macro)) : aggregate_reb;
      assign iomem_write_addr[macro] = softmax_grant ? softmax_write_line[3:0] : read_slot;
      assign iomem_read_addr[macro] = softmax_grant ? softmax_read_line[3:0] : next_output;
      assign iomem_data[macro] = softmax_grant ? softmax_write_data : reduced_words[macro*128+:128];
    end else begin : compute_only
      assign iomem_web[macro] = softmax_grant || aggregate_web;
      assign iomem_reb[macro] = softmax_grant || aggregate_reb;
      assign iomem_write_addr[macro] = read_slot;
      assign iomem_read_addr[macro] = next_output;
      assign iomem_data[macro] = reduced_words[macro*128+:128];
    end
  end
  TS6N28HPCPSVTA16X128M2F aggregate_memory[7:0] (
    .CLKW(clk), .CLKR(clk), .WEB(iomem_web), .REB(iomem_reb),
    .AA(iomem_write_addr), .AB(iomem_read_addr), .D(iomem_data), .Q(aggregate_q)
  );"""
    return replace(text, old, shared)


def prepare(output):
    source = PARENT / "cluster_resident_softmax_replay_complete_probe"
    old_prep = source / "receipt.json"
    prior = source / "xcelium/cluster_bank_qualification.json"
    prepared, proof = read(old_prep), read(prior)
    assert proof["state"] == "five_cluster_resident_softmax_banks_passed_integrated_xcelium"
    assert proof["replay"]["native_exit_status"] == 0 and prepared["mapped_banks"] == []
    inputs = proof["input_sha256"].copy()
    verify(inputs)
    vendor = collect_memory_models(inputs)
    assert len(vendor) == 6
    output.mkdir()
    generated = []

    def write(name, text):
        target = output / name
        target.write_text(text)
        generated.append(target)
        return f'`include "{target}"'

    def rewrite(match):
        path = Path(match[1])
        if path.name == "full_layer_views.sv":
            return "\n".join(f'`include "{model}"' for model in vendor)
        if path.name == "tri_oracle_softmax_bank.sv":
            bank = write("tri_oracle_softmax_iomem_bank.sv", bank_arithmetic())
            return f'`include "{RTL / "tri_oracle_softmax_iomem.sv"}"\n{bank}'
        if path.name == "tri_oracle_cluster_softmax_control.sv":
            return write(path.name, coordinator(path.read_text()))
        if path.name == "tri_oracle_sram_compute_cluster.sv":
            return write(path.name, cluster(path.read_text()))
        if path.name == "softmax_bank_types.sv":
            text = replace(path.read_text(), "logic begin_row, load, read_slot, write_weight;",
                           "logic begin_row, load, read_slot, write_weight, reserve, flush;")
            text = replace(text, "logic [15:0] probability;", "logic [15:0] probability;\n        logic granted;")
            return write(path.name, text)
        if path.name == "cluster_softmax_probe.sv":
            text = replace(path.read_text(), "bind tri_oracle_softmax_bank ", "bind tri_oracle_softmax_iomem_bank ")
            return write(path.name, text + OWNER_MONITOR)
        return match[0]

    original = (source / "bundle.sv").read_text()
    body = re.sub(r'(?m)^`include "([^"]+)"$', rewrite, original)
    assert len(generated) == 5 and body.count("`define UNIT_DELAY\n") == 1
    bundle = output / "bundle.sv"
    bundle.write_text("`define UNIT_DELAY\n" + body.replace("`define UNIT_DELAY\n", ""))
    assert "full_layer_views.sv" not in bundle.read_text()
    inputs.update({str(path): sha(path) for path in (
        Path(__file__), old_prep, prior, bundle, Path(__file__).with_name("run_tri_oracle_softmax_iomem.py"),
        RTL / "tri_oracle_softmax_iomem.sv", *generated,
    )})
    verify(inputs)
    prepared.update(bundle=str(bundle), input_sha256=inputs,
                    softmax="shared_aggregator_iomem", memory_models="vendor",
                    memory_model_paths=list(map(str, vendor)))
    (output / "receipt.json").write_text(json.dumps(prepared, indent=2) + "\n")
    print("Prepared cluster-resident softmax using the existing result memories.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    prepare(parser.parse_args().output.resolve())
