"""Register the compact metadata word while preserving predictor replay cadence."""

import argparse
import json
from pathlib import Path

from prepare_tri_oracle_packed_sign_predictor import ROOT, rewrite, sha


WORK = ROOT / ".cache/physical/ranked_sign_slots"
SOURCE = WORK / "banked_observation_32"
PREDICTOR = "tri_oracle_packed_outlier_replay.sv"
WITNESS = ROOT / "verilog/tri_oracle_metadata_prefetch_witness.sv"


def predictor(code):
    return rewrite(code, (
        ("    logic mem_write, mem_read, advance_metadata;",
         "    logic mem_write, mem_read, advance_metadata, following_read, next_token_read;"),
        ("    logic [63:0] encoded_word, selected_word;", "    logic [63:0] encoded_word, memory_word, latched_word;"),
        ("""        mem_read = rst_n && state == ReadWord;
        word_address = 10'(token_index)*10'd52 + 10'(metadata_word);""",
         """        word_address = 10'(token_index)*10'd52 + 10'(metadata_word);
        if (following_read) word_address = word_address + 10'd1;
        if (next_token_read) word_address = last_token ? 10'd0 : 10'(token_index)*10'd52 + 10'd52;"""),
        ("""    tri_oracle_outlier_word_codec metadata_codec (""",
         """    // Read the next word before leaving its predecessor. For an active
    // fifth strip, the memory output can wait through its sign response.
    assign following_read = state == SelectStrip && metadata_slot == 3'd4 && !last_strip;
    assign next_token_read = state == HoldGroup && out_ready && pred_valid && !(last_token && last_group);
    assign mem_read = rst_n && ((commit_valid && commit_ready) || following_read || next_token_read);

    always_ff @(posedge clk)
        if (state == ReadWord) latched_word <= memory_word;

    tri_oracle_outlier_word_codec metadata_codec ("""),
        (".encoded(encoded_word), .decode_word(selected_word)", ".encoded(encoded_word), .decode_word(latched_word)"),
        (".write_word(encoded_word), .read_word(selected_word)", ".write_word(encoded_word), .read_word(memory_word)"),
    ))


def run(output):
    native_path = ROOT / "records/wac_banked_ranked_observation_native_result.json"
    physical_path = ROOT / "records/wac_banked_ranked_observation_placed_result.json"
    native, physical = (json.loads(path.read_text()) for path in (native_path, physical_path))
    assert native["state"] == "banked_strip_observation_verified_in_xcelium"
    assert physical["state"] == "banked_compact_predictor_mapped_replayed_and_placed"
    slow = physical["estimated_timing"]["setup_slow"]
    assert slow["startpoint"] == "metadata_memory_read_tail_reg/CP"
    assert slow["endpoint"] == "metadata_word_reg[0]/D" and slow["worst_slack_ns"] < 0
    assert all(sha(ROOT / name) == digest for name, digest in native["input_sha256"].items())

    output.mkdir()
    generated = []
    for name in (PREDICTOR, "tri_oracle_ranked_sign_slots.sv", "tri_oracle_ranked_sign_line_cache.sv",
                 "tri_oracle_packed_sign_predictor_tb.sv", "memory_witness.sv", "miss_addresses.hex"):
        source = SOURCE / name
        assert native["input_sha256"][str(source.relative_to(ROOT))] == sha(source)
        target = output / name
        code = source.read_text()
        target.write_text(predictor(code) if name == PREDICTOR else code)
        generated.append(target)
    paths = (Path(__file__).resolve(), native_path, physical_path, WITNESS, *generated)
    evidence = {str(path.relative_to(ROOT)): sha(path) for path in paths}
    prepared = {
        "state": "metadata_prefetch_and_capture_prepared",
        "baseline_slow_setup_slack_ns": slow["worst_slack_ns"],
        "input_sha256": evidence,
    }
    (output / "prepared.json").write_text(json.dumps(prepared, indent=2, sort_keys=True) + "\n")
    print(prepared["state"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=lambda path: Path(path).resolve())
    run(parser.parse_args().output)
