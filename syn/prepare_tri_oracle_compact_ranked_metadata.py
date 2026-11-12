"""Use five ternary-coded strips per memory word in the ranked predictor."""

import argparse
import json
from pathlib import Path

from prepare_tri_oracle_packed_sign_predictor import ROOT, rewrite, sha


WORK = ROOT / ".cache/physical/ranked_sign_slots"
SOURCE = WORK / "pipelined_32"
RTL = ROOT / "verilog"
PREDICTOR = "tri_oracle_packed_outlier_replay.sv"


def predictor(code):
    return rewrite(code, (
        ("""    logic [63:0] packed_word, next_word;
    logic mem_write, mem_read;
    logic [8:0] word_address;
    logic [63:0] lower_q, upper_q, selected_word;""", """    logic [79:0] packed_word, next_word;
    logic mem_write, mem_read, advance_metadata;
    logic [2:0] metadata_slot;
    logic [5:0] metadata_word;
    logic [9:0] word_address;
    logic [63:0] encoded_word, selected_word;"""),
        ("""        next_word = strip_index[1:0] == 0 ? '0 : packed_word;
        next_word[16*strip_index[1:0] +: 16] = {meta_negative & meta_outliers, meta_outliers};
        mem_write = rst_n && meta_valid && meta_ready && !invalid_metadata &&
            (last_strip || strip_index[1:0] == 3);
        mem_read = rst_n && state == ReadWord;
        word_address = {token_index[2:0], strip_index[7:2]};
        selected_word = token_index[3] ? upper_q : lower_q;
        metadata = selected_word[16*strip_index[1:0] +: 16];""", """        next_word = metadata_slot == 0 ? '0 : packed_word;
        next_word[16*metadata_slot +: 16] = {meta_negative & meta_outliers, meta_outliers};
        mem_write = rst_n && accept_metadata && (last_strip || metadata_slot == 3'd4);
        mem_read = rst_n && state == ReadWord;
        word_address = 10'(token_index)*10'd52 + 10'(metadata_word);"""),
        ("""    TS5N28HPCPSVTA512X64M4F lower_metadata (
        .CLK(clk), .CEB(!(mem_write || mem_read) || token_index[3]),
        .WEB(!mem_write), .A(word_address), .D(next_word), .Q(lower_q)
    );
    TS5N28HPCPSVTA512X64M4F upper_metadata (
        .CLK(clk), .CEB(!(mem_write || mem_read) || !token_index[3]),
        .WEB(!mem_write), .A(word_address), .D(next_word), .Q(upper_q)
    );""", """    tri_oracle_outlier_word_codec metadata_codec (
        .encode_metadata(next_word), .encoded(encoded_word), .decode_word(selected_word),
        .decode_strip(metadata_slot), .decoded_metadata(metadata)
    );
    tri_oracle_compact_outlier_words metadata_memory (
        .clk, .read_enable(mem_read), .write_enable(mem_write),
        .address(word_address), .write_word(encoded_word), .read_word(selected_word)
    );

    // Advance in the same cycles as the existing strip cursor. Each token
    // has a fixed 52-word region, including the partial final word.
    assign advance_metadata = accept_metadata ||
        (state == SelectStrip && metadata[7:0] == 0 && !last_strip) ||
        (state == WaitFetch && fetch_valid && pred_in_ready && !fetch_last && !fetch_error);
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            metadata_slot <= '0;
            metadata_word <= '0;
        end else if ((state == Idle && cfg_valid) || (accept_metadata && last_strip) ||
                     (state == HoldGroup && out_ready && pred_valid)) begin
            metadata_slot <= '0;
            metadata_word <= '0;
        end else if (advance_metadata) begin
            if (metadata_slot == 3'd4) begin
                metadata_slot <= '0;
                metadata_word <= metadata_word + 6'd1;
            end else metadata_slot <= metadata_slot + 3'd1;
        end
    end"""),
        ("if (strip_index[1:0] == 3) state <= ReadWord;",
         "if (metadata_slot == 3'd4) state <= ReadWord;"),
        ("state <= state_t'(strip_index[1:0] == 3 ? ReadWord : SelectStrip);",
         "state <= state_t'(metadata_slot == 3'd4 ? ReadWord : SelectStrip);"),
    ))


def run(output):
    prior = ROOT / "records/wac_pipelined_ranked_sign_native_result.json"
    proof = json.loads(prior.read_text())
    assert proof["state"] == "pipelined_ranked_sign_predictor_verified_in_xcelium"
    pins = proof["evidence_sha256"]
    assert all(sha(ROOT / name) == digest for name, digest in pins.items())
    output.mkdir()
    tracked = (RTL / "tri_oracle_outlier_word_codec.sv", RTL / "tri_oracle_compact_outlier_words.sv")
    for name in (PREDICTOR, "tri_oracle_ranked_sign_slots.sv", "tri_oracle_ranked_sign_line_cache.sv",
                 "tri_oracle_packed_sign_predictor_tb.sv", "miss_addresses.hex"):
        source = SOURCE / name
        assert pins[str(source.relative_to(ROOT))] == sha(source)
        code = source.read_text()
        (output / name).write_text(predictor(code) if name == PREDICTOR else code)
    paths = (prior, Path(__file__).resolve(), *tracked, *output.iterdir())
    receipt = {
        "state": "compact_ranked_outlier_metadata_trial_prepared",
        "words": 16 * 52, "maximum_strips_per_token": 256,
        "input_sha256": {str(path.relative_to(ROOT)): sha(path) for path in paths},
    }
    (output / "prepared.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(receipt["state"], receipt["words"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=lambda path: Path(path).resolve())
    run(parser.parse_args().output)
