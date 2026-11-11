"""Check compute-to-softmax input-memory ownership with installed memory models."""

import argparse
import gzip
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path

from prepare_tri_oracle_wac_shared_imem import TOP as CORE, prepare
from run_tri_oracle_wac_softmax_imem import ADAPTER, ARCHIVE, MODEL, MONITOR, REFERENCE, ROOT, RTL, TOP as ROW_BENCH
from run_tri_oracle_aggregator_softmax import require_reference_hash, sha
from run_tri_oracle_softmax_iomem import replace
from test_tri_oracle_sram_memory_compute import models

BENCH = "tri_oracle_wac_shared_imem_tb"
OWNER = RTL / "tri_oracle_wac_imem_owner.sv"
CORNERS = ("tt1v25c", "ssg0p9v125c", "ffg1p05vm40c")
MACROS = ((MODEL, "inputs", 2), ("TS5N28HPCPSVTA32X128M2FW", "weights", 16),
          ("TS5N28HPCPSVTA32X128M2FW", "masks", 2), ("TS6N28HPCPSVTA16X128M2F", "outputs", 8))
SUCCESS = "WAC_IMEM_HANDOFF_PASS drained=4 retained_results=4 softmax_outputs=3 resumed_results=2"


def xcelium(work, top, units, *plusargs):
    run = subprocess.run([
        "/opt/cadence/bin/xrun", "-64bit", "-sv", "-define", "UNIT_DELAY", "-nospecify", "-notimingchecks",
        "-sequdp_nba_delay", "-xmerror", "RECOME", "-top", top, *map(str, units), *plusargs,
    ], cwd=work, capture_output=True, text=True, timeout=120)
    return run.returncode, run.stdout + run.stderr


def dependencies(corner, owner):
    return [*(ROOT / path for path in models(corner)), RTL / "tri_oracle_pe_array.sv", ADAPTER, owner]


def run_handoff(owner, corner, expected_fault):
    with tempfile.TemporaryDirectory(prefix="wac_shared_imem_", dir=ROOT / ".cache") as directory:
        work = Path(directory)
        core, simd = prepare(work)
        probe = work / "memory_probe.sv"
        probe.write_text("""module tri_oracle_wac_imem_probe #(parameter string MASTER="") ();
    initial $display("WAC_MEMORY %s %m", MASTER);
endmodule
""" + "".join(f'bind {master} tri_oracle_wac_imem_probe #(.MASTER("{master}")) probe ();\n'
               for master in dict.fromkeys(master for master, _, _ in MACROS)))
        status, log = xcelium(work, BENCH, [*dependencies(corner, owner), core, simd, RTL / f"{BENCH}.sv", probe])
    if expected_fault:
        assert status == 2 and expected_fault in log and SUCCESS not in log, log[-5000:]
        print(corner, "REJECTED", expected_fault)
        return
    assert status == 0 and not re.search(r"\*[EF],", log), log[-5000:]
    lines = log.splitlines()
    assert lines.count(SUCCESS) == 1
    observed = [tuple(line.split()[1:]) for line in lines if line.startswith("WAC_MEMORY ")]
    expected = {
        (master, f"{BENCH}.dut.{bank}[{index}].probe")
        for master, bank, count in MACROS
        for index in range(count)
    }
    assert len(observed) == len(expected) and set(observed) == expected, expected ^ set(observed)
    print(corner, SUCCESS, "compiled_memories=28")


def run_archive(corner):
    reference = json.loads(REFERENCE.read_text())
    assert sha(ARCHIVE) == reference["native_evidence_sha256"]
    original = RTL / "tri_oracle_proportional_softmax.sv"
    bench = RTL / f"{ROW_BENCH}.sv"
    for path in (original, bench):
        require_reference_hash(path, reference)
    with gzip.open(ARCHIVE, "rt") as stream:
        vectors = json.load(stream)["vectors"]
    assert hashlib.sha256(vectors.encode()).hexdigest() == reference["fixture_sha256"]
    ports = original.read_text().split("module tri_oracle_proportional_softmax (", 1)[1].split(");", 1)[0]
    wrapper = f"""`timescale 1ns/1ps
module wac_softmax_archive ({ports});
    {CORE} core (
        .clk, .rst_n, .load_valid(1'b0), .load_ready(), .load_kind('0), .load_addr('0), .load_data('0),
        .load_row_enable('0), .load_error(), .cmd_valid(1'b0), .cmd_ready(), .cmd_weight('0), .cmd_activation('0),
        .cmd_mask('0), .cmd_output('0), .cmd_accumulate(1'b0), .done_valid(), .done_output(),
        .read_valid(1'b0), .read_output('0), .result_valid(), .result_data(),
        .activation_reloaded(1'b0), .activation_reload_required(),
        .softmax_cfg_valid(cfg_valid), .softmax_cfg_ready(cfg_ready), .softmax_cfg_length(cfg_length),
        .softmax_cfg_error(cfg_error), .softmax_in_valid(in_valid), .softmax_in_ready(in_ready),
        .softmax_in_score(in_score), .softmax_in_size(in_size), .softmax_out_valid(out_valid),
        .softmax_out_ready(out_ready), .softmax_out_probability(out_probability), .softmax_out_last(out_last)
    );
endmodule
"""
    text = replace(bench.read_text(), "tri_oracle_proportional_softmax dut", "wac_softmax_archive dut")
    text = replace(text, 'if (out_valid || in_ready || !cfg_ready) $fatal(1, "SOFTMAX_RESET_DRAIN");\n        rst_n = 1;',
                   '''if (out_valid || in_ready || cfg_ready) $fatal(1, "SOFTMAX_RESET_DRAIN");
        rst_n = 1;
        #1;
        if (!cfg_ready) $fatal(1, "SOFTMAX_RESET_RELEASE");''')
    monitor = MONITOR.replace("dut.mem_", "dut.core.imem_").replace("dut.simd.", "dut.core.simd.")
    with tempfile.TemporaryDirectory(prefix="wac_shared_archive_", dir=ROOT / ".cache") as directory:
        work = Path(directory)
        core, simd = prepare(work)
        top = work / "wrapper.sv"
        replay = work / "bench.sv"
        top.write_text(wrapper)
        replay.write_text(replace(text, "endmodule", monitor + "endmodule"))
        (work / "vectors.txt").write_text(vectors)
        status, log = xcelium(work, ROW_BENCH, [*dependencies(corner, OWNER), core, simd, top, replay],
                              "+FIXTURE=vectors.txt")
    assert status == 0 and not re.search(r"\*[EF],", log), log[-5000:]
    assert log.splitlines().count(reference["simulation_marker"]) == 1, log[-5000:]
    print(corner, reference["simulation_marker"])


def run_matrix(corner):
    bench = (RTL / "tri_oracle_sram_memory_hazards_tb.sv").read_text()
    bench = replace(bench, "tri_oracle_memory_compute dut (.*);", f"""{CORE} dut (
    .load_ready(), .activation_reloaded(rst_n), .activation_reload_required(),
    .softmax_cfg_valid(1'b0), .softmax_cfg_ready(), .softmax_cfg_error(), .softmax_cfg_length('0),
    .softmax_in_valid(1'b0), .softmax_in_ready(), .softmax_in_score('0), .softmax_in_size('0),
    .softmax_out_ready(1'b0), .softmax_out_valid(), .softmax_out_last(), .softmax_out_probability(), .*
  );""")
    bench = replace(bench, "endmodule", """  int inflight;
  always @(posedge clk) begin
    if (!rst_n) inflight = 0;
    else begin
      if (dut.input_owner.outstanding !== 3'(inflight))
        $fatal(1, "WAC_IMEM_OUTSTANDING_COUNT got=%0d expected=%0d", dut.input_owner.outstanding, inflight);
      inflight += int'(cmd_valid && cmd_ready) - int'(done_valid);
      if (inflight < 0 || inflight > 7) $fatal(1, "WAC_IMEM_OUTSTANDING_CAPACITY");
    end
  end
endmodule""")
    with tempfile.TemporaryDirectory(prefix="wac_matrix_regression_", dir=ROOT / ".cache") as directory:
        work = Path(directory)
        core, simd = prepare(work)
        replay = work / "bench.sv"
        replay.write_text(bench)
        status, log = xcelium(work, "tri_oracle_memory_compute_tb",
                              [*dependencies(corner, OWNER), core, simd, replay])
    assert status == 0 and not re.search(r"\*[EF],", log), log[-5000:]
    markers = [line for line in log.splitlines() if line.startswith("PASS:")]
    assert len(markers) == 2 and markers[-1].startswith("PASS: completion-read throughput and reset retention"), log[-5000:]
    print(corner, markers[-1])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corner", choices=CORNERS)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--fault", choices=("early-grant", "skip-reload", "unsafe-reset"))
    mode.add_argument("--archive", action="store_true")
    mode.add_argument("--matrix", action="store_true")
    args = parser.parse_args()
    if args.fault:
        old, new, failure = {
            "early-grant": (" && outstanding == 0", "", "WAC_IMEM_EARLY_GRANT issued=6 completed=2"),
            "skip-reload": (" && !activation_reload_required", "", "WAC_IMEM_COMPUTE_BEFORE_RELOAD"),
            "unsafe-reset": ("\n            activation_reload_required <= 1'b1;",
                             "\n            activation_reload_required <= 1'b0;",
                             "WAC_IMEM_RESET_RELEASED_STALE_ACTIVATIONS"),
        }[args.fault]
        with tempfile.TemporaryDirectory(dir=ROOT / ".cache", prefix="wac_imem_fault_") as directory:
            broken = Path(directory) / OWNER.name
            broken.write_text(replace(OWNER.read_text(), old, new))
            run_handoff(broken, args.corner or CORNERS[0], failure)
    elif args.archive:
        run_archive(args.corner or CORNERS[0])
    elif args.matrix:
        run_matrix(args.corner or CORNERS[0])
    else:
        for corner in (args.corner,) if args.corner else CORNERS:
            run_handoff(OWNER, corner, None)


if __name__ == "__main__":
    main()
