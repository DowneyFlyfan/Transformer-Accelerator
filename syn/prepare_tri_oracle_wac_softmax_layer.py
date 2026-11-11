"""Route attention rows through the existing classifier's core assignment."""

import argparse
import json
from pathlib import Path
import re
import sys

from prepare_tri_oracle_wac_shared_imem import TOP as CORE, core_source
from run_tri_oracle_wac_softmax_imem import ADAPTER, ROOT, RTL, source

NATIVE = ROOT / ".cache/physical/shared437/aggregator_local_merge/cluster_native"
PARENT = NATIVE / "partitioned_parent"
sys.path[:0] = [str(PARENT), str(NATIVE)]
from prepare_parent_boundary_probe import probe_text
from run_separate_cores_fixture_export_at_reserve import read, sha, verify

TYPE = "tri_oracle_wac_softmax_types"
REQUEST = f"{TYPE}::request_t"
RESPONSE = f"{TYPE}::response_t"
LINK = ".softmax_request, .softmax_response,"
THROUGH = ".token_sizes_request, .token_sizes_response,"
ACK = ".activation_reloaded,"
PACKAGE = f"""package {TYPE};
    typedef struct packed {{
        logic [4:0] owner;
        logic cfg_valid;
        logic [10:0] cfg_length;
        logic in_valid;
        logic signed [15:0] score;
        logic [9:0] size;
        logic out_ready;
    }} request_t;
    typedef struct packed {{
        logic cfg_ready, cfg_error, in_ready, out_valid, out_last;
        logic [15:0] probability;
    }} response_t;
    function automatic logic [4:0] core_owner(input logic [4:0] head);
        return head >= 5'd20 ? head - 5'd20 : head;
    endfunction
endpackage
"""
MONITOR = """`timescale 1ns/1ps
module tri_oracle_wac_softmax_route_probe (
    input logic clk, rst_n, cfg_valid, cfg_ready, in_valid, in_ready, out_valid, out_ready
);
    int rows=0, scores=0, probabilities=0;
    always @(posedge clk) if (rst_n) begin
        if (cfg_valid && cfg_ready) rows++;
        if (in_valid && in_ready) scores++;
        if (out_valid && out_ready) probabilities++;
    end
    final $display("WAC_ROW_ROUTE %m rows=%0d scores=%0d probabilities=%0d", rows, scores, probabilities);
endmodule
bind tri_oracle_wac_softmax tri_oracle_wac_softmax_route_probe row_route_probe (.*);
"""


def edit(text, old, new, count=1):
    assert text.count(old) == count, (old, text.count(old), count)
    return text.replace(old, new)


def ports(text, anchor, producer=False, reload=False, count=1):
    request, response = ("output", "input") if producer else ("input", "output")
    prefix = f"{request} {REQUEST} softmax_request,\n  {response} {RESPONSE} softmax_response,\n  "
    if reload:
        prefix += "input logic activation_reloaded,\n  "
    return edit(text, anchor, prefix + anchor, count)


def row(text):
    text = edit(text, "    input logic row_streaming,", "    input logic row_streaming,\n    input logic [4:0] row_head,")
    text = edit(text, "    logic [31:0] tag;", "    logic [31:0] tag;\n    logic [4:0] row_owner;")
    text = edit(text, "            tag <= 0;", "            tag <= 0;\n            row_owner <= '0;")
    text = edit(text, "                    tag <= row_tag;",
                f"                    tag <= row_tag;\n                    row_owner <= {TYPE}::core_owner(row_head);")
    start = text.index("    tri_oracle_proportional_softmax normalize (")
    end = text.index("\n    );", start) + len("\n    );")
    text = text[:start] + """    assign softmax_request = '{
        owner: row_owner, cfg_valid: state == ConfigureSoftmax, cfg_length: selected,
        in_valid: state == SendScores, score: scores[cursor[9:0]], size: selected_size,
        out_ready: state == ReceiveProbability || state == DiscardProbabilities
    };
    assign norm_cfg_ready = softmax_response.cfg_ready;
    assign norm_in_ready = softmax_response.in_ready;
    assign norm_out_valid = softmax_response.out_valid;
    assign norm_out_last = softmax_response.out_last;
    assign norm_probability = softmax_response.probability;""" + text[end:]
    return edit(text, "            SendScores: if (norm_in_ready) begin",
                "            SendScores: if (softmax_response.cfg_error) state <= Failed;\n"
                "                        else if (norm_in_ready) begin")


def cluster(text):
    anchor = "input tri_oracle_merge_range_types::range_command_t merge_range_command,"
    text = ports(text, anchor, reload=True, count=2)
    text = ports(text, "input logic [394:0] head_request,", reload=True)
    local = f"""  logic [3:0] core_load_ready;
  {REQUEST} [3:0] core_softmax_requests;
  {RESPONSE} [3:0] core_softmax_responses;
  for (genvar core=0; core<4; core++) begin : softmax_route
    assign core_softmax_requests[core] = softmax_request.owner[1:0]==2'(core) ? softmax_request : '0;
  end
  assign softmax_response = core_softmax_responses[softmax_request.owner[1:0]];

"""
    text = edit(text, "  logic [3:0] ready, done,", local + "  logic [3:0] ready, done,")
    text = edit(text, "    load_error = |load_errors;", "    load_error = (|load_errors) || (load_valid && !core_load_ready[load_core]);")
    text = edit(text, "    .head_request(core_head_requests), .head_response(core_head_responses),",
                "    .head_request(core_head_requests), .head_response(core_head_responses),\n"
                "    .softmax_request(core_softmax_requests), .softmax_response(core_softmax_responses),\n"
                "    .activation_reloaded, .load_ready(core_load_ready),")
    before, module, core_text = text.partition("module tri_oracle_sram_strip_core448")
    assert module
    text = before + module + edit(core_text, "  output logic load_error,",
                                  "  output logic load_error,\n  output logic load_ready,")
    core = """    tri_oracle_sram_memory_compute compute (
        .softmax_cfg_valid(softmax_request.cfg_valid), .softmax_cfg_length(softmax_request.cfg_length),
        .softmax_cfg_ready(softmax_response.cfg_ready), .softmax_cfg_error(softmax_response.cfg_error),
        .softmax_in_valid(softmax_request.in_valid), .softmax_in_ready(softmax_response.in_ready),
        .softmax_in_score(softmax_request.score), .softmax_in_size(softmax_request.size),
        .softmax_out_ready(softmax_request.out_ready), .softmax_out_valid(softmax_response.out_valid),
        .softmax_out_last(softmax_response.out_last), .softmax_out_probability(softmax_response.probability),
        .activation_reload_required(), .*
    );"""
    return edit(text, "    tri_oracle_sram_memory_compute compute (.*);", core)


def reroute(name, text):
    producer = {"tri_oracle_attention_row426.sv", "tri_oracle_attention_layer427.sv", "tri_oracle_attention_pipeline430.sv"}
    consumer = {"tri_oracle_batched_learned406.sv", "tri_oracle_batched_frame393.sv",
                "tri_oracle_batched_shared392.sv", "tri_oracle_batched_tensor390.sv"}
    if name in producer:
        text = ports(text, "output tri_oracle_token_size_types::request_t token_sizes_request,", producer=True)
        if name == "tri_oracle_attention_row426.sv":
            return row(text)
        text = edit(text, THROUGH, THROUGH + " " + LINK)
        return edit(text, ".row_tag, .row_position,", ".row_head, .row_tag, .row_position,") if "layer427" in name else text
    if name in consumer:
        text = ports(text, "input tri_oracle_token_size_types::request_t token_sizes_request,")
        text = edit(text, THROUGH, THROUGH + " " + LINK)
        if name == "tri_oracle_batched_tensor390.sv":
            return edit(text, LINK, LINK + " .activation_reloaded(state==EXECUTE && sequence_ready),")
        if name in ("tri_oracle_batched_learned406.sv", "tri_oracle_batched_frame393.sv"):
            return edit(text, ".token_sizes_request('0), .token_sizes_response(),",
                        ".token_sizes_request('0), .token_sizes_response(), .softmax_request('0), .softmax_response(),")
        return text
    if name == "tri_oracle_shared_layer437.sv":
        text = edit(text, "    tri_oracle_token_size_types::request_t token_sizes_request;",
                    f"    {REQUEST} softmax_request;\n    {RESPONSE} softmax_response;\n"
                    "    tri_oracle_token_size_types::request_t token_sizes_request;")
        return edit(text, THROUGH, THROUGH + " " + LINK, 2)
    if name == "tri_oracle_compute_fabric.sv":
        text = ports(text, "input tri_oracle_token_size_types::request_t token_sizes_request,", reload=True)
        anchor = "    assign head_response ="
        text = edit(text, anchor, f"    wire [2:0] softmax_cluster = softmax_request.owner[4:2];\n"
                    f"    {RESPONSE} [4:0] cluster_softmax_responses;\n"
                    "    assign softmax_response = softmax_cluster<5 ? cluster_softmax_responses[softmax_cluster] : '0;\n"
                    + anchor)
        return edit(text, ".merge_range_command(range_commands[cluster]),",
                    ".softmax_request(softmax_cluster==3'(cluster) ? softmax_request : '0),\n"
                    "            .softmax_response(cluster_softmax_responses[cluster]), .activation_reloaded,\n"
                    "            .merge_range_command(range_commands[cluster]),")
    if name == "tri_oracle_sram_compute_cluster.sv":
        return cluster(text)
    if name == "wrappers.sv":
        text = ports(text, "input wire [376:0] merge_range_command,", reload=True, count=5)
        return edit(text, ".merge_range_command(merge_range_command),", LINK + " " + ACK + "\n    .merge_range_command(merge_range_command),", 5)
    if name == "cluster_adapter.sv":
        text = ports(text, "input tri_oracle_merge_range_types::range_command_t merge_range_command,", reload=True)
        for bank in (0, 1):
            text = edit(text, f"tri_oracle_native_cluster{bank}_mapped_replay{bank} block_instance",
                        f"tri_oracle_native_cluster{bank} block_instance")
        return text
    if name == "tri_oracle_attention_head_predictor415.sv":
        return edit(text, "cfg_head_id>=5'd20 ? cfg_head_id-5'd20 : cfg_head_id", f"{TYPE}::core_owner(cfg_head_id)")
    return None


def prepare(output):
    baseline = PARENT / "cluster_boundary_vendor_preflight"
    prep_path, replay_path = baseline / "receipt.json", baseline / "xcelium/receipt.json"
    prepared, prior = read(prep_path), read(replay_path)
    assert prior["state"] == "mapped_clusters_passed_integrated_attention_fixture"
    assert prepared["memory_models"] == "vendor" and prior["replay"]["native_exit_status"] == 0
    inputs = prior["input_sha256"].copy()
    verify(inputs)
    core_proof = ROOT / "records/wac_shared_imem_result.json"
    proof = read(core_proof)
    assert proof["state"] == "core_local_softmax_shares_weight_attention_core_input_memories"
    verify({str(ROOT / path): digest for path, digest in proof["source_evidence_sha256"].items()})
    output.mkdir()
    generated = []

    def write(name, text):
        path = output / name
        path.write_text(text)
        generated.append(path)
        return f'`include "{path}"\n'

    package = write("wac_softmax_types.sv", PACKAGE)
    monitor = write("wac_softmax_route_probe.sv", MONITOR)
    removed = {"cluster0.v", "cluster1.v", "shared_compute_core.v", "tcbn28hpcplusbwp12t40p140.v"}

    def rewrite(match):
        path = Path(match[1])
        if path.name in removed:
            return ""
        assert inputs[str(path)] == sha(path)
        if path.name == "tri_oracle_sram_memory_compute.sv":
            text = core_source(path.read_text())
            return write(path.name, edit(text, f"module {CORE} (", "module tri_oracle_sram_memory_compute ("))
        if path.name == "tri_oracle_proportional_softmax.sv":
            return write("tri_oracle_wac_softmax.sv", source(path.read_text()))
        if path.name == "bank_probe.sv":
            return write(path.name, probe_text([]))
        if path.name == "attention_tb.sv":
            text = edit(path.read_text(), "wire [4:0] head_id=0;", "wire [4:0] head_id=19;")
            text = edit(text, "wire [4:0] row_head=0;", "wire [4:0] row_head=head_id;")
            return write(path.name, edit(text, "head_done_id!==0", "head_done_id!==head_id"))
        text = reroute(path.name, path.read_text())
        return write(path.name, text) if text is not None else match[0]

    original = (baseline / "bundle.sv").read_text()
    body = re.sub(r'(?m)^`include "([^"]+)"\n', rewrite, original)
    assert len(generated) == 19, [path.name for path in generated]
    owner = RTL / "tri_oracle_wac_imem_owner.sv"
    bundle = output / "bundle.sv"
    bundle.write_text(package + body + f'`include "{owner}"\n`include "{ADAPTER}"\n' + monitor)
    inputs.update({str(path): sha(path) for path in (Path(__file__), core_proof, prep_path, replay_path,
                                                    owner, ADAPTER, bundle, *generated)})
    verify(inputs)
    prepared.update(bundle=str(bundle), input_sha256=inputs, mapped_banks=[], mapped_core_instances={},
                    linked_memory_inventory={}, softmax="head_owned_core_input_memory", exercised_head=19)
    (output / "receipt.json").write_text(json.dumps(prepared, indent=2) + "\n")
    print("Prepared source layer with head-owned softmax in all twenty cores.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    prepare(parser.parse_args().output.resolve())
