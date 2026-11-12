"""Bind the packed reader and dual-port cache into a copy of the trained predictor."""

import argparse
from hashlib import file_digest
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PHYSICAL = ROOT / ".cache/physical"
ARCHIVE = PHYSICAL / "sign_word_cache_native/trained_masks"
CACHE = PHYSICAL / "dual_port_sign_line_cache"
SOURCE = PHYSICAL / "shared437/local_token_size_integrated/portable/tri_oracle_batched_outlier_replay404.sv"
BENCH = ROOT / "verilog/tri_oracle_sign_cache_trained_masks_tb.sv"


def sha(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def rewrite(text, replacements):
    for before, after in replacements:
        assert text.count(before) == 1, before
        text = text.replace(before, after)
    return text


def predictor(text):
    text = rewrite(text, (
        ("module tri_oracle_batched_outlier_replay404", "module tri_oracle_packed_outlier_replay"),
        ("cfg_gate_sign_base, cfg_up_sign_base", "cfg_sign_base"),
        ("logic [63:0] gate_base, up_base;", "logic [63:0] sign_base;"),
        ("logic [64:0] sign_span, unused_cfg_gate_end, unused_cfg_up_end;", "logic [64:0] sign_span, cfg_sign_end;"),
        ("sign_span = (65'(cfg_groups) * 65'(cfg_strips)) << 5;", "sign_span = (65'(cfg_groups) * 65'(cfg_strips)) << 6;"),
        ("unused_cfg_gate_end = {1'b0, cfg_gate_sign_base} + sign_span - 65'd1;\n"
         "        unused_cfg_up_end = {1'b0, cfg_up_sign_base} + sign_span - 65'd1;",
         "cfg_sign_end = {1'b0, cfg_sign_base} + sign_span - 65'd1;"),
        ("cfg_gate_sign_base[2:0] != 0 ||\n"
         "            cfg_up_sign_base[2:0] != 0 || unused_cfg_gate_end[64] || unused_cfg_up_end[64];",
         "cfg_sign_base[5:0] != 0 || cfg_sign_end[64];"),
        ("gate_base <= '0; up_base <= '0;", "sign_base <= '0;"),
        ("gate_base <= cfg_gate_sign_base; up_base <= cfg_up_sign_base;", "sign_base <= cfg_sign_base;"),
        ("output logic req_valid,\n    input logic req_ready,", "output logic [1:0] req_valid,\n    input logic [1:0] req_ready,"),
        ("output logic [4:0] req_length,\n    input logic rsp_valid,\n    output logic rsp_ready,\n"
         "    input logic rsp_last, rsp_error,\n    input logic [63:0] rsp_data,",
         "output logic [5:0] req_length,\n    input logic [1:0] rsp_valid,\n    output logic [1:0] rsp_ready,\n"
         "    input logic [1:0] rsp_last, rsp_error,\n    input logic [1:0][511:0] rsp_data,"),
        ("    tri_oracle_sign_fetch sign_memory (", """    logic cache_req_valid, cache_req_ready, cache_rsp_valid, cache_rsp_ready;
    logic cache_rsp_last, cache_rsp_error;
    logic [63:0] cache_req_address;
    logic [5:0] cache_req_length;
    logic [511:0] cache_rsp_data;

    tri_oracle_packed_sign_fetch sign_memory ("""),
        (".in_gate_base(gate_base), .in_up_base(up_base)", ".in_sign_base(sign_base)"),
        ("        .req_valid(req_valid), .req_ready(req_ready), .req_address(req_address),\n"
         "        .req_length(req_length), .rsp_valid(rsp_valid), .rsp_ready(rsp_ready),\n"
         "        .rsp_last(rsp_last), .rsp_error(rsp_error), .rsp_data(rsp_data)\n    );",
         """        .req_valid(cache_req_valid), .req_ready(cache_req_ready), .req_address(cache_req_address),
        .req_length(cache_req_length), .rsp_valid(cache_rsp_valid), .rsp_ready(cache_rsp_ready),
        .rsp_last(cache_rsp_last), .rsp_error(cache_rsp_error), .rsp_data(cache_rsp_data)
    );

    tri_oracle_dual_port_sign_line_cache sign_cache (
        .clk, .rst_n, .frame_start(cfg_valid && cfg_ready),
        .client_req_valid(cache_req_valid), .client_req_ready(cache_req_ready),
        .client_req_address(cache_req_address), .client_req_length(cache_req_length),
        .client_rsp_valid(cache_rsp_valid), .client_rsp_ready(cache_rsp_ready),
        .client_rsp_last(cache_rsp_last), .client_rsp_error(cache_rsp_error), .client_rsp_data(cache_rsp_data),
        .mem_req_valid(req_valid), .mem_req_ready(req_ready), .mem_req_address(req_address),
        .mem_req_length(req_length), .mem_rsp_valid(rsp_valid), .mem_rsp_ready(rsp_ready),
        .mem_rsp_last(rsp_last), .mem_rsp_error(rsp_error), .mem_rsp_data(rsp_data)
    );"""),
    ))
    assert "cfg_up_sign_base" not in text and "tri_oracle_sign_fetch sign_memory" not in text
    return text


def bench(text, counts):
    text = rewrite(text, (
        ("tri_oracle_sign_cache_trained_masks_tb", "tri_oracle_packed_sign_predictor_tb"),
        (", PAIRS = STRIPS * 4", ""),
        (", UP_BASE = 64'h0000000dffffff00", ""),
        ("localparam int EXPECTED_READS = 21824;", f"localparam int EXPECTED_READS = {counts['primary'] + counts['auxiliary']};"),
        ("logic req_valid, req_ready;", "logic [1:0] req_valid, req_ready;"),
        ("logic [4:0] req_length;", "logic [5:0] req_length;"),
        ("logic rsp_valid, rsp_ready;", "logic [1:0] rsp_valid, rsp_ready;"),
        ("logic [63:0] rsp_data;", "logic [1:0][511:0] rsp_data;"),
        ("logic [63:0] gate_signs [0:GROUPS*PAIRS-1], up_signs [0:GROUPS*PAIRS-1];", "logic [511:0] lines [GROUPS*STRIPS];"),
        ("logic [63:0] expected_addresses", "logic [65:0] expected_addresses"),
        ("logic pending = 0;", "logic [1:0] pending = 0;\n    int primary = 0, auxiliary = 0;"),
        ("tri_oracle_batched_outlier_replay404 #", "tri_oracle_packed_outlier_replay #"),
        (".cfg_gate_sign_base(GATE_BASE),\n        .cfg_up_sign_base(UP_BASE),", ".cfg_sign_base(GATE_BASE),"),
        (".rsp_last(1'b1), .rsp_error(1'b0)", ".rsp_last(2'b11), .rsp_error(2'b00)"),
        ("assign req_ready = !pending && cycle % 7 != 0;", "assign req_ready = {2{pending == 0 && cycle % 7 != 0}};"),
        ("string fixture, norm, addresses;", "string fixture, norm, addresses, packed_file;"),
        ('!$value$plusargs("ADDRESSES=%s", addresses))',
         '!$value$plusargs("ADDRESSES=%s", addresses) || !$value$plusargs("PACKED=%s", packed_file))'),
        ('        $readmemh({fixture, "/gate_sign.hex"}, gate_signs);\n'
         '        $readmemh({fixture, "/up_sign.hex"}, up_signs);', '        $readmemh(packed_file, lines);'),
        ("logical_reads != 55616 ||", f"logical_reads != {counts['requests']} || primary != {counts['primary']} ||\n"
         f"            auxiliary != {counts['auxiliary']} ||"),
        ("TRAINED_SIGN_CACHE_PASS groups=%0d bits_per_mask=32 skipped=%0d logical=%0d external=%0d cycles=%0d",
         "PACKED_SIGN_PREDICTOR_PASS groups=%0d bits_per_mask=32 skipped=%0d logical=%0d external=%0d cycles=%0d"),
    ))
    start = text.index("            if (req_valid && req_ready) begin")
    end = text.index("            if (dut.cache_req_valid", start)
    return text[:start] + """            if (|(req_valid & req_ready)) begin
                logic [1:0] granted;
                granted = req_valid & req_ready;
                if (reads >= EXPECTED_READS || req_length != 1 || req_address !== expected_addresses[reads][63:0] ||
                    granted !== expected_addresses[reads][65:64])
                    $fatal(1, "PACKED_SIGN_PREDICTOR_ADDRESS index=%0d address=%h lane=%b", reads, req_address, granted);
                index = int'((req_address - GATE_BASE) >> 6);
                if (granted[0]) begin
                    rsp_data[0] <= lines[index];
                    primary++;
                end else begin
                    rsp_data[1] <= lines[index];
                    auxiliary++;
                end
                pending <= granted;
                reads++;
            end else if (|(rsp_valid & rsp_ready)) pending <= 0;
""" + text[end:]


def run(output):
    reference = json.loads((ARCHIVE / "receipt.json").read_text())
    assert sha(SOURCE) == reference["input_sha256"][str(SOURCE.relative_to(ROOT))]
    assert sha(BENCH) == reference["input_sha256"][str(BENCH.relative_to(ROOT))]
    sequence = CACHE / "sequence_128.hex"
    counts_path = sequence.with_suffix(".json")
    counts = json.loads(counts_path.read_text())
    assert counts["entries"] == 128 and sha(sequence) == counts["request_sha256"]
    miss_words = [word for word in sequence.read_text().splitlines() if int(word, 16) >> 64]
    assert len(miss_words) == counts["primary"] + counts["auxiliary"]
    output.mkdir()
    updated_source, updated_bench, addresses = (output / name for name in (
        "tri_oracle_packed_outlier_replay.sv", "tri_oracle_packed_sign_predictor_tb.sv", "miss_addresses.hex"))
    updated_source.write_text(predictor(SOURCE.read_text()))
    updated_bench.write_text(bench(BENCH.read_text(), counts))
    addresses.write_text("\n".join(miss_words) + "\n")
    paths = (SOURCE, BENCH, sequence, counts_path, ARCHIVE / "receipt.json", Path(__file__).resolve(),
             updated_source, updated_bench, addresses)
    result = {"state": "packed_sign_predictor_trained_replay_prepared", "counts": counts,
              "input_sha256": {str(path.relative_to(ROOT)): sha(path) for path in paths}}
    (output / "prepared.json").write_text(json.dumps(result, indent=2) + "\n")
    print(result["state"], counts["requests"], len(miss_words))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=lambda path: Path(path).resolve())
    run(parser.parse_args().output)
