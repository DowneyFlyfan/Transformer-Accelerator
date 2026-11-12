"""Split the observation and slot-build read paths of the ranked predictor."""

import argparse
import json
from pathlib import Path

from prepare_tri_oracle_packed_sign_predictor import ROOT, rewrite, sha


WORK = ROOT / ".cache/physical/ranked_sign_slots"
BASELINE = WORK / "integrated_32_final"
ALLOCATOR = ROOT / "verilog/tri_oracle_ranked_sign_slots.sv"
BENCH = ROOT / "verilog/tri_oracle_ranked_sign_slots_tb.sv"
MAX_BUILD_CYCLES = 273


def allocator(code):
    return rewrite(code, (
        ("    logic [7:0] scan_strip, count_address;", """    logic [7:0] scan_strip, bank_strip, allocation_strip;
    logic scan_active, bank_valid, allocation_valid;
    logic [4:0] bank_uses[16], build_uses;"""),
        ("""    assign count_address = state == BuildMap ? scan_strip : observe_strip;
    assign uses = state == Collect && observe_first ? 5'd0 : strip_uses[count_address];""",
         "    assign uses = observe_first ? 5'd0 : strip_uses[observe_strip];"),
        ("    assign select_strip = uses > cutoff || (uses == cutoff && remaining != 0);",
         "    assign select_strip = build_uses > cutoff || (build_uses == cutoff && remaining != 0);"),
        ("""            remaining <= '0;
            scan_strip <= '0;""", """            remaining <= '0;
            scan_strip <= '0;
            scan_active <= 0;
            bank_valid <= 0;
            allocation_valid <= 0;"""),
        ("""            remaining <= 9'(ENTRIES);
            scan_strip <= '0;""", """            remaining <= 9'(ENTRIES);
            scan_strip <= '0;
            scan_active <= 1;
            bank_valid <= 0;
            allocation_valid <= 0;"""),
        ("""            BuildMap: begin
                strip_selected[scan_strip] <= select_strip;
                if (select_strip) begin
                    strip_slot[scan_strip] <= next_slot;
                    next_slot <= next_slot + 1'b1;
                    if (uses == cutoff) remaining <= remaining - 9'd1;
                end
                if ({1'b0, scan_strip} + 9'd1 == strips) state <= Ready;
                else scan_strip <= scan_strip + 8'd1;
            end""", """            BuildMap: begin
                // Read sixteen local candidates, then select the addressed
                // bank. Neither pipeline stage uses the observation address.
                bank_valid <= scan_active;
                if (scan_active) begin
                    for (int bank = 0; bank < 16; bank++)
                        bank_uses[bank] <= strip_uses[{4'(bank), scan_strip[3:0]}];
                    bank_strip <= scan_strip;
                    if ({1'b0, scan_strip} + 9'd1 == strips) scan_active <= 0;
                    else scan_strip <= scan_strip + 8'd1;
                end
                allocation_valid <= bank_valid;
                if (bank_valid) begin
                    build_uses <= bank_uses[bank_strip[7:4]];
                    allocation_strip <= bank_strip;
                end
                if (allocation_valid) begin
                    strip_selected[allocation_strip] <= select_strip;
                    if (select_strip) begin
                        strip_slot[allocation_strip] <= next_slot;
                        next_slot <= next_slot + 1'b1;
                        if (build_uses == cutoff) remaining <= remaining - 9'd1;
                    end
                    if ({1'b0, allocation_strip} + 9'd1 == strips) state <= Ready;
                end
            end"""),
    ))


def unit_bench(code):
    return rewrite(code, (
        ("delay_cycles < 272", f"delay_cycles < {MAX_BUILD_CYCLES + 1}"),
        ("delay_cycles > 271", f"delay_cycles > {MAX_BUILD_CYCLES}"),
        ('        $display("RANKED_SIGN_SLOTS_PASS', f"""        if (max_build_cycles != {MAX_BUILD_CYCLES})
            $fatal(1, "RANKED_SIGN_PIPELINE_LATENCY cycles=%0d", max_build_cycles);
        $display("RANKED_SIGN_SLOTS_PASS"""),
    ))


def run(output):
    placement = ROOT / "records/wac_ranked_sign_predictor_placed_result.json"
    mapped = ROOT / "records/wac_ranked_sign_predictor_mapped_result.json"
    native = ROOT / "records/wac_ranked_sign_predictor_native_result.json"
    inputs = [json.loads(path.read_text()) for path in (placement, mapped, native)]
    assert inputs[0]["estimated_timing"]["setup_slow"]["worst_slack_ns"] == -2.079699
    assert inputs[0]["slow_setup_path_startpoints"] == {"strip_index_reg[0]/CP": 15}
    evidence = inputs[2]["evidence_sha256"]
    assert all(sha(ROOT / name) == digest for name, digest in evidence.items())
    output.mkdir()
    candidate = {
        ALLOCATOR.name: allocator(ALLOCATOR.read_text()),
        BENCH.name: unit_bench(BENCH.read_text()),
    }
    for name in ("tri_oracle_packed_outlier_replay.sv", "tri_oracle_ranked_sign_line_cache.sv",
                 "tri_oracle_packed_sign_predictor_tb.sv", "miss_addresses.hex"):
        original = BASELINE / name
        assert sha(original) == evidence[str(original.relative_to(ROOT))]
        candidate[name] = original.read_text()
    for name, contents in candidate.items():
        (output / name).write_text(contents)
    paths = (Path(__file__).resolve(), placement, mapped, native, ALLOCATOR, BENCH,
             *(output / name for name in candidate))
    receipt = {
        "state": "banked_ranked_slot_build_pipeline_prepared",
        "build_delay_cycles_added": MAX_BUILD_CYCLES - inputs[2]["maximum_build_cycles_per_prefill_frame"],
        "input_sha256": {str(path.relative_to(ROOT)): sha(path) for path in paths},
    }
    (output / "prepared.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(receipt["state"], receipt["build_delay_cycles_added"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=lambda path: Path(path).resolve())
    run(parser.parse_args().output)
