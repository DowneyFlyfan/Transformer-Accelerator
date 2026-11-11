"""Verify physical destinations of both vector operations on the twenty-core fabric."""

import argparse
import json
from pathlib import Path
import re
import tempfile

from prepare_tri_oracle_wac_outlier_layer import ROOT, RTL, edit, read, sha, verify
from replay_mapped_cluster_fixture import shared_memory_stage, wait_for_shared_memory
from run_tri_oracle_wac_softmax_routes import MARKER, TOP, destinations

OUTLIER_MARKER = "WAC_OUTLIER_ROUTES_PASS cores=20 invalid_destinations=12"
OUTLIER_ROUTE = re.compile(
    rf"WAC_OUTLIER_ROUTE_TRANSFER {TOP}\.fabric\.clusters\[([0-4])\]\.unit\.selected_bank([0-4])\.block_instance"
    r"\.source_cluster\.implementation\.cores\[([0-3])\]\.compute\.simd\.route_witness owner_code=(\d+)"
)


def bench_text(text):
    text = edit(text, "            request.cfg_valid = 1;", """            request.cfg_valid = 1;
            request.outlier_valid = 1;""")
    text = edit(text, f'        $display("{MARKER}");', f'''        $display("{MARKER}");
        request = '0;
        request.outlier_valid = 1;
        for (int owner = 0; owner < 20; owner++) begin
            request.owner = 5'(owner);
            request.normalized = {{16'sd32767, -16'sd32768, -16'sd768, -16'sd769,
                                   16'sd768, 16'sd769, -16'sd1, 16'(owner)}};
            @(posedge clk);
            if (response.outlier_valid !== 1'b1 || response.outliers !== 8'hd4 || response.negative !== 8'h72)
                $fatal(1, "WAC_OUTLIER_ROUTE_RESULT owner=%0d", owner);
            @(negedge clk);
        end
        request = '0;
        @(posedge clk);
        if (response.outlier_valid !== 1'b0) $fatal(1, "WAC_OUTLIER_ROUTE_IDLE");
        $display("{OUTLIER_MARKER}");''')
    text = edit(text, "    input logic [10:0] cfg_length\n", """    input logic [10:0] cfg_length,
    input logic outlier_valid,
    input logic [127:0] metadata_values
""")
    return edit(text, '        $display("WAC_ROUTE_TRANSFER %m length=%0d", cfg_length);',
                '        $display("WAC_ROUTE_TRANSFER %m length=%0d", cfg_length);\n'
                '    always @(posedge clk) if (rst_n && outlier_valid)\n'
                '        $display("WAC_OUTLIER_ROUTE_TRANSFER %m owner_code=%0d", metadata_values[15:0]);')


def outlier_destinations(log):
    observed = {}
    for line in log.splitlines():
        if line.startswith("WAC_OUTLIER_ROUTE_TRANSFER "):
            match = OUTLIER_ROUTE.fullmatch(line)
            assert match, line
            cluster, selected, core, owner = map(int, match.groups())
            assert cluster == selected and owner not in observed, line
            observed[owner] = (cluster, core)
    assert set(observed) == set(range(20))
    return observed


def run(case):
    prepared = read(case / "receipt.json")
    assert prepared["outlier_owner"] == "core_simd_round_robin" and prepared["memory_models"] == "vendor"
    bundle = case / "bundle.sv"
    source = RTL / f"{TOP}.sv"
    inputs = prepared["input_sha256"].copy()
    inputs.update({str(path): sha(path) for path in (source, Path(__file__))})
    verify(inputs)
    report = case / "outlier_routes"
    report.mkdir()
    with tempfile.TemporaryDirectory(dir=report, prefix="route_") as temporary:
        work = Path(temporary)
        bench = work / source.name
        bench.write_text(bench_text(source.read_text()))
        cluster = case / "tri_oracle_sram_compute_cluster.sv"
        mutant = work / cluster.name
        mutant.write_text(edit(cluster.read_text(), "softmax_request.owner[1:0]",
                               "(softmax_request.owner[1:0] ^ 2'b01)", 2))
        mutant_bundle = work / "bundle.sv"
        mutant_bundle.write_text(edit(bundle.read_text(), str(cluster), str(mutant)))
        for wrong, variant in enumerate((bundle, mutant_bundle)):
            out = report / ("wrong_owner" if wrong else "positive")
            out.mkdir()
            wait_for_shared_memory("outlier fabric destinations", 17)
            shared_memory_stage("outlier fabric destinations", out, ["/opt/cadence/bin/xrun", "-64bit", "-sv",
                "-nospecify", "-notimingchecks", "-sequdp_nba_delay", "-xmerror", "RECOME", "-top", TOP,
                str(variant), str(bench)], 180, 0)
            log = (out / "console.log").read_text()
            assert log.splitlines().count(MARKER) == log.splitlines().count(OUTLIER_MARKER) == 1
            assert destinations(log) == {head: ((head % 20)//4, (head % 4) ^ wrong) for head in range(32)}
            assert outlier_destinations(log) == {owner: (owner//4, (owner % 4) ^ wrong) for owner in range(20)}
            print("Wrong physical owner detected on all 20 cores" if wrong else OUTLIER_MARKER, flush=True)
    verify(inputs)
    (report / "receipt.json").write_text(json.dumps({"state": "twenty_core_outlier_destinations_verified",
        "cases": 20, "invalid_owners": 12, "wrong_owner_detected": True, "input_sha256": inputs}, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", type=Path)
    run(parser.parse_args().case.resolve())
