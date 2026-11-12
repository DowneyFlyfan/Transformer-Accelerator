"""Prepare a trained predictor replay with group-local ranked sign slots."""

import argparse
from collections import Counter
import json
from pathlib import Path

from prepare_tri_oracle_packed_sign_predictor import (
    ARCHIVE, BENCH, CACHE, ROOT, SOURCE, bench, predictor, rewrite, sha,
)
from prepare_tri_oracle_sign_line_cache_replay import BASE, GROUPS, STRIPS, fold


ALLOCATOR = ROOT / "verilog/tri_oracle_ranked_sign_slots.sv"
LINE_CACHE = ROOT / "verilog/tri_oracle_dual_port_sign_line_cache.sv"
ENTRIES = 32


def fixture_misses(sequence, primary_buckets):
    """Rank strips independently from the original trained cache request sequence."""
    addresses = [int(word, 16) & ((1 << 64) - 1) for word in sequence.read_text().splitlines()]
    first_group = Counter((address - BASE) >> 6 for address in addresses if address < BASE + STRIPS * 64)
    chosen = {strip for strip, count in sorted(first_group.items(), key=lambda row: (-row[1], row[0]))[:ENTRIES]
              if count >= 2}
    groups = Counter()
    misses = []
    previous_group, valid = None, set()
    for address in addresses:
        assert address % 64 == 0 and BASE <= address < BASE + GROUPS * STRIPS * 64
        group, strip = divmod((address - BASE) >> 6, STRIPS)
        assert previous_group is None or group in (previous_group, previous_group + 1)
        if group != previous_group:
            previous_group = group
            valid.clear()
        groups[group, strip] += 1
        if strip in chosen:
            if strip in valid:
                continue
            valid.add(strip)
        primary = fold(address >> 6, 5) < primary_buckets
        misses.append((address, 1 if primary else 2))
    assert groups == {(group, strip): count for group in range(GROUPS) for strip, count in first_group.items()}
    return misses, {"entries": ENTRIES, "requests": len(addresses), "allocated_strips": len(chosen),
                    "primary": sum(port == 1 for _, port in misses), "auxiliary": sum(port == 2 for _, port in misses)}


def ranked_cache(code, primary_buckets):
    return rewrite(code, (
        ("module tri_oracle_dual_port_sign_line_cache", "module tri_oracle_ranked_sign_line_cache"),
        ("parameter int ENTRIES = 128", f"parameter int ENTRIES = {ENTRIES}"),
        ("    input logic client_req_valid,",
         "    input logic client_req_valid, client_slot_valid,\n"
         "    input logic [$clog2(ENTRIES)-1:0] client_slot,"),
        ("localparam int BANK_BITS = INDEX_BITS - 5;", "localparam int BANK_BITS = INDEX_BITS > 5 ? INDEX_BITS - 5 : 1;"),
        ("ENTRIES == 256 ? 5'd8 : 5'd9;", f"5'd{primary_buckets};"),
        ("""    // At a given folded index, the high tag bits uniquely determine the low
    // address bits. Store only the high bits to avoid duplicate tag storage.
    logic [63:6+INDEX_BITS] tags[ENTRIES];
""", ""),
        ("        request_slot = '0;", "        request_slot = client_slot;"),
        ("            request_slot[(bit_index - 6) % INDEX_BITS] ^= client_req_address[bit_index];\n", ""),
        ("valid_lines[request_slot] && tags[request_slot] == client_req_address[63:6+INDEX_BITS]",
         "client_slot_valid && valid_lines[request_slot]"),
        ("access_slot[INDEX_BITS-1:5] == BANK_BITS'(bank)", "(access_slot >> 5) == INDEX_BITS'(bank)"),
        ("read_bank <= request_slot[INDEX_BITS-1:5];", "read_bank <= BANK_BITS'(request_slot >> 5);"),
        ("                        fill_pending <= 1;", "                        fill_pending <= client_slot_valid;"),
        ("                        tags[miss_slot] <= mem_req_address[63:6+INDEX_BITS];\n", ""),
    ))


def ranked_predictor(code):
    return rewrite(predictor(code), (
        ("    logic invalid_metadata;", """    logic invalid_metadata;
    logic ranked_ready, ranked_hit_slot, accept_metadata, invalidate_signs;
    logic [4:0] ranked_slot;"""),
        ("commit_ready = state == Commit && !abort_fill;", "commit_ready = state == Commit && !abort_fill && ranked_ready;"),
        ("else if (commit_valid) state <= ReadWord;", "else if (commit_valid && commit_ready) state <= ReadWord;"),
        ("    tri_oracle_dual_port_sign_line_cache sign_cache (\n        .clk, .rst_n, .frame_start(cfg_valid && cfg_ready),",
         """    assign accept_metadata = meta_valid && meta_ready && !invalid_metadata;
    assign invalidate_signs = (cfg_valid && cfg_ready) ||
        (state == HoldGroup && pred_valid && out_ready && last_token);

    tri_oracle_ranked_sign_slots slots (
        .clk, .rst_n, .frame_start(cfg_valid && cfg_ready && !invalid_config),
        .frame_enable(cfg_tokens > 5'd1), .frame_strips(cfg_strips[8:0]),
        .observe_valid(accept_metadata), .observe_first(token_index == 0),
        .observe_active(|meta_outliers), .observe_strip(strip_index),
        .build(accept_metadata && last_strip && last_token), .map_ready(ranked_ready),
        .lookup_strip(strip_index), .lookup_valid(ranked_hit_slot), .lookup_slot(ranked_slot)
    );

    tri_oracle_ranked_sign_line_cache sign_cache (
        .clk, .rst_n, .frame_start(invalidate_signs),
        .client_slot_valid(ranked_hit_slot), .client_slot(ranked_slot),"""),
    ))


def run(output):
    sequence = CACHE / "sequence_128.hex"
    fixture_proof = ROOT / "records/wac_dual_port_sign_line_cache_result.json"
    archive_path = ARCHIVE / "receipt.json"
    budget_path = ROOT / "records/wac_ranked_sign_cache_service_result.json"
    native, archive, budget = (json.loads(path.read_text()) for path in (fixture_proof, archive_path, budget_path))
    for path in (sequence, LINE_CACHE):
        assert sha(path) == native["evidence_sha256"][str(path.relative_to(ROOT))]
    for path in (SOURCE, BENCH):
        assert sha(path) == archive["input_sha256"][str(path.relative_to(ROOT))]
    primary_buckets = budget["ranked"][str(ENTRIES)]["send_to_primary_when_bucket_below"]
    misses, counts = fixture_misses(sequence, primary_buckets)
    assert counts["requests"] == budget["trained_fixture"]["requests"]
    assert len(misses) == budget["trained_fixture"]["ranked_32_external_reads"]
    output.mkdir()
    sources = {
        "tri_oracle_ranked_sign_line_cache.sv": ranked_cache(LINE_CACHE.read_text(), primary_buckets),
        "tri_oracle_packed_outlier_replay.sv": ranked_predictor(SOURCE.read_text()),
        "tri_oracle_packed_sign_predictor_tb.sv": bench(BENCH.read_text(), counts),
        "miss_addresses.hex": "".join(f"{(port << 64) | address:017x}\n" for address, port in misses),
    }
    for name, code in sources.items():
        (output / name).write_text(code)
    paths = (Path(__file__).resolve(), Path(predictor.__code__.co_filename), Path(fold.__code__.co_filename),
             ALLOCATOR, LINE_CACHE, SOURCE, BENCH, sequence, fixture_proof, archive_path, budget_path,
             *(output / name for name in sources))
    receipt = {"state": "ranked_sign_predictor_replay_prepared", "counts": counts, "primary_buckets": primary_buckets,
               "input_sha256": {str(path.relative_to(ROOT)): sha(path) for path in paths}}
    (output / "prepared.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(receipt["state"], counts, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=lambda path: Path(path).resolve())
    run(parser.parse_args().output)
