"""Route pre-affine outlier and sign decisions to the weight-attention core SIMD."""

import argparse
import json
from pathlib import Path
import re

from prepare_tri_oracle_wac_softmax_layer import ROOT, RTL, TYPE, edit, read, sha, verify

BASELINE = ROOT / ".cache/physical/wac_head_offload_layer"
PORTS = """    input logic outlier_valid,
    input logic [127:0] metadata_values,
    output logic outlier_response_valid,
    output logic [7:0] outliers, negative,
"""


def package(text):
    text = edit(text, "        logic out_ready;", """        logic out_ready;
        logic outlier_valid;
        logic [127:0] normalized;""")
    return edit(text, "        logic [15:0] probability;", """        logic [15:0] probability;
        logic outlier_valid;
        logic [7:0] outliers, negative;""")


def normalizer(text):
    text = edit(text, "    output logic [533:0] strip_request,", f"""    output {TYPE}::request_t outlier_request,
    input {TYPE}::response_t outlier_response,
    output logic [533:0] strip_request,""")
    text = edit(text, "    logic [127:0] unused_norm_magnitudes;\n    logic [7:0] norm_outliers, norm_negative;", """    logic [127:0] normalized_q8;
    logic [4:0] metadata_owner;
    logic offer_metadata;""")
    text = edit(text, "(norm_bad || replay_failed || metadata_ready)",
                "(norm_bad || replay_failed || (metadata_ready && outlier_response.outlier_valid))")
    text = edit(text, """    for (genvar lane = 0; lane < 8; lane++) begin : signs
        assign norm_negative[lane] = unused_norm_magnitudes[16*lane + 15];
    end""", """    assign offer_metadata = state == Collect && norm_valid && !norm_bad && !replay_failed;
    assign outlier_request = '{owner: metadata_owner, outlier_valid: offer_metadata,
                               normalized: offer_metadata ? normalized_q8 : '0, default: '0};""")
    text = edit(text, ".out_norm_q8(unused_norm_magnitudes),\n        .out_outlier_mask(norm_outliers)",
                ".out_norm_q8(normalized_q8),\n        .out_outlier_mask()")
    text = edit(text, ".meta_valid(state == Collect && norm_valid && !norm_bad && !replay_failed)",
                ".meta_valid(offer_metadata && outlier_response.outlier_valid)")
    text = edit(text, ".meta_outliers(norm_outliers), .meta_negative(norm_negative),",
                ".meta_outliers(outlier_response.outliers), .meta_negative(outlier_response.negative),")
    text = edit(text, "            tag <= '0; epsilon", "            metadata_owner <= '0;\n            tag <= '0; epsilon")
    text = edit(text, "                tag <= cfg_tag; epsilon", "                metadata_owner <= '0;\n                tag <= cfg_tag; epsilon")
    return edit(text, "                        burst_words[burst_fill] <= activation_data;",
                "                        metadata_owner <= metadata_owner == 5'd19 ? 5'd0 : metadata_owner + 5'd1;\n"
                "                        burst_words[burst_fill] <= activation_data;")


def learned(text):
    text = edit(text, "    logic [533:0] strip_request;", f"""    {TYPE}::request_t outlier_request;
    {TYPE}::response_t simd_response;
    assign softmax_response = outlier_request.outlier_valid ? '0 : simd_response;
    logic [533:0] strip_request;""")
    text = edit(text, "        .strip_request, .strip_response,", "        .outlier_request, .outlier_response(simd_response),\n        .strip_request, .strip_response,")
    return edit(text, ".softmax_request, .softmax_response, .merge_request, .merge_response,",
                ".softmax_request(outlier_request.outlier_valid ? outlier_request : softmax_request),\n"
                "      .softmax_response(simd_response), .merge_request, .merge_response,")


def cluster(text):
    return edit(text, "        .activation_reload_required(), .*", """        .outlier_valid(softmax_request.outlier_valid), .metadata_values(softmax_request.normalized),
        .outlier_response_valid(softmax_response.outlier_valid),
        .outliers(softmax_response.outliers), .negative(softmax_response.negative),
        .activation_reload_required(), .*""")


def compute(text):
    text = edit(text, "  input logic softmax_cfg_valid,", PORTS + "  input logic softmax_cfg_valid,")
    return edit(text, "  tri_oracle_wac_softmax simd (", """  tri_oracle_wac_softmax simd (
    .outlier_valid, .metadata_values, .outlier_response_valid, .outliers, .negative,""")


def simd(text):
    text = edit(text, "    input  logic cfg_valid,", PORTS + "    input  logic cfg_valid,")
    return edit(text, "    localparam int MAX_KEYS = 1024;", """    tri_oracle_wac_outlier_sign metadata (
        .valid(outlier_valid), .normalized(metadata_values), .response_valid(outlier_response_valid), .outliers, .negative
    );

    localparam int MAX_KEYS = 1024;""")


def attention_row(text):
    return edit(text, "out_ready: state == ReceiveProbability || state == DiscardProbabilities\n",
                "out_ready: state == ReceiveProbability || state == DiscardProbabilities, default: '0\n")


def prepare(output):
    proof_path = BASELINE / "xcelium/head_offload_qualification.json"
    proof = read(proof_path)
    assert proof["state"] == "dynamic_head_offload_replayed_on_twenty_core_layer"
    inputs = proof["input_sha256"].copy()
    verify(inputs)
    setup_path = BASELINE / "receipt.json"
    setup = read(setup_path)
    assert inputs[str(setup_path)] == sha(setup_path)
    changes = {
        "wac_softmax_types.sv": package,
        "tri_oracle_batched_normalize405.sv": normalizer,
        "tri_oracle_batched_learned406.sv": learned,
        "tri_oracle_sram_compute_cluster.sv": cluster,
        "tri_oracle_sram_memory_compute.sv": compute,
        "tri_oracle_wac_softmax.sv": simd,
        "tri_oracle_attention_row426.sv": attention_row,
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
    metadata = RTL / "tri_oracle_wac_outlier_sign.sv"
    body = re.sub(r'(?m)^`include "([^"]+)"$', rewrite, (BASELINE / "bundle.sv").read_text())
    assert not changes
    bundle.write_text(body + f'`include "{metadata}"\n')
    inputs.update({str(path): sha(path) for path in (proof_path, Path(__file__), bundle, metadata, *generated)})
    verify(inputs)
    setup.update(bundle=str(bundle), input_sha256=inputs, outlier_owner="core_simd_round_robin")
    (output / "receipt.json").write_text(json.dumps(setup, indent=2) + "\n")
    print("Prepared core-local outlier and sign extraction in the twenty-core layer.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    prepare(parser.parse_args().output.resolve())
