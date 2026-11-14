"""Exercise the real mapped predictor after projection releases its lower memory."""
import argparse
import json
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory

from run_tri_oracle_batch396_masks import GIB, check_memory
from test_tri_oracle_attention_projection_scale import ROOT, sha, trained_vectors
from tri_oracle_process_guard import terminate_process_group

RANKED = ROOT / ".cache/physical/ranked_sign_slots"
REPLAY = RANKED / "mapped_prefetched_metadata_bank_traffic"
PREDICTOR = RANKED / "mapped_prefetched_metadata_32/netlist.v"
BANK = ROOT / ".cache/placement_coordinate_reuse/projection_shared_bank/netlist.v"
BRIDGE = ROOT / "verilog/tri_oracle_projection_read_bridge.sv"
TOP = "tri_oracle_packed_sign_predictor_tb"
BANK_PORTS = dict(CEB="metadata_ce_n", WEB="metadata_we_n", A="metadata_address",
                  D="metadata_write_data", Q="metadata_read_data")

PROJECTION_TEST = r"""
    logic acquire_valid = 0, acquire_ready, release_valid = 0, release_ready;
    logic row_valid = 0, row_ready, frame_ready, fill_error;
    logic [2047:0] row_data;
    logic [4:0] row_shift;
    logic [5:0] row_index;
    logic projection_req_valid = 0, projection_rsp_valid;
    logic [8:0] projection_req_word;
    logic projection_rsp_ready = 0, projection_rsp_last, projection_rsp_error;
    logic [63:0] projection_rsp_data;
    logic chip_req_ready, chip_rsp_valid, chip_rsp_last, chip_rsp_error, bridge_idle;
    logic [511:0] chip_rsp_data;
    logic local_req_valid, local_req_ready, local_rsp_ready, external_read;
    logic [8:0] local_req_word;
    logic [4:0] local_req_length;
    wire metadata_ce_n, metadata_we_n;
    wire [8:0] metadata_address;
    wire [63:0] metadata_write_data, metadata_read_data;
    logic [2052:0] operands[64];
    logic [511:0] activation[64];

    tri_oracle_projection_read_bridge projection_reads (
        .clk, .rst_n, .projection_enabled(frame_ready),
        .req_valid(projection_req_valid), .req_wide(1'b0), .req_ready(chip_req_ready),
        .req_address(64'h10000 | (64'(projection_req_word) << 3)), .req_length(6'd16),
        .rsp_valid(chip_rsp_valid), .rsp_ready(projection_rsp_ready),
        .rsp_last(chip_rsp_last), .rsp_error(chip_rsp_error), .rsp_data(chip_rsp_data),
        .external_req_valid(external_read), .external_req_ready(1'b0),
        .external_req_wide(), .external_req_address(), .external_req_length(),
        .external_rsp_valid(1'b0), .external_rsp_last(1'b0), .external_rsp_error(1'b0),
        .external_rsp_ready(), .external_rsp_data('0),
        .local_req_valid, .local_req_ready, .local_req_word, .local_req_length,
        .local_rsp_valid(projection_rsp_valid), .local_rsp_ready,
        .local_rsp_last(projection_rsp_last), .local_rsp_error(projection_rsp_error),
        .local_rsp_data(projection_rsp_data), .idle(bridge_idle)
    );

    tri_oracle_projection_shared_bank projection (
        .clk, .rst_n, .metadata_idle(cfg_ready && !cfg_valid),
        .acquire_valid, .acquire_ready, .release_valid, .release_ready,
        .row_valid, .row_ready, .row_data, .row_shift, .row_index,
        .frame_ready, .fill_error,
        .req_valid(local_req_valid), .req_ready(local_req_ready),
        .req_word(local_req_word), .req_length(local_req_length),
        .rsp_valid(projection_rsp_valid), .rsp_ready(local_rsp_ready),
        .rsp_last(projection_rsp_last), .rsp_error(projection_rsp_error), .rsp_data(projection_rsp_data),
        .metadata_ce_n, .metadata_we_n, .metadata_address, .metadata_write_data, .metadata_read_data
    );

    task automatic replay_projection;
        string rows, expected;
        if (!$value$plusargs("PROJECTION_ROWS=%s", rows) ||
            !$value$plusargs("PROJECTION_EXPECTED=%s", expected))
            $fatal(1, "PROJECTION_METADATA_FIXTURE");
        $readmemh(rows, operands);
        $readmemh(expected, activation);
        acquire_valid = 1;
        @(posedge clk);
        if (acquire_ready !== 1'b1) $fatal(1, "PROJECTION_METADATA_ACQUIRE");
        @(negedge clk);
        acquire_valid = 0;

        for (int row = 0; row < 64; row++) begin
            row_index = 6'(17*row+63);
            {row_shift,row_data} = operands[row_index];
            row_valid = 1;
            do @(posedge clk); while (row_ready !== 1'b1);
            @(negedge clk);
            row_valid = 0;
        end
        if (fill_error || !frame_ready) $fatal(1, "PROJECTION_METADATA_COMMIT");

        for (int word = 0; word < 512; word += 16) begin
            projection_req_valid = 1;
            projection_req_word = 9'(word);
            @(posedge clk);
            if ({chip_req_ready, external_read} !== 2'b10) $fatal(1, "PROJECTION_METADATA_REQUEST");
            @(negedge clk);
            projection_req_valid = 0;
            for (int beat = 0; beat < 16; beat++) begin
                // Each burst includes a held response before its first acceptance.
                if (beat == 0) begin
                    @(posedge clk);
                    if (release_ready || !chip_rsp_valid || bridge_idle)
                        $fatal(1, "PROJECTION_METADATA_ACTIVE_RELEASE");
                    @(negedge clk);
                end
                projection_rsp_ready = 1;
                @(posedge clk);
                if ({chip_rsp_valid,chip_rsp_error,chip_rsp_last,chip_rsp_data} !==
                    {1'b1,1'b0,(beat==15),448'b0,activation[(word+beat)/8][64*((word+beat)%8) +: 64]})
                    $fatal(1, "PROJECTION_METADATA_OPERAND word=%0d", word+beat);
                @(negedge clk);
                projection_rsp_ready = 0;
            end
        end

        release_valid = 1;
        @(posedge clk);
        if (release_ready !== 1'b1) $fatal(1, "PROJECTION_METADATA_RELEASE");
        @(negedge clk);
        release_valid = 0;
        if (frame_ready || chip_rsp_valid || !bridge_idle) $fatal(1, "PROJECTION_METADATA_STALE_FRAME");
        $display("PROJECTION_METADATA_HANDOFF_PASS rows=64 words=512");
    endtask
"""


def once(text, before, after):
    assert text.count(before) == 1, before
    return text.replace(before, after, 1)


def open_bank(text):
    instance = re.search(r"(?ms)^  TS5N28HPCPSVTA512X64M4F metadata_memory_lower_words\((.*?)\);", text)
    assert instance and text.count("metadata_memory_lower_words(") == 1
    text = text[:instance.start()] + "".join(
        f"  assign {wire} = {expression.strip()};\n" if port != "Q"
        else f"  assign {expression.strip()} = {wire};\n"
        for port, wire in BANK_PORTS.items()
        for expression in [re.search(rf"\.{port}\s*\(([^()]*)\)", instance[1])[1]]
    ) + text[instance.end():]
    return once(text, "     strip_response);", """     strip_response, metadata_ce_n, metadata_we_n, metadata_address,
     metadata_write_data, metadata_read_data);
  output metadata_ce_n, metadata_we_n;
  output [8:0] metadata_address;
  output [63:0] metadata_write_data;
  input [63:0] metadata_read_data;""")


def extend_wrapper(text):
    text = once(text, "    input logic [111:0] strip_response\n);", """    input logic [111:0] strip_response,
    output logic metadata_ce_n, metadata_we_n,
    output logic [8:0] metadata_address,
    output logic [63:0] metadata_write_data,
    input logic [63:0] metadata_read_data
);""")
    return once(text, "        .strip_response(strip_response)\n", """        .strip_response(strip_response),
        .metadata_ce_n, .metadata_we_n, .metadata_address, .metadata_write_data, .metadata_read_data
""")


def extend_bench(text):
    instance = "    tri_oracle_packed_outlier_replay #"
    text = once(text, instance, PROJECTION_TEST + "\n" + instance)
    text = once(text, "        rst_n = 1;\n        cfg_valid = 1;",
                "        rst_n = 1;\n        replay_projection();\n        cfg_valid = 1;")
    return once(text, ".strip_request, .strip_response\n", """.strip_request, .strip_response,
        .metadata_ce_n, .metadata_we_n, .metadata_address, .metadata_write_data, .metadata_read_data
""")


def run(log, mutate, bridge=BRIDGE):
    assert Path("/.dockerenv").is_file()
    check_memory(10 * GIB)
    receipt = json.loads((REPLAY / "receipt.json").read_text())
    assert receipt["state"] == "compact_predictor_mapped_bank_traffic_verified"
    invocation = REPLAY / "invocation.json"
    command = json.loads(invocation.read_text())["argv"]
    inputs = (PREDICTOR, invocation, REPLAY / "mapped_predictor.sv", REPLAY / f"{TOP}.sv")
    for path in inputs:
        assert sha(path) == receipt["input_sha256"][str(path.relative_to(ROOT))]
    result = json.loads((ROOT / "records/tri_oracle_projection_shared_bank.json").read_text())
    assert sha(BANK) == result["evidence_sha256"][str(BANK.relative_to(ROOT))]
    vectors, pins = trained_vectors()
    pins.update({path: sha(path) for path in (*inputs, BANK, bridge, Path(__file__).resolve())})
    with TemporaryDirectory(prefix="mapped_projection_metadata_", dir=ROOT / ".cache") as tmp:
        work = Path(tmp)
        rows, expected = work / "rows.hex", work / "expected.hex"
        row_data, expected_data = [], []
        for start in range(0, len(vectors), 64):
            words = [int(value, 16) for value in vectors[start:start+64]]
            shift = (words[0] >> 8) & 31
            payload = sum((word >> 13) << (32*lane) for lane, word in enumerate(words))
            row_data.append(f"{(shift << 2048) | payload:0514x}")
            expected_data.append(f"{sum((word & 255) << (8*lane) for lane, word in enumerate(words)):0128x}")
        rows.write_text("\n".join(row_data) + "\n")
        expected.write_text("\n".join(expected_data) + "\n")
        sources = {
            inputs[0]: open_bank(inputs[0].read_text()),
            inputs[2]: extend_wrapper(inputs[2].read_text()),
            inputs[3]: extend_bench(inputs[3].read_text()),
        }
        if mutate:
            sources[inputs[0]] = once(sources[inputs[0]], "assign metadata_write_data = encoded_word;",
                                     "assign metadata_write_data = 64'b0;")
        for path, content in sources.items():
            assert command.count(str(path)) == 1
            replacement = work / path.name
            replacement.write_text(content)
            command[command.index(str(path))] = str(replacement)
        log_file = work / "xrun.log"
        command.extend([str(BANK), str(bridge), "-l", str(log_file),
                        f"+PROJECTION_ROWS={rows}", f"+PROJECTION_EXPECTED={expected}"])
        with log.open("x") as stream:
            child = subprocess.Popen(command, cwd=work, stdin=subprocess.DEVNULL,
                                     stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                status = child.wait(timeout=180)
            finally:
                terminate_process_group(child, log_argument=str(log_file))
    assert all(sha(path) == digest for path, digest in pins.items())
    text = log.read_text()
    marker = "PROJECTION_METADATA_HANDOFF_PASS rows=64 words=512"
    assert text.splitlines().count(marker) == 1, text[-2500:]
    if mutate:
        assert status != 0 and "PACKED_SIGN_PREDICTOR_PASS" not in text
        assert re.search(r"TRAINED_SIGN_CACHE_MASK|PACKED_SIGN_PREDICTOR_ADDRESS|TRAINED_SIGN_CACHE_INVENTORY", text)
        print("PROJECTION_METADATA_CORRUPTED_REBUILD_REJECTED")
        return
    assert status == 0 and not re.search(r"\*[EF],", text), text[-2500:]
    proven, = re.findall(r"(?m)^PACKED_SIGN_PREDICTOR_PASS (.+)$", text)
    fields = dict((key, int(value)) for key, value in (field.split("=") for field in proven.split()))
    baseline = receipt["trained_replay"]
    assert {k: v for k, v in fields.items() if k != "cycles"} == {
        k: v for k, v in baseline.items() if k != "cycles"
    }
    print(marker)
    print("PACKED_SIGN_PREDICTOR_PASS", proven)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("--mutate", action="store_true")
    parser.add_argument("--bridge", type=Path, default=BRIDGE)
    args = parser.parse_args()
    run(args.log.resolve(), args.mutate, args.bridge.resolve())
