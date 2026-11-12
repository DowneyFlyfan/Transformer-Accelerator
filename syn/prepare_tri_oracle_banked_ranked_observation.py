"""Prepare a ranked predictor with banked, pipelined strip observations."""

import argparse
import json
from pathlib import Path

from prepare_tri_oracle_packed_sign_predictor import ROOT, rewrite, sha


WORK = ROOT / ".cache/physical/ranked_sign_slots"
PIPELINED = WORK / "pipelined_32"
COMPACT = WORK / "compact_ranked_32"
BENCH = "tri_oracle_ranked_sign_slots_tb.sv"
ALLOCATOR = "tri_oracle_ranked_sign_slots.sv"
MAX_BUILD_CYCLES = 276


def allocator(code):
    return rewrite(code, (
        ("{Idle, Collect, FindCutoff, BuildMap, Ready, Bypass}",
         "{Idle, Collect, DrainObservations, FindCutoff, BuildMap, Ready, Bypass}"),
        ("    logic [4:0] cutoff, uses;", "    logic [4:0] cutoff;"),
        ("""    logic observe, add_use, select_strip;

    assign uses = observe_first ? 5'd0 : strip_uses[observe_strip];
    assign observe = state == Collect && observe_valid && {1'b0, observe_strip} < strips;
    assign add_use = observe && observe_active && uses < 5'd16;""", """    logic observe, select_strip;
    logic observation_valid, observation_first, observation_active;
    logic [15:0] observation_rows, observation_banks, read_banks;
    logic read_valid, read_first, histogram_valid;
    logic [4:0] previous_by_bank[16], read_count, previous_count;

    assign observe = state == Collect && observe_valid && {1'b0, observe_strip} < strips;

    // Decode the observation address once. Each counter uses its own
    // registered value for the increment, with no shared write-data mux.
    for (genvar bank = 0; bank < 16; bank++) begin : observed_banks
        logic [4:0] selected_count;
        always_comb begin
            selected_count = '0;
            for (int row = 0; row < 16; row++)
                selected_count |= strip_uses[16*bank + row] & {5{observation_rows[row]}};
        end
        for (genvar row = 0; row < 16; row++) begin : observed_rows
            localparam int INDEX = 16*bank + row;
            always_ff @(posedge clk) begin
                if (!frame_start && observation_valid && observation_banks[bank] && observation_rows[row]) begin
                    if (observation_first) strip_uses[INDEX] <= observation_active ? 5'd1 : 5'd0;
                    else if (observation_active && strip_uses[INDEX] < 5'd16)
                        strip_uses[INDEX] <= strip_uses[INDEX] + 5'd1;
                end
            end
        end
        // Sample the selected counter at the same edge that increments it.
        // A consecutive observation therefore sees the preceding update.
        always_ff @(posedge clk)
            if (observation_valid && observation_active && observation_banks[bank])
                previous_by_bank[bank] <= selected_count;
    end

    always_comb begin
        read_count = '0;
        for (int bank = 0; bank < 16; bank++)
            read_count |= previous_by_bank[bank] & {5{read_banks[bank]}};
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) {observation_valid, read_valid, histogram_valid} <= '0;
        else {observation_valid, read_valid, histogram_valid} <= frame_start ? 3'b0 :
            {observe, (observation_valid && observation_active), read_valid};
    end

    always_ff @(posedge clk) begin
        if (observe) begin
            observation_first <= observe_first;
            observation_active <= observe_active;
            observation_rows <= 16'b1 << observe_strip[3:0];
            observation_banks <= 16'b1 << observe_strip[7:4];
        end
        if (observation_valid && observation_active) begin
            read_first <= observation_first;
            read_banks <= observation_banks;
        end
        if (read_valid) previous_count <= read_first ? 5'd0 : read_count;
    end"""),
        ("""        end else case (state)
            Collect: begin
                // The first token initializes every configured entry.
                if (observe && (observe_first || add_use))
                    strip_uses[observe_strip] <= add_use ? uses + 5'd1 : 5'd0;
                if (add_use) begin
                    histogram[uses] <= histogram[uses] - 9'd1;
                    histogram[uses + 5'd1] <= histogram[uses + 5'd1] + 9'd1;
                end
                if (build) state <= FindCutoff;
            end""", """        end else begin
            if (histogram_valid && previous_count < 5'd16) begin
                for (int bin = 0; bin <= 16; bin++) begin
                    if (previous_count == 5'(bin)) histogram[bin] <= histogram[bin] - 9'd1;
                    else if (previous_count + 5'd1 == 5'(bin)) histogram[bin] <= histogram[bin] + 9'd1;
                end
            end
            case (state)
            Collect: if (build) state <= DrainObservations;
            DrainObservations: begin
                // The histogram can commit its last update on this edge.
                if (!observation_valid && !read_valid) state <= FindCutoff;
            end"""),
        ("        endcase\n    end\nendmodule", "            endcase\n        end\n    end\nendmodule"),
    ))


def observation_bench(code):
    return rewrite(code, (
        ("delay_cycles < 274", f"delay_cycles < {MAX_BUILD_CYCLES + 1}"),
        ("delay_cycles > 273", f"delay_cycles > {MAX_BUILD_CYCLES}"),
        ("                    default: active = (strip % 7 == 0) && (token < 2);",
         """                    4: active = token == tokens - 1 || (strip % 7 == 0 && token == 0);
                    default: active = (strip % 7 == 0) && (token < 2);"""),
        ("        synthetic(1, 2, 0);", """        synthetic(1, 2, 0);
        synthetic(1, 16, 0);
        // The last observation must reach the histogram before cutoff selection.
        synthetic(256, 2, 4);
        // Restart while a previous frame has live counter and histogram updates.
        start_frame(1, 1);
        send_strip(0, 1, 1);
        send_strip(0, 0, 1, 1);
        synthetic(1, 2, 1);"""),
        ("max_build_cycles != 273", f"max_build_cycles != {MAX_BUILD_CYCLES}"),
    ))


def run(output):
    source_path = ROOT / "records/wac_compact_ranked_metadata_result.json"
    baseline_path = ROOT / "records/wac_pipelined_ranked_sign_native_result.json"
    placed_path = ROOT / "records/wac_pipelined_ranked_sign_placed_result.json"
    source, baseline, placed = (json.loads(path.read_text()) for path in (source_path, baseline_path, placed_path))
    pins = source["input_sha256"] | baseline["evidence_sha256"]
    assert all(sha(ROOT / name) == digest for name, digest in pins.items())
    assert placed["estimated_timing"]["setup_slow"]["startpoint"] == "strip_index_reg[0]/CP"
    assert placed["estimated_timing"]["setup_slow"]["endpoint"].startswith("slots_strip_uses_reg")

    output.mkdir()
    prepared = []
    for name in (ALLOCATOR, BENCH, "tri_oracle_packed_outlier_replay.sv", "tri_oracle_ranked_sign_line_cache.sv",
                 "tri_oracle_packed_sign_predictor_tb.sv", "memory_witness.sv", "miss_addresses.hex"):
        path = (PIPELINED if name == BENCH else COMPACT) / name
        assert sha(path) == pins[str(path.relative_to(ROOT))]
        content = path.read_text()
        if name == ALLOCATOR:
            content = allocator(content)
        if name == BENCH:
            content = observation_bench(content)
        prepared.append(output / name)
        prepared[-1].write_text(content)
    paths = (Path(__file__).resolve(), source_path, baseline_path, placed_path, *prepared)
    receipt = {
        "state": "registered_banked_strip_observation_prepared",
        "maximum_build_cycles": MAX_BUILD_CYCLES,
        "input_sha256": {str(path.relative_to(ROOT)): sha(path) for path in paths},
    }
    (output / "prepared.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(receipt["state"], receipt["maximum_build_cycles"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=lambda path: Path(path).resolve())
    run(parser.parse_args().output)
