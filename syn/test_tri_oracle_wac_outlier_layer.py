"""Check trained metadata, activation writes and masks through the core SIMD."""

import argparse
import json
from pathlib import Path
import re
import tempfile

from prepare_tri_oracle_wac_outlier_layer import ROOT, RTL, TYPE, edit, read, sha, verify
from replay_mapped_cluster_fixture import shared_memory_stage, wait_for_shared_memory

TOP = "tri_oracle_batched405_normalize_tb"


def test_bench(text):
    anchor = "    tri_oracle_batched_normalize405 dut (.rsp_last"
    text = edit(text, anchor, f"""    {TYPE}::request_t outlier_request;
    {TYPE}::response_t outlier_response;
    logic outlier_response_valid;
    logic [7:0] outliers, negative;
    logic [15:0] expected_norm [TOKENS * FEATURES];
    int metadata_strips = 0;
    bit bad_response;

    assign outlier_response = '{{outlier_valid: outlier_response_valid,
        outliers: bad_response ? ~outliers : outliers, negative: negative, default: '0}};
    tri_oracle_wac_softmax simd (
        .clk, .rst_n, .cfg_valid(1'b0), .cfg_ready(), .cfg_length('0), .cfg_error(),
        .in_valid(1'b0), .in_ready(), .in_score('0), .in_size('0),
        .out_valid(), .out_ready(1'b0), .out_probability(), .out_last(),
        .mem_ce_n(), .mem_we_n(), .mem_address(), .mem_d(), .mem_q('0),
        .outlier_valid(outlier_request.outlier_valid), .metadata_values(outlier_request.normalized),
        .outlier_response_valid, .outliers, .negative
    );
    always @(posedge clk) if (rst_n) begin
        if (cfg_valid && cfg_ready) metadata_strips = 0;
        if (dut.replay_table.meta_valid && dut.replay_table.meta_ready) begin
            if (!outlier_request.outlier_valid || outlier_request.owner != 5'(metadata_strips % 20))
                $fatal(1, "WAC_OUTLIER_OWNER_SEQUENCE");
            for (int lane=0; lane<8; lane++) begin
                automatic logic signed [15:0] code = fault == 4 ? 16'sd256 :
                    $signed(expected_norm[int'(dut.token_index)*FEATURES + int'(dut.norm_index)*8 + lane]);
                if (outlier_request.normalized[16*lane+:16] !== code ||
                    dut.replay_table.meta_outliers[lane] !== (code > 16'sd768 || code < -16'sd768) ||
                    dut.replay_table.meta_negative[lane] !== code[15])
                    $fatal(1, "WAC_OUTLIER_TRAINED_METADATA strip=%0d lane=%0d", metadata_strips, lane);
            end
            metadata_strips++;
        end
    end

    tri_oracle_batched_normalize405 dut (.outlier_request, .outlier_response, .rsp_last""")
    text = edit(text, '        $readmemh({activation_dir,"/gamma.hex"},gamma_words);',
                '        bad_response = $test$plusargs("BAD_OUTLIER_RESPONSE");\n'
                '        $readmemh({activation_dir,"/norm.hex"},expected_norm);\n'
                '        $readmemh({activation_dir,"/gamma.hex"},gamma_words);')
    return edit(text, "        $finish;", """        if (metadata_strips != frame_tokens*frame_strips) $fatal(1, "WAC_OUTLIER_STRIP_COUNT");
        $display("WAC_OUTLIER_TRAINED_PASS fault=%0d strips=%0d codes=%0d", fault, metadata_strips, 8*metadata_strips);
        $finish;""")


def run(case):
    setup = read(case / "receipt.json")
    assert setup["outlier_owner"] == "core_simd_round_robin"
    records = ROOT / "records"
    baseline_path = records / "batch405_normalize_result.json"
    baseline = read(baseline_path)
    vector_paths = [records / name for name in ("batch396_mask_fixture.json", "batch403_activation_precision.json")]
    vectors = [read(path) for path in vector_paths]
    includes = [Path(name) for name in re.findall(r'(?m)^`include "([^"]+)"$', (case / "bundle.sv").read_text())]
    names = ("wac_softmax_types.sv", *(f"tri_oracle_{unit}.sv" for unit in (
        "batched_normalize405", "wac_softmax", "wac_softmax_imem", "wac_outlier_sign", "rmsnorm", "affine_quantizer",
        "rms_activation", "sign_fetch", "strip_predictor", "batched_outlier_replay404")))
    sources = [next(path for path in includes if path.name == name) for name in names]
    model, = (Path(name) for name in baseline["source_sha256"] if name.endswith("512x64m4f_130a_tt1v25c.v"))
    bench = RTL / f"{TOP}.sv"
    pins = setup["input_sha256"].copy()
    assert all(str(path) in pins for path in sources)
    pins[str(model)] = baseline["source_sha256"][str(model)]
    pins.update({str(path): sha(path) for path in (bench, baseline_path, Path(__file__), *vector_paths)})
    for vector in vectors:
        pins.update(vector["files_sha256"])
    verify(pins)
    report_dir = case / "trained_metadata"
    report_dir.mkdir()
    results = []
    with tempfile.TemporaryDirectory(dir=report_dir, prefix="native_") as temporary:
        work = Path(temporary)
        rewritten = work / bench.name
        rewritten.write_text(test_bench(bench.read_text()))
        for label, fault in (("trained", 0), ("write_fault", 1), ("last_write_fault", 2), ("bad_replay", 3), ("short", 4), ("mutant", 0)):
            logs = report_dir / label
            logs.mkdir()
            wait_for_shared_memory(label, 17)
            positive = label != "mutant"
            command = ["/opt/cadence/bin/xrun", "-64bit", "-sv", "+define+UNIT_DELAY", "-top", TOP,
                       "-xmlibdirname", str(work / "xcelium.d"), "-clean", *map(str, [*sources, model, rewritten]),
                       f"+INPUT={vectors[0]['fixture']}", f"+EXPECTED={vectors[1]['fixture']}", f"+FAULT={fault}"]
            if not positive:
                command.append("+BAD_OUTLIER_RESPONSE")
            result = shared_memory_stage(label, logs, command, 120, 0 if positive else 2)
            console = logs / "console.log"
            text = console.read_text()
            strips = 34 if fault == 4 else 4096
            expected = f"WAC_OUTLIER_TRAINED_PASS fault={fault} strips={strips} codes={8*strips}"
            if positive:
                assert text.splitlines().count(expected) == 1 and not re.search(r"\*[EF],", text)
                old = baseline["runs"][fault]
                assert f"mask_bits={old['mask_bits']} sign_reads={old['sign_reads']}" in text
            else:
                assert "WAC_OUTLIER_TRAINED_METADATA strip=0 lane=0" in text and expected not in text
            results.append(dict(label=label, native=result))
            print(label, expected if positive else "corrupted metadata rejected", flush=True)
    verify(pins)
    record = dict(state="trained_metadata_activation_and_masks_verified_at_simd_interface", cases=results,
                  bench_sha256=sha(bench), source_sha256=pins)
    (report_dir / "receipt.json").write_text(json.dumps(record, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", type=Path)
    run(parser.parse_args().case.resolve())
