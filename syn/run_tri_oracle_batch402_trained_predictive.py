"""Verify the joined predictor and feedforward fabric on the full trained layer.

The predictor consumes the original captured residuals and original quantized
weight signs. Prepared activation codes and the local numeric policy are still
inputs. Expected mask, intermediate and output words only enter the scoreboard.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time

from prepare_tri_oracle_batch400_bench import hierarchy_bench, integrated_bench
from run_tri_oracle_batch396_masks import GIB, check_memory, sha256
from tri_oracle_process_guard import terminate_process_group


ROOT = Path(__file__).resolve().parents[1]
TOP = "tri_oracle_batched400_predictive_tb"
TOKENS, HIDDEN, INTERMEDIATE, OUTPUTS = 16, 2048, 5632, 2048


def trained_bench():
    source = integrated_bench()

    def replace(before, after):
        nonlocal source
        assert source.count(before) == 1, before
        source = source.replace(before, after)

    replace("  string fixture;", """  string fixture,prediction_fixture;
  logic [127:0] fixture_residual[TOKENS*(HIDDEN/8)];
  logic [(HIDDEN/2)-1:0] fixture_outlier_pairs[TOKENS];
  int sign_token=0,sign_group=0,sign_pair=0;
  bit sign_up=0;""")
    replace("    // Two equal, opposite nonzero residuals", """    if(TRAINED)return fixture_keep[token*INTERMEDIATE+channel]!=0;
    // Two equal, opposite nonzero residuals""")
    replace("    raw_strip=0;", """    if(TRAINED)return fixture_residual[token*(HIDDEN/8)+strip];
    raw_strip=0;""")
    replace("cfg_up_sign_base=UP_SIGN_BASE;cfg_epsilon_q16=0;",
            "cfg_up_sign_base=UP_SIGN_BASE;cfg_epsilon_q16=TRAINED ? 32'd43980465 : 32'd0;")
    # Operands are immutable during accepted reads. Trigger on the bus beat
    # rather than adding every element of the large operand arrays to its wait set.
    replace("  always_comb begin: read_word", "  always @(read_address or read_beat or read_active) begin: read_word")
    replace("    int offset,row,token,expected_start,expected_token,expected_count;",
            """    int offset,row,token,expected_start,expected_token,expected_count;
    logic [63:0] expected_sign_address;""")
    replace("        sign_requests++;", """        if(TRAINED)begin
          while(sign_pair<HIDDEN/2 && !fixture_outlier_pairs[sign_token][sign_pair])sign_pair++;
          if(sign_pair==HIDDEN/2 || sign_group>=INTERMEDIATE/32)
            $fatal(1,"BATCH402_UNEXPECTED_SIGN_READ");
          expected_sign_address=(sign_up ? UP_SIGN_BASE : GATE_SIGN_BASE)+
            (64'(sign_group)*64'(HIDDEN/2)+64'(sign_pair))*8;
          if(req_address!==expected_sign_address)
            $fatal(1,"BATCH402_SIGN_ADDRESS got=%h expected=%h",req_address,expected_sign_address);
          if(sign_up)begin
            sign_pair++;
            while(sign_pair<HIDDEN/2 && !fixture_outlier_pairs[sign_token][sign_pair])sign_pair++;
            if(sign_pair==HIDDEN/2)begin
              sign_pair=0;
              if(sign_token==TOKENS-1)begin sign_token=0;sign_group++;end
              else sign_token++;
            end
          end
          sign_up=!sign_up;
        end
        sign_requests++;""")
    replace("        valid_masks++;", """        $display("BATCH402_MASK_ACCEPTED start=%0d count=%0d cycle=%0d",
          dut.packet_mask_start,dut.compute_mask_count,cycle);
        $fflush();
        valid_masks++;""")
    replace("""      if(expected_token==TOKENS-1)$display("BATCH400_OUTPUT_TILE start=%0d count=%0d",expected_start,expected_count);""",
        """      if(expected_token==TOKENS-1)begin
        $display("BATCH402_OUTPUT_TILE start=%0d count=%0d cycle=%0d",expected_start,expected_count,cycle);
        $fflush();
      end""")
    replace('      if(!$value$plusargs("FIXTURE=%s",fixture))$fatal(1,"BATCH400_FIXTURE_REQUIRED");',
        """      if(!$value$plusargs("FIXTURE=%s",fixture) ||
         !$value$plusargs("PREDICTION_FIXTURE=%s",prediction_fixture))$fatal(1,"BATCH402_FIXTURES_REQUIRED");
      $display("BATCH402_LOADING_FIXTURES");$fflush();
      $readmemh({prediction_fixture,"/raw.hex"},fixture_residual);
      $readmemh({prediction_fixture,"/outlier_pairs.hex"},fixture_outlier_pairs);""")
    replace("    repeat(3)@(negedge clk);rst_n=1;configure();", """    $display("BATCH402_FIXTURES_LOADED");$fflush();
    repeat(3)@(negedge clk);rst_n=1;configure();""")
    replace("    if(sign_requests!=TOKENS*(INTERMEDIATE/32)*4 || valid_masks!=GATE_GROUPS || abort_masks!=0 ||",
        """    if((TRAINED ? (sign_requests!=55616 || sign_group!=INTERMEDIATE/32 || sign_token!=0 || sign_up) :
                   (sign_requests!=TOKENS*(INTERMEDIATE/32)*4)) || valid_masks!=GATE_GROUPS || abort_masks!=0 ||""")
    return source.replace("BATCH400_", "BATCH402_")


def main():
    backend_path = ROOT / "records/batch393_literal_result.json"
    backend = json.loads(backend_path.read_text())
    frontend_path = ROOT / "records/batch399_mask_packet_result.json"
    frontend = json.loads(frontend_path.read_text())
    compute_path = ROOT / "records/batch389_fixture_preparation.json"
    compute = json.loads(compute_path.read_text())
    prediction_path = ROOT / "records/batch396_mask_fixture.json"
    prediction = json.loads(prediction_path.read_text())
    assert compute["state"] == "complete_trained_layer_fixture_scalar_cuda_equal"
    assert prediction["state"] == "trained_residuals_and_weight_signs_match_archived_masks"
    assert tuple(compute[key] for key in ("tokens", "input_features", "intermediate_features", "output_features")) == (
        TOKENS, HIDDEN, INTERMEDIATE, OUTPUTS)
    assert tuple(prediction[key] for key in ("tokens", "features", "channels", "epsilon_q16")) == (
        TOKENS, HIDDEN, INTERMEDIATE, 43980465)
    assert prediction["source_sha256"][str(compute_path)] == sha256(compute_path)
    assert compute["predicted_skipped_pairs"] == prediction["skipped_channels"] == 5231
    assert all(count > 0 for count in prediction["outlier_pair_counts"])
    assert 2 * (INTERMEDIATE // 32) * sum(prediction["outlier_pair_counts"]) == 55616
    sources = [Path(path) for path in backend["source_sha256"]
               if path.endswith((".sv", ".v")) and not path.endswith(("_tb.sv", "_hierarchy.sv"))]
    sources.extend(ROOT / "verilog" / (name + ".sv") for name in (
        "tri_oracle_rmsnorm", "tri_oracle_sign_fetch", "tri_oracle_strip_predictor", "tri_oracle_batched_outliers398",
        "tri_oracle_batched_mask_packet399", "tri_oracle_batched_predictive400",
    ))
    tracked = [backend_path, frontend_path, compute_path, prediction_path, Path(__file__),
        ROOT / "verilog/tri_oracle_batched393_tb.sv", ROOT / "verilog/tri_oracle_batch357_hierarchy.sv",
        ROOT / "syn/prepare_tri_oracle_batch400_bench.py", ROOT / "syn/run_tri_oracle_batch396_masks.py",
        ROOT / "syn/tri_oracle_process_guard.py", *sources]
    hashes = compute["files_sha256"] | prediction["files_sha256"] | {str(path): sha256(path) for path in tracked}
    prior = backend["source_sha256"] | frontend["source_sha256"]
    assert all(prior[path] == digest for path, digest in hashes.items() if path in prior)
    assert all(sha256(Path(path)) == digest for path, digest in hashes.items())
    check_memory(14 * GIB)

    directory = ROOT / ".cache/physical/simulation/batch402_trained_predictive"
    output = ROOT / "records/batch402_trained_predictive_result.json"
    assert not directory.exists() and not output.exists()
    directory.mkdir()
    work = directory / "native"
    work.mkdir()
    bench = work / "bench.sv"
    hierarchy = work / "hierarchy.sv"
    bundle = work / "bundle.sv"
    bench.write_text(trained_bench())
    hierarchy.write_text(hierarchy_bench())
    bundle.write_text('`define UNIT_DELAY\n`define TRI_ORACLE_SRAM_CLUSTER_BIND_PUBLIC\n' +
                      "".join(f'`include "{path}"\n' for path in (*sources, bench, hierarchy)))
    log = directory / "trained.log"
    command = [
        "taskset", "-c", "0-7", "/opt/cadence/bin/xrun", "-64bit", "-sv",
        "-xmerror", "RECOME", "-notimingchecks", "-top", TOP, "-top", "tri_oracle_batch357_hierarchy",
        "-xmlibdirname", str(work / "xcelium.d"), "-l", str(work / "native.log"),
        "-history_file", str(work / "history"), str(bundle),
        f"+FIXTURE={compute['fixture']}", f"+PREDICTION_FIXTURE={prediction['fixture']}",
    ]
    for parameter, value in (
        ("TOKENS", TOKENS), ("HIDDEN", HIDDEN), ("INTERMEDIATE", INTERMEDIATE), ("OUTPUTS", OUTPUTS), ("TRAINED", 1),
    ):
        command.extend(("-defparam", f"{TOP}.{parameter}={value}"))
    result = {
        "state": "starting", "scope": __doc__, "supervisor_pid": os.getpid(), "command": command,
        "source_sha256": hashes, "generated_bench_sha256": sha256(bench),
        "generated_hierarchy_sha256": sha256(hierarchy), "log": str(log),
        "trained_joined_frame_verified": False, "full_paper_results_matched": False,
    }
    started = time.monotonic()
    stopped = False

    def stop(_number, _frame):
        nonlocal stopped
        stopped = True

    def save(**changes):
        result.update(changes, elapsed_seconds=time.monotonic() - started)
        temporary = output.with_suffix(".tmp")
        temporary.write_text(json.dumps(result, indent=2) + "\n")
        temporary.replace(output)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    child = None
    save()
    try:
        with log.open("x") as stream:
            child = subprocess.Popen(command, cwd=work, stdout=stream, stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL, start_new_session=True)
            save(state="running", process_group=child.pid)
            print(f"BATCH402_STARTED group={child.pid}", flush=True)
            last = 0.0
            while child.poll() is None:
                check_memory(8 * GIB)
                elapsed = time.monotonic() - started
                assert not stopped and elapsed < 10800, "Joined trained simulation stopped or timed out"
                if elapsed - last >= 10:
                    text = log.read_text()
                    save(
                        mask_packets_accepted=len(re.findall(r"^BATCH402_MASK_ACCEPTED ", text, re.MULTILINE)),
                        output_tiles_retired=len(re.findall(r"^BATCH402_OUTPUT_TILE ", text, re.MULTILINE)),
                    )
                    last = elapsed
                time.sleep(0.5)
        text = log.read_text()
        assert child.returncode == 0, f"Joined trained Xcelium run failed: {log}"
        assert not re.search(r"\*(?:E|F),|\*ERROR|Simulation terminated via \$fatal", text)
        assert text.splitlines().count("BATCH357_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=602") == 1
        mask_packets = [tuple(map(int, pair)) for pair in re.findall(
            r"^BATCH402_MASK_ACCEPTED start=(\d+) count=(\d+) cycle=\d+$", text, re.MULTILINE)]
        output_tiles = [tuple(map(int, pair)) for pair in re.findall(
            r"^BATCH402_OUTPUT_TILE start=(\d+) count=(\d+) cycle=\d+$", text, re.MULTILINE)]
        assert mask_packets == [(start, min(80, INTERMEDIATE - start)) for start in range(0, INTERMEDIATE, 80)]
        assert output_tiles == [(start, min(160, OUTPUTS - start)) for start in range(0, OUTPUTS, 160)]
        pass_line, = re.findall(r"^BATCH402_PASS (.+)$", text, re.MULTILINE)
        inventory = {name: int(value) for name, value in (part.split("=") for part in pass_line.split())}
        assert tuple(inventory[k] for k in ("tokens", "hidden", "intermediate", "outputs", "trained", "fault")) == (
            TOKENS, HIDDEN, INTERMEDIATE, OUTPUTS, 1, 0)
        assert inventory["exact_outputs"] == TOKENS * OUTPUTS
        assert inventory["intermediate_bytes"] == TOKENS * INTERMEDIATE
        assert inventory["output_packets"] == TOKENS * len(output_tiles)
        bus_line, = re.findall(r"^BATCH402_SHARED_BUS sign_requests=(\d+) valid_masks=(\d+) contended_cycles=(\d+)$",
                               text, re.MULTILINE)
        sign_reads, valid_masks, contended_cycles = map(int, bus_line)
        assert sign_reads == 55616 and valid_masks == len(mask_packets) and contended_cycles > 0
        assert all(sha256(Path(path)) == digest for path, digest in hashes.items())
        terminate_process_group(child)
        shutil.rmtree(work)
        save(state="trained_raw_residual_to_feedforward_verified", native_exit_status=0,
             inventory=inventory, sign_reads=sign_reads, contended_cycles=contended_cycles,
             mask_packets_accepted=len(mask_packets), output_tiles_retired=len(output_tiles),
             trained_joined_frame_verified=True, temporary_build_removed=True, log_sha256=sha256(log))
        print("BATCH402_VERIFIED exact_outputs=32768 intermediate_bytes=90112 sign_reads=55616", flush=True)
    except BaseException as error:
        if child is not None:
            terminate_process_group(child)
        shutil.rmtree(work, ignore_errors=True)
        save(state="failed", exception=repr(error), native_exit_status=child.returncode if child else None,
             temporary_build_removed=not work.exists())
        raise


if __name__ == "__main__":
    main()
