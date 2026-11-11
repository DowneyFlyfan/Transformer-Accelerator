"""Build an attention replay with score tiles executed in the head's cluster."""

import argparse
import json
from pathlib import Path
import re

from prepare_tri_oracle_wac_softmax_layer import ROOT, edit, read, sha, verify

MONITOR = """`timescale 1ns/1ps
module tri_oracle_cluster_local_score_probe (
    input logic clk, rst_n, cfg_valid, cfg_ready, local_scores, load_valid,
    input logic backend_cmd_valid, backend_cmd_ready,
    input logic [7:0] cfg_count,
    input logic [4:0] load_core, backend_clusters,
    input logic [2:0] score_cluster,
    input tri_oracle_wac_softmax_types::request_t softmax_request
);
    int tiles=0, keys=0, commands=0;
    always @(posedge clk) if (rst_n) begin
        if (cfg_valid && cfg_ready && softmax_request.score_tile) begin
            if (cfg_count == 0 || cfg_count > 32) $fatal(1, "SCORE_TILE_CAPACITY");
            tiles++;
            keys += int'(cfg_count);
        end
        if (local_scores && load_valid && load_core[4:2] != score_cluster)
            $fatal(1, "SCORE_TILE_REMOTE_LOAD");
        if (local_scores && backend_cmd_valid && backend_cmd_ready) begin
            if (backend_clusters !== (5'b1 << score_cluster)) $fatal(1, "SCORE_TILE_REMOTE_ISSUE");
            commands++;
        end
    end
    final $display("SCORE_CLUSTER_TOTAL %m tiles=%0d keys=%0d commands=%0d", tiles, keys, commands);
endmodule
bind tri_oracle_batched_tensor390 tri_oracle_cluster_local_score_probe score_cluster_probe (.*);
"""


def projection(text):
    text = edit(text, "  input logic [5:0] in_strips,", "  input logic [5:0] in_strips,\n  input logic [4:0] in_clusters,")
    text = edit(text, "  logic context_valid;", "  logic context_valid;\n  logic [4:0] clusters, context_clusters;")
    text = edit(text, "invalid_config=in_tokens==0", "invalid_config=in_clusters==0 || in_tokens==0")
    text = edit(text, "in_mask_base!=context_mask_base || in_activation_stride!=context_stride",
                "in_mask_base!=context_mask_base || in_activation_stride!=context_stride || in_clusters!=context_clusters")
    text = edit(text, "all_results=&backend_out_valid;", "all_results=(backend_out_valid & clusters)==clusters;")
    text = edit(text, "if(state==RUN && all_results && backend_out_output", "if(state==RUN && all_results && clusters[cluster] && backend_out_output")
    text = edit(text, "backend_out_ready={5{", "backend_out_ready=clusters & {5{")
    text = edit(text, "accept_result=all_results && (&backend_out_ready);", "accept_result=all_results && ((backend_out_ready & clusters)==clusters);")
    text = edit(text, "      context_valid<=0;context_tag", "      clusters<=0;context_clusters<=0;\n      context_valid<=0;context_tag")
    text = edit(text, "        tag<=in_tag;", "        clusters<=in_clusters;tag<=in_tag;")
    return edit(text, "            context_valid<=1;context_tag", "            context_clusters<=in_clusters;context_valid<=1;context_tag")


def tensor(text):
    anchor = "  logic [5119:0] backend_out_data;"
    text = edit(text, anchor, anchor + """
  logic local_scores;
  logic [2:0] score_cluster, first_cluster, last_cluster;
  logic [4:0] first_core, last_core, backend_clusters;
  logic [5119:0] sequence_data;

  assign first_cluster = local_scores ? score_cluster : 3'd0;
  assign last_cluster = local_scores ? score_cluster : 3'd4;
  assign first_core = {first_cluster, 2'b00};
  assign last_core = {last_cluster, 2'b11};
  assign backend_clusters = local_scores ? 5'b1 << score_cluster : 5'b11111;
  assign out_data = local_scores ? {4096'b0, sequence_data[1024*int'(score_cluster)+:1024]} : sequence_data;
""")
    text = edit(text, ".in_strips(tile_words),", ".in_strips(tile_words),.in_clusters(backend_clusters),")
    text = edit(text, ".out_data(out_data),", ".out_data(sequence_data),")
    text = edit(text, ".activation_reloaded(state==EXECUTE && sequence_ready)",
                ".activation_reloaded(state==EXECUTE && sequence_ready ? backend_clusters : '0)")
    text = edit(text, ".cmd_clusters(5'b11111)", ".cmd_clusters(backend_clusters)")
    text = edit(text, "    tile_words=", "    invalid_config=invalid_config || (softmax_request.score_tile &&\n"
                "      (cfg_paired || cfg_count>32 || cfg_tokens!=1 || softmax_request.owner>=20));\n    tile_words=")
    text = edit(text, "int'(weight_core/4)*32+int'(weight_row)", "(local_scores ? 0 : int'(weight_core/4)*32)+int'(weight_row)")
    text = edit(text, "int'(mask_core/4)*32+row", "(local_scores ? 0 : int'(mask_core/4)*32)+row")
    text = edit(text, "    if(!rst_n)begin\n      state<=IDLE", "    if(!rst_n)begin\n      local_scores<=0;score_cluster<=0;\n      state<=IDLE")
    text = edit(text, "        IDLE:if(cfg_valid)begin", "        IDLE:if(cfg_valid)begin\n"
                "          local_scores<=softmax_request.score_tile;score_cluster<=softmax_request.owner[4:2];")
    text = edit(text, "          validate_column<=0;mask_core<=0;", "          validate_column<=0;\n"
                "          mask_core<=softmax_request.score_tile ? {softmax_request.owner[4:2],2'b00} : 5'd0;")
    text = edit(text, "if(mask_core==19)", "if(mask_core==last_core)")
    text = edit(text, "if(weight_core==19)", "if(weight_core==last_core)", 3)
    text = edit(text, "activation_buffer<=rsp_data;broadcast_cluster<=0;", "activation_buffer<=rsp_data;broadcast_cluster<=first_cluster;")
    text = edit(text, "if(broadcast_cluster==4)", "if(broadcast_cluster==last_cluster)")
    text = edit(text, "activation_mode<=0;weight_core<=0;clear_word", "activation_mode<=0;weight_core<=first_core;clear_word")
    text = edit(text, "begin weight_core<=0;weight_row<=0;chunk_word<=0;state<=WEIGHT_SELECT;end",
                "begin weight_core<=first_core;weight_row<=0;chunk_word<=0;state<=WEIGHT_SELECT;end")
    return text


def fabric(text):
    text = edit(text, "input logic activation_reloaded,", "input logic [4:0] activation_reloaded,")
    return edit(text, ".activation_reloaded,", ".activation_reloaded(activation_reloaded[cluster]),")


def row(text):
    text = edit(text, "owner: row_owner, cfg_valid:", "owner: row_owner, score_tile: state == SubmitTile, cfg_valid:")
    return edit(text, "lane == 8'd159", "lane == 8'd31")


def prepare(output):
    baseline = ROOT / ".cache/physical/wac_layer_owned19"
    proof_path = baseline / "xcelium/wac_layer_qualification.json"
    previous = read(proof_path)
    assert previous["state"] == "twenty_core_layer_replayed_with_head_owned_softmax"
    inputs = previous["input_sha256"].copy()
    verify(inputs)
    setup_path = baseline / "receipt.json"
    setup = read(setup_path)
    assert setup["exercised_head"] == 19
    assert inputs[str(setup_path)] == sha(setup_path)
    changes = {
        "wac_softmax_types.sv": lambda text: edit(text, "logic [4:0] owner;", "logic [4:0] owner;\n        logic score_tile;"),
        "tri_oracle_attention_row426.sv": row,
        "tri_oracle_batched_projection356.sv": projection,
        "tri_oracle_batched_tensor390.sv": tensor,
        "tri_oracle_compute_fabric.sv": fabric,
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
    monitor = output / "score_cluster_probe.sv"
    monitor.write_text(MONITOR)
    body = re.sub(r'(?m)^`include "([^"]+)"$', rewrite, (baseline / "bundle.sv").read_text())
    assert not changes and len(generated) == 5
    bundle.write_text(body + f'`include "{monitor}"\n')
    inputs.update({str(path): sha(path) for path in (proof_path, Path(__file__), bundle, monitor, *generated)})
    verify(inputs)
    setup.update(bundle=str(bundle), input_sha256=inputs, score_tiles="one_head_cluster")
    (output / "receipt.json").write_text(json.dumps(setup, indent=2) + "\n")
    print("Prepared cluster-local attention score tiles on the existing twenty-core layer.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    prepare(parser.parse_args().output.resolve())
