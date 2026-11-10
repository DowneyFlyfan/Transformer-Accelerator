"""Run the complete trained layer from hardware-generated activation bytes."""

import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time

from prepare_tri_oracle_batch400_bench import hierarchy_bench
from prepare_tri_oracle_batch406_bench import learned_bench
from run_tri_oracle_batch396_masks import GIB, check_memory, sha256
from run_tri_oracle_batch406_learned_frame import native_command, source_files, write_bundle
from tri_oracle_process_guard import terminate_process_group


ROOT = Path(__file__).resolve().parents[1]
TOKENS, HIDDEN, INTERMEDIATE = 16, 2048, 5632


def trained_bench():
    source = learned_bench()

    def replace(before, after):
        nonlocal source
        assert source.count(before) == 1, before
        source = source.replace(before, after)

    replace("  string fixture;", """  string fixture,raw_fixture,learned_fixture,intermediate_fixture,progress_path;
  integer progress_file;
  logic [127:0] fixture_residual[TOKENS*(HIDDEN/8)];
  logic [(HIDDEN/2)-1:0] fixture_outlier_pairs[TOKENS];
  logic [15:0] fixture_gamma[HIDDEN];
  logic [7:0] fixture_activation_shifts[TOKENS];
  int expected_sign_token=0,expected_sign_group=0,expected_sign_pair=0;
  bit expected_sign_up=0;""")
    replace("    // Two equal, opposite nonzero residuals", """    if(TRAINED)return fixture_keep[token*INTERMEDIATE+channel]!=0;
    // Two equal, opposite nonzero residuals""")
    replace("    for(int lane=0;lane<8;lane++)raw_strip", """    if(TRAINED)return fixture_residual[token*(HIDDEN/8)+strip];
    for(int lane=0;lane<8;lane++)raw_strip""")
    replace("    return ((feature*13)%23-11)*97+1024;",
        """    if(TRAINED)return int'($signed(fixture_gamma[feature]));
    return ((feature*13)%23-11)*97+1024;""")
    replace("cfg_up_sign_base=UP_SIGN_BASE;cfg_epsilon_q16=0;",
        "cfg_up_sign_base=UP_SIGN_BASE;cfg_epsilon_q16=TRAINED ? 32'd43980465 : 32'd0;")
    replace("cfg_activation_shifts[6*token+:6]=6'(14+token%2);",
        "cfg_activation_shifts[6*token+:6]=TRAINED ? fixture_activation_shifts[token][5:0] : 6'(14+token%2);")
    # The accepted activation/scratch regions are immutable throughout a read.
    replace("  always_comb begin: read_word", "  always @(read_address or read_beat or read_active) begin: read_word")
    replace("      if(activation_acks!=TOKENS*HIDDEN)$fatal(1,\"BATCH406_READ_BEFORE_ACTIVATION_ACK\");\n", "")
    replace("    cycle<=cycle+1;", """    cycle<=cycle+1;
    if(req_valid && activation_acks!=TOKENS*HIDDEN)$fatal(1,"BATCH408_READ_OFFER_BEFORE_ACTIVATION_ACK");""")
    replace("    int offset,row,token,expected_start,expected_token,expected_count;",
        """    int offset,row,token,expected_start,expected_token,expected_count;
    logic [63:0] expected_sign_address;""")
    replace("        sign_requests++;", """        if(TRAINED)begin
          while(expected_sign_pair<HIDDEN/2 &&
                !fixture_outlier_pairs[expected_sign_token][expected_sign_pair])expected_sign_pair++;
          if(expected_sign_pair==HIDDEN/2 || expected_sign_group>=INTERMEDIATE/32)
            $fatal(1,"BATCH408_UNEXPECTED_SIGN_READ");
          expected_sign_address=(expected_sign_up ? UP_SIGN_BASE : GATE_SIGN_BASE)+
            (64'(expected_sign_group)*64'(HIDDEN/2)+64'(expected_sign_pair))*8;
          if(req_address!==expected_sign_address)
            $fatal(1,"BATCH408_SIGN_ADDRESS got=%h expected=%h",req_address,expected_sign_address);
          if(expected_sign_up)begin
            expected_sign_pair++;
            while(expected_sign_pair<HIDDEN/2 &&
                  !fixture_outlier_pairs[expected_sign_token][expected_sign_pair])expected_sign_pair++;
            if(expected_sign_pair==HIDDEN/2)begin
              expected_sign_pair=0;
              if(expected_sign_token==TOKENS-1)begin expected_sign_token=0;expected_sign_group++;end
              else expected_sign_token++;
            end
          end
          expected_sign_up=!expected_sign_up;
        end
        sign_requests++;""")
    replace("        valid_masks++;", """        $fdisplay(progress_file,"BATCH408_MASK_ACCEPTED start=%0d count=%0d cycle=%0d",
          dut.packet_mask_start,dut.compute_mask_count,cycle);
        $fflush(progress_file);
        valid_masks++;""")
    replace("        activation_acks+=write_length*8;", """        activation_acks+=write_length*8;
        if(activation_acks%HIDDEN==0)begin
          $fdisplay(progress_file,"BATCH408_ACTIVATION_COMMITTED token=%0d total_bytes=%0d",
            activation_acks/HIDDEN-1,activation_acks);
          $fflush(progress_file);
        end""")
    replace("""      if(expected_token==TOKENS-1)$display("BATCH406_OUTPUT_TILE start=%0d count=%0d",expected_start,expected_count);""",
        """      if(expected_token==TOKENS-1)begin
        $fdisplay(progress_file,"BATCH408_OUTPUT_TILE start=%0d count=%0d cycle=%0d",
          expected_start,expected_count,cycle);
        $fflush(progress_file);
      end""")
    replace("    real energy,scaled;", """    real energy,scaled;
    if(!$value$plusargs("PROGRESS=%s",progress_path))$fatal(1,"BATCH408_PROGRESS_REQUIRED");
    progress_file=$fopen(progress_path,"w");
    if(!progress_file)$fatal(1,"BATCH408_PROGRESS_OPEN");
    $fdisplay(progress_file,"BATCH408_START");$fflush(progress_file);""")
    replace('      if(!$value$plusargs("FIXTURE=%s",fixture))$fatal(1,"BATCH406_FIXTURE_REQUIRED");',
        """      if(!$value$plusargs("FIXTURE=%s",fixture) || !$value$plusargs("RAW_FIXTURE=%s",raw_fixture) ||
         !$value$plusargs("LEARNED_FIXTURE=%s",learned_fixture) ||
         !$value$plusargs("INTERMEDIATE_FIXTURE=%s",intermediate_fixture))
        $fatal(1,"BATCH408_FIXTURES_REQUIRED");
      $readmemh({raw_fixture,"/raw.hex"},fixture_residual);
      $readmemh({raw_fixture,"/outlier_pairs.hex"},fixture_outlier_pairs);
      $readmemh({learned_fixture,"/gamma.hex"},fixture_gamma);
      $readmemh({learned_fixture,"/shifts.hex"},fixture_activation_shifts);""")
    replace('$readmemh({fixture,"/activation.hex"},fixture_activation);',
            '$readmemh({learned_fixture,"/activation.hex"},fixture_activation);')
    replace('$readmemh({fixture,"/intermediate.hex"},fixture_intermediate);',
            '$readmemh({intermediate_fixture,"/intermediate.hex"},fixture_intermediate);')
    replace('$readmemh({fixture,"/expected.hex"},fixture_output);',
            '$readmemh({learned_fixture,"/expected.hex"},fixture_output);')
    replace("        for(int channel=0;channel<INTERMEDIATE;channel++)golden_down", """        for(int feature=0;feature<HIDDEN;feature++)
          activation_golden[token][feature]=int'($signed(fixture_activation[token*HIDDEN+feature]));
        for(int channel=0;channel<INTERMEDIATE;channel++)golden_down""")
    replace("    repeat(3)@(negedge clk);rst_n=1;configure();", """    $fdisplay(progress_file,"BATCH408_FIXTURES_LOADED");$fflush(progress_file);
    repeat(3)@(negedge clk);rst_n=1;configure();""")
    replace("    if(sign_requests!=TOKENS*(INTERMEDIATE/32)*4 || valid_masks!=GATE_GROUPS || abort_masks!=0 ||",
        """    if((TRAINED ? (sign_requests!=55616 || expected_sign_group!=INTERMEDIATE/32 ||
                   expected_sign_token!=0 || expected_sign_up) : sign_requests!=TOKENS*(INTERMEDIATE/32)*4) ||
        valid_masks!=GATE_GROUPS || abort_masks!=0 ||""")
    replace("    $display(\"BATCH406_PASS tokens=", """    $fdisplay(progress_file,"BATCH408_DONE");$fflush(progress_file);$fclose(progress_file);
    $display("BATCH406_PASS tokens=""")
    return source.replace("BATCH406_", "BATCH408_")


def main():
    records = {
        "FIXTURE": ROOT / "records/batch389_fixture_preparation.json",
        "RAW_FIXTURE": ROOT / "records/batch396_mask_fixture.json",
        "LEARNED_FIXTURE": ROOT / "records/batch403_activation_precision.json",
        "INTERMEDIATE_FIXTURE": ROOT / "records/batch407_learned_fixture.json",
    }
    fixtures = {name: json.loads(path.read_text()) for name, path in records.items()}
    reference = fixtures["INTERMEDIATE_FIXTURE"]
    assert reference["state"] == "complete_learned_layer_golden_fixed_point_cpu_cuda_equal"
    assert (reference["tokens"], reference["hidden"], reference["intermediate"]) == (TOKENS, HIDDEN, INTERMEDIATE)
    for name, path in records.items():
        if name != "INTERMEDIATE_FIXTURE":
            assert reference["source_sha256"][str(path)] == sha256(path)
    literal_path = ROOT / "records/batch406_learned_result.json"
    literal = json.loads(literal_path.read_text())
    assert literal["state"] == "generated_activations_consumed_by_joined_feedforward_verified"
    sources, evidence = source_files()
    evidence += [literal_path, ROOT / "syn/run_tri_oracle_batch406_learned_frame.py", *records.values(), Path(__file__)]
    hashes = {str(path): sha256(path) for path in (*sources, *evidence)}
    assert all(literal["source_sha256"][path] == digest for path, digest in hashes.items()
               if path in literal["source_sha256"])
    for fixture in fixtures.values():
        hashes.update(fixture["files_sha256"])
    assert all(sha256(Path(path)) == digest for path, digest in hashes.items())
    check_memory(14 * GIB)
    directory = ROOT / ".cache/physical/simulation/batch408_trained_learned"
    output = ROOT / "records/batch408_trained_learned_result.json"
    assert not directory.exists() and not output.exists()
    directory.mkdir()
    work = directory / "native"
    work.mkdir()
    log = directory / "trained.log"
    progress = directory / "progress.log"
    bundle = write_bundle(work, sources, trained_bench(), hierarchy_bench())
    command = native_command(work, bundle, "0-7", {
        "TOKENS": TOKENS, "HIDDEN": HIDDEN, "INTERMEDIATE": INTERMEDIATE, "OUTPUTS": HIDDEN, "TRAINED": 1,
    }) + [f"+{name}={fixture['fixture']}" for name, fixture in fixtures.items()] + [f"+PROGRESS={progress}"]
    result = {
        "state": "starting", "scope": __doc__, "supervisor_pid": os.getpid(), "command": command,
        "source_sha256": hashes, "bench_sha256": sha256(work / "bench.sv"),
        "log": str(log), "progress": str(progress), "trained_learned_frame_verified": False,
        "full_paper_results_matched": False,
    }
    began = time.monotonic()
    stopped = False

    def stop(_number, _frame):
        nonlocal stopped
        stopped = True

    def save(**changes):
        result.update(changes, elapsed_seconds=time.monotonic() - began)
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
            print(f"BATCH408_STARTED group={child.pid}", flush=True)
            last = 0.0
            while child.poll() is None:
                check_memory(8 * GIB)
                elapsed = time.monotonic() - began
                assert not stopped and elapsed < 10800, "Trained learned frame stopped or timed out"
                if elapsed - last >= 10:
                    text = progress.read_text() if progress.exists() else ""
                    save(activation_tokens_committed=text.count("BATCH408_ACTIVATION_COMMITTED "),
                         mask_packets_accepted=text.count("BATCH408_MASK_ACCEPTED "),
                         output_tiles_retired=text.count("BATCH408_OUTPUT_TILE "))
                    last = elapsed
                time.sleep(0.5)
        text = log.read_text()
        assert child.returncode == 0, f"Trained learned frame failed: {log}"
        assert not re.search(r"\*(?:E|F),|\*ERROR|Simulation terminated via \$fatal", text)
        assert text.splitlines().count("BATCH357_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=602") == 1
        milestones = progress.read_text()
        assert milestones.splitlines()[-1] == "BATCH408_DONE"
        activation_tokens = re.findall(r"^BATCH408_ACTIVATION_COMMITTED token=(\d+) total_bytes=(\d+)$", milestones, re.M)
        assert [tuple(map(int, item)) for item in activation_tokens] == [(t, HIDDEN * (t + 1)) for t in range(TOKENS)]
        for marker, width, bound in (("MASK_ACCEPTED", 80, INTERMEDIATE), ("OUTPUT_TILE", 160, HIDDEN)):
            packets = re.findall(rf"^BATCH408_{marker} start=(\d+) count=(\d+) cycle=\d+$", milestones, re.M)
            assert [tuple(map(int, item)) for item in packets] == [
                (start, min(width, bound - start)) for start in range(0, bound, width)]
        inv, = re.findall(r"^BATCH408_PASS (.+)$", text, re.M)
        inventory = {key: int(value) for key, value in (item.split("=") for item in inv.split())}
        assert tuple(inventory[key] for key in ("tokens", "hidden", "intermediate", "outputs", "fault", "trained")) == (
            TOKENS, HIDDEN, INTERMEDIATE, HIDDEN, 0, 1)
        assert (inventory["exact_outputs"], inventory["intermediate_bytes"], inventory["output_packets"]) == (32768, 90112, 208)
        assert text.splitlines().count("BATCH408_ACTIVATION_PASS bytes=32768 bursts=256 normalizations=16") == 1
        assert re.search(r"^BATCH408_SHARED_BUS sign_requests=55616 valid_masks=71 contended_cycles=[1-9]\d*$", text, re.M)
        assert all(sha256(Path(path)) == digest for path, digest in hashes.items())
        terminate_process_group(child)
        shutil.rmtree(work)
        save(state="complete_trained_learned_feedforward_verified", native_exit_status=0, inventory=inventory,
             activation_tokens_committed=16, mask_packets_accepted=71, output_tiles_retired=13,
             temporary_build_removed=True, trained_learned_frame_verified=True,
             log_sha256=sha256(log), progress_sha256=sha256(progress))
        print("BATCH408_VERIFIED activation_bytes=32768 intermediate_bytes=90112 exact_outputs=32768", flush=True)
    except BaseException as error:
        if child is not None:
            terminate_process_group(child)
        shutil.rmtree(work, ignore_errors=True)
        save(state="failed", exception=repr(error), native_exit_status=child.returncode if child else None,
             temporary_build_removed=not work.exists())
        raise


if __name__ == "__main__":
    main()
