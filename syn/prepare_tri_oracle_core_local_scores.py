"""Build the single-core score path for attention rows that fit in one tile."""

import argparse
import json
from pathlib import Path
import re

from prepare_tri_oracle_wac_softmax_layer import ROOT, edit, read, sha, verify

MONITOR = """`timescale 1ns/1ps
module tri_oracle_core_local_score_probe (
    input logic clk, rst_n, cfg_valid, cfg_ready, single_core_scores, load_valid,
    input logic backend_cmd_valid, backend_cmd_ready,
    input logic [7:0] cfg_count,
    input logic [4:0] load_core, first_core,
    input tri_oracle_wac_softmax_types::request_t softmax_request
);
    int tiles=0, keys=0, commands=0;
    always @(posedge clk) if (rst_n) begin
        if (cfg_valid && cfg_ready && softmax_request.score_core) begin
            if (!softmax_request.score_tile || cfg_count == 0 || cfg_count > 32)
                $fatal(1, "SCORE_CORE_TILE_CAPACITY");
            tiles++;
            keys += int'(cfg_count);
        end
        if (single_core_scores && load_valid && load_core != first_core)
            $fatal(1, "SCORE_CORE_REMOTE_LOAD");
        if (single_core_scores && backend_cmd_valid && backend_cmd_ready) commands++;
    end
    final $display("SCORE_CORE_TOTAL %m tiles=%0d keys=%0d commands=%0d", tiles, keys, commands);
endmodule
bind tri_oracle_batched_tensor390 tri_oracle_core_local_score_probe score_core_probe (.*);

module tri_oracle_score_core_issue_probe (
    input logic clk, rst_n, issue, activation_reloaded,
    input logic [2:0] core_score_select,
    input logic [3:0] core_issue, core_activation_reloaded
);
    int issued=0;
    wire [3:0] selected = 4'b1 << core_score_select[1:0];
    always @(posedge clk) if (rst_n && core_score_select[2]) begin
        if (activation_reloaded && core_activation_reloaded !== selected)
            $fatal(1, "SCORE_CORE_REMOTE_RELOAD");
        if (issue) begin
            if (core_issue !== selected) $fatal(1, "SCORE_CORE_REMOTE_ISSUE");
            issued++;
        end
    end
    final $display("SCORE_CORE_ISSUE %m commands=%0d", issued);
endmodule
bind tri_oracle_sram_compute_cluster tri_oracle_score_core_issue_probe score_issue_probe (.*);
"""


def ports(text, count=1):
    return edit(text, "  input logic activation_reloaded,",
                "  input logic activation_reloaded,\n  input logic [2:0] core_score_select,", count)


def cluster(text):
    before, module, core = text.partition("module tri_oracle_sram_strip_core448")
    assert module
    text = ports(before, 2) + module + core
    anchor = "  logic output_forward, aggregate_web, aggregate_reb;"
    text = edit(text, anchor, anchor + """
  logic [3:0] active_cores, core_issue, core_read, core_activation_reloaded;
  logic [3:0] done_slot;
  logic [1:0] selected_core;
  assign selected_core = core_score_select[1:0];
  assign active_cores = core_score_select[2] ? 4'b1 << selected_core : 4'hf;
  assign core_issue = active_cores & {4{issue}};
  assign core_read = active_cores & {4{done_aligned}};
  assign core_activation_reloaded = active_cores & {4{activation_reloaded}};
  assign done_slot = done_slots[4*int'(core_score_select[2] ? selected_core : 2'd0)+:4];
""")
    text = edit(text, "cmd_ready = (&ready)", "cmd_ready = (&(ready | ~active_cores))")
    text = edit(text, "    done_aligned = (&done) &&", "    done_aligned = core_score_select[2] ? done[selected_core] : (&done) &&")
    text = edit(text, "aggregate_write = rst_n && (&result_valid);", "aggregate_write = rst_n && (&(result_valid | ~active_cores));")
    text = edit(text, "      reduced_words[row*32+:32] = reduce_four(",
                "      reduced_words[row*32+:32] = core_score_select[2] ? result_words[1024*int'(selected_core)+row*32+:32] : reduce_four(")
    text = edit(text, ".activation_reloaded, .load_ready(core_load_ready),", ".activation_reloaded(core_activation_reloaded), .load_ready(core_load_ready),")
    text = edit(text, ".cmd_valid(issue), .cmd_ready(ready),", ".cmd_valid(core_issue), .cmd_ready(ready),")
    text = edit(text, ".read_valid(done_aligned), .read_output(done_slots[3:0]),", ".read_valid(core_read), .read_output(done_slot),")
    return edit(text, "read_slot <= done_slots[3:0];", "read_slot <= done_slot;")


def tensor(text):
    text = edit(text, "  logic local_scores;", "  logic local_scores, single_core_scores;\n  logic [1:0] score_core, weight_part;")
    text = edit(text, "  assign first_core = {first_cluster, 2'b00};", "  assign first_core = {first_cluster, single_core_scores ? score_core : 2'b00};")
    text = edit(text, "  assign last_core = {last_cluster, 2'b11};", "  assign last_core = {last_cluster, single_core_scores ? score_core : 2'b11};\n"
                "  assign weight_part = single_core_scores ? 2'd0 : weight_core[1:0];")
    text = edit(text, ".cmd_clusters(backend_clusters),", ".cmd_clusters(backend_clusters), .core_score_select({single_core_scores, score_core}),")
    text = edit(text, "    tile_words=", "    invalid_config=invalid_config || (softmax_request.score_core &&\n"
                "      (!softmax_request.score_tile || cfg_feature_words>32));\n    tile_words=")
    text = edit(text, "int'(weight_core%4)", "int'(weight_part)", 4)
    text = edit(text, "65'(weight_core%4)", "65'(weight_part)")
    text = edit(text, "load_core=5'(broadcast_cluster)*5'd4+5'(activation_part);", "load_core=single_core_scores ? first_core : {broadcast_cluster, activation_part};")
    text = edit(text, "      local_scores<=0;score_cluster<=0;", "      local_scores<=0;score_cluster<=0;single_core_scores<=0;score_core<=0;")
    text = edit(text, "          local_scores<=softmax_request.score_tile;score_cluster<=softmax_request.owner[4:2];",
                "          local_scores<=softmax_request.score_tile;score_cluster<=softmax_request.owner[4:2];\n"
                "          single_core_scores<=softmax_request.score_core;score_core<=softmax_request.owner[1:0];")
    text = edit(text, "part_words<=8'(cfg_feature_words>>2);",
                "part_words<=8'(softmax_request.score_core ? cfg_feature_words : cfg_feature_words>>2);")
    text = edit(text, "{softmax_request.owner[4:2],2'b00} : 5'd0;", "{softmax_request.owner[4:2],\n"
                "              softmax_request.score_core ? softmax_request.owner[1:0] : 2'b00} : 5'd0;")
    return edit(text, "if(activation_part==3)", "if(single_core_scores || activation_part==3)")


def fabric(text):
    text = edit(text, "  input logic [4:0] activation_reloaded,",
                "  input logic [4:0] activation_reloaded,\n  input logic [2:0] core_score_select,")
    return edit(text, ".activation_reloaded(activation_reloaded[cluster]),", ".activation_reloaded(activation_reloaded[cluster]), .core_score_select,")


def wrappers(text):
    return edit(ports(text, 5), ".activation_reloaded,", ".activation_reloaded, .core_score_select,", 5)


def row(text):
    return edit(text, "score_tile: state == SubmitTile, cfg_valid:",
                "score_tile: state == SubmitTile, score_core: state == SubmitTile && selected <= 32, cfg_valid:")


def prepare(output):
    baseline = ROOT / ".cache/physical/wac_cluster_local_scores"
    proof_path = baseline / "xcelium/cluster_local_score_qualification.json"
    previous = read(proof_path)
    assert previous["state"] == "cluster_local_score_execution_replayed_with_core_local_softmax"
    inputs = previous["input_sha256"].copy()
    verify(inputs)
    setup_path = baseline / "receipt.json"
    setup = read(setup_path)
    assert setup["exercised_head"] == 19 and inputs[str(setup_path)] == sha(setup_path)
    changes = {
        "wac_softmax_types.sv": lambda text: edit(text, "logic score_tile;", "logic score_tile, score_core;"),
        "tri_oracle_attention_row426.sv": row,
        "tri_oracle_batched_tensor390.sv": tensor,
        "tri_oracle_compute_fabric.sv": fabric,
        "tri_oracle_sram_compute_cluster.sv": cluster,
        "cluster_adapter.sv": ports,
        "wrappers.sv": wrappers,
    }
    output.mkdir()
    generated = []

    def rewrite(match):
        path = Path(match[1])
        assert inputs[str(path)] == sha(path)
        transform = changes.pop(path.name, None)
        if transform is None:
            return match[0]
        target = output / path.name
        target.write_text(transform(path.read_text()))
        generated.append(target)
        return f'`include "{target}"'

    bundle = output / "bundle.sv"
    monitor = output / "score_core_probe.sv"
    monitor.write_text(MONITOR)
    body = re.sub(r'(?m)^`include "([^"]+)"$', rewrite, (baseline / "bundle.sv").read_text())
    assert not changes and len(generated) == 7
    bundle.write_text(body + f'`include "{monitor}"\n')
    inputs.update({str(path): sha(path) for path in (proof_path, Path(__file__), bundle, monitor, *generated)})
    verify(inputs)
    setup.update(bundle=str(bundle), input_sha256=inputs, score_tiles="single_core_or_head_cluster")
    (output / "receipt.json").write_text(json.dumps(setup, indent=2) + "\n")
    print("Prepared single-core score execution for rows that fit in one tile.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    prepare(parser.parse_args().output.resolve())
