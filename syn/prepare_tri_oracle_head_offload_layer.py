"""Build an attention replay with scheduler-selected cluster and core owners."""

import argparse
import json
from pathlib import Path
import re

from prepare_tri_oracle_wac_softmax_layer import ROOT, RTL, edit, read, sha, verify

BASELINE = ROOT / ".cache/physical/wac_core_local_scores_verified"
MONITOR = """`timescale 1ns/1ps
module tri_oracle_offload_route_probe (
    input logic clk, rst_n, row_valid, row_ready, row_allowed, placement_ready,
    input logic [4:0] row_head, planned_cluster_owner, planned_core_owner
);
    always @(posedge clk) if (rst_n && row_valid && row_ready && row_allowed) begin
        if (!placement_ready) $fatal(1, "HEAD_OFFLOAD_ROW_BEFORE_MAP");
        $display("HEAD_OFFLOAD_ROW head=%0d cluster_owner=%0d core_owner=%0d", row_head, planned_cluster_owner, planned_core_owner);
    end
endmodule
bind tri_oracle_attention_layer427 tri_oracle_offload_route_probe offload_route_probe (.*);
"""


def layer(text):
    anchor = "    logic [31:0] known_heads, head_types;"
    text = edit(text, anchor, anchor + """
    logic placement_ready;
    logic [4:0] planned_cluster_owner, planned_core_owner;

    tri_oracle_head_offload placement (
        .clk, .rst_n, .known_heads, .streaming_heads(head_types), .lookup_head(row_head),
        .map_ready(placement_ready), .cluster_owner(planned_cluster_owner), .core_owner(planned_core_owner)
    );
""")
    for label in ("frame", "head", "restore"):
        state = f"{label.title()}Result"
        text = edit(text, f"assign {label}_done_valid = state=={state};",
                    f"assign {label}_done_valid = state=={state} && placement_ready;")
        text = edit(text, f"{state}: if ({label}_done_ready)", f"{state}: if ({label}_done_valid && {label}_done_ready)")
    text = edit(text, "(!row_allowed || native_row_ready);", "(!row_allowed || (native_row_ready && placement_ready));")
    return edit(text, ".row_head, .row_tag, .row_position,",
                ".row_cluster_owner(planned_cluster_owner), .row_core_owner(planned_core_owner), .row_tag, .row_position,")


def row(text):
    text = edit(text, "    input logic [4:0] row_head,", "    input logic [4:0] row_cluster_owner, row_core_owner,")
    text = edit(text, "    logic [4:0] row_owner;", """    logic [4:0] row_owner, saved_cluster_owner, saved_core_owner;
    wire [10:0] selected_keys = streaming && visible > SPARSE_KEYS ? SPARSE_KEYS : visible;""")
    text = edit(text, "            row_owner <= '0;",
                "            row_owner <= '0;\n            saved_cluster_owner <= '0;\n            saved_core_owner <= '0;")
    text = edit(text, "                    row_owner <= tri_oracle_wac_softmax_types::core_owner(row_head);",
                "                    saved_cluster_owner <= row_cluster_owner;\n                    saved_core_owner <= row_core_owner;")
    return edit(text, "                selected <= streaming && visible > SPARSE_KEYS ? SPARSE_KEYS : visible;",
                "                selected <= selected_keys;\n                row_owner <= selected_keys <= 32 ? saved_core_owner : saved_cluster_owner;")


def bench(text):
    text = edit(text, "wire [4:0] head_id=19;", "logic [4:0] head_id=0;")
    text = edit(text, "wire [4:0] row_head=head_id;", "wire [4:0] row_head=0;")
    text = edit(text, "wire [7:0] head_ratio_num=8,head_ratio_den=1;", "logic [7:0] head_ratio_num=8;\n    wire [7:0] head_ratio_den=1;")
    text = edit(text, "        int file, rank, position, image_start, shift;",
                "        int file, rank, position, image_start, shift, before_head_reads, head_read_beats;")
    return edit(text, "            predict();", """            if (expect_streaming != 0 || expect_recent <= 0) $fatal(1, "HEAD_OFFLOAD_CLASSIFIER_FIXTURE");
            before_head_reads = attention_reads;
            predict();
            head_read_beats = attention_reads - before_head_reads;
            if (head_read_beats == 0) $fatal(1, "HEAD_OFFLOAD_CLASSIFIER_NO_READS");
            before_head_reads = attention_reads;
            head_id = 20;
            predict();
            if (attention_reads - before_head_reads != head_read_beats) $fatal(1, "HEAD_OFFLOAD_RETRIEVAL_READS");
            before_head_reads = attention_reads;
            head_id = 8;
            head_ratio_num = 0;
            expect_streaming = 1;
            predict();
            if (attention_reads - before_head_reads != head_read_beats) $fatal(1, "HEAD_OFFLOAD_STREAMING_READS");
            $display("HEAD_OFFLOAD_REPLAY_CLASSIFICATION retrieval=2 streaming=1 read_beats_per_head=%0d", head_read_beats);""")


def prepare(output):
    proof_path = BASELINE / "xcelium/core_local_score_qualification.json"
    previous = read(proof_path)
    assert previous["state"] == "single_core_and_cluster_score_execution_replayed"
    inputs = previous["input_sha256"].copy()
    verify(inputs)
    setup_path = BASELINE / "receipt.json"
    setup = read(setup_path)
    assert inputs[str(setup_path)] == sha(setup_path)
    changes = {"tri_oracle_attention_layer427.sv": layer, "tri_oracle_attention_row426.sv": row, "attention_tb.sv": bench}
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
    planner = RTL / "tri_oracle_head_offload.sv"
    monitor = output / "head_offload_route_probe.sv"
    monitor.write_text(MONITOR)
    body = re.sub(r'(?m)^`include "([^"]+)"$', rewrite, (BASELINE / "bundle.sv").read_text())
    assert not changes and len(generated) == 3
    bundle.write_text(body + f'`include "{planner}"\n`include "{monitor}"\n')
    inputs.update({str(path): sha(path) for path in (proof_path, Path(__file__), bundle, monitor, planner, *generated)})
    verify(inputs)
    setup.update(bundle=str(bundle), input_sha256=inputs, exercised_head=0,
                 head_placement="retrieval_streaming_offload", expected_owner=8)
    (output / "receipt.json").write_text(json.dumps(setup, indent=2) + "\n")
    print("Prepared twenty-core replay with dynamic head reassignment.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    prepare(parser.parse_args().output.resolve())
