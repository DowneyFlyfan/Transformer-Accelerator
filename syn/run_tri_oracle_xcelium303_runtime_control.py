"""Verify elaborated-snapshot reuse and runtime plus-argument isolation.

Small simulator-control experiment only; it does not exercise accelerator RTL.
All three phases use the scheduling and eight-worker options qualified in274.
"""
import datetime
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

from tri_oracle_process_guard import terminate_process_group


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def available():
    return int(next(line.split()[1] for line in Path("/proc/meminfo").read_text().splitlines()
                    if line.startswith("MemAvailable:")))*1024


def anonymous():
    return int(dict(line.split() for line in Path("/sys/fs/cgroup/memory.stat").read_text().splitlines())["anon"])


def library_files(folder):
    return {str(path.relative_to(folder)): sha(path) for path in folder.rglob("*") if path.is_file()}


def main():
    root = Path(__file__).resolve().parents[1]
    result = root/"records/xcelium303_snapshot_runtime_control.json"
    assert not result.exists()
    assert available() > 14*1024**3 and anonymous() < 256*1024**2
    assert any(os.environ.get(name) for name in ["LM_LICENSE_FILE", "CDS_LIC_FILE"])
    start = time.monotonic()
    stop = False
    def requested(number, frame):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGTERM, requested)
    signal.signal(signal.SIGINT, requested)
    text = """`timescale 1ns/1ps
module tri_oracle_runtime303_tb;
  logic clk=0;
  integer cycles=0;
  always #5 clk=~clk;
  always @(posedge clk) cycles<=cycles+1;
  initial begin
    integer stream;
    string path;
    if(!$value$plusargs("RESULT_FILE=%s",path)) $fatal(1,"RUNTIME303_RESULT_FILE_REQUIRED");
    stream=$fopen(path,"w");
    if(!stream) $fatal(1,"RUNTIME303_RESULT_FILE_OPEN");
    repeat(3) @(negedge clk);
    if(cycles!==3) $fatal(1,"RUNTIME303_SNAPSHOT_STATE_NOT_RESET");
    $fdisplay(stream,"%0d",cycles);
    $fflush(stream);
    if($test$plusargs("CORRUPT_REFERENCE")) $fatal(1,"RUNTIME303_EXPECTED_WRONG_REFERENCE");
    $display("RUNTIME303_PASS cycles=3");
    $fclose(stream);
    $finish;
  end
endmodule
"""
    executable = Path("/opt/cadence/bin/xrun")
    inputs = {str(path):sha(path) for path in [Path(__file__).resolve(),executable,
        root/"syn/tri_oracle_process_guard.py",root/"records/down128_multicore_result.json"]}
    record = dict(state="preparing",started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        supervisor_pid=os.getpid(),source_sha256=inputs,control_source=text,
        scope=__doc__,requested_workers=8,native_runs={},peak_container_anonymous_bytes=0,
        minimum_host_available_bytes=available())
    def save(**changes):
        record.update(changes,elapsed_seconds=time.monotonic()-start)
        temporary=result.with_suffix(".tmp")
        temporary.write_text(json.dumps(record,indent=2)+"\n")
        temporary.replace(result)
    save()
    folder_path = None
    try:
        with tempfile.TemporaryDirectory(prefix="runtime303_",dir=root/".cache/physical") as directory:
            folder = folder_path = Path(directory)
            bench = folder/"runtime_control.sv"
            bench.write_text(text)
            lib = folder/"xcelium.d"
            environment = dict(os.environ,XDG_CACHE_HOME=str(root/".cache"))
            def run(phase,arguments):
                command=[str(executable),"-64bit",*arguments,"-xmlibdirname",str(lib),
                         "-l",str(folder/(phase+".xrun.log")),"-history_file",str(folder/(phase+".history"))]
                log=root/"records"/("xcelium303_"+phase+"_native.log")
                assert not log.exists()
                began=time.monotonic()
                with log.open("w") as stream:
                    child=subprocess.Popen(command,cwd=folder,stdin=subprocess.DEVNULL,
                        stdout=stream,stderr=subprocess.STDOUT,start_new_session=True,env=environment)
                    save(state="native_"+phase+"_running",native_process_group=child.pid,command=command)
                    try:
                        while child.poll() is None:
                            current=anonymous();host=available()
                            record["peak_container_anonymous_bytes"]=max(record["peak_container_anonymous_bytes"],current)
                            record["minimum_host_available_bytes"]=min(record["minimum_host_available_bytes"],host)
                            assert not stop and time.monotonic()-began < 180,"Runtime-control wall/stop guard"
                            assert host>10*1024**3 and current<2*1024**3,"Runtime-control resource guard"
                            time.sleep(.1)
                    finally:
                        terminate_process_group(child,log_argument=str(folder/(phase+".xrun.log")))
                content=log.read_text(errors="replace")
                record["native_runs"][phase]=dict(command=command,native_exit_status=child.returncode,
                    elapsed_seconds=time.monotonic()-began,console_sha256=sha(log))
                save()
                return child.returncode,content
            code,content=run("elaborate",["-sv","-xmerror","RECOME","-sequdp_nba_delay",
                "-mce","-mce_sim_thread_count","8","-mce_build_thread_count","8",
                "-elaborate","-top","tri_oracle_runtime303_tb",str(bench)])
            assert code==0 and "Writing initial simulation snapshot:" in content,content[-3000:]
            compiled=library_files(lib)
            assert compiled
            for phase,corrupt in [("wrong_reference",True),("positive",False)]:
                output=folder/(phase+".txt")
                args=["-R","-mce","-mce_sim_thread_count","8",
                      "+RESULT_FILE="+str(output)]
                if corrupt: args.append("+CORRUPT_REFERENCE")
                code,content=run(phase,args)
                assert output.read_text().strip()=="3"
                if corrupt:
                    assert code!=0 and "RUNTIME303_EXPECTED_WRONG_REFERENCE" in content
                    assert "RUNTIME303_PASS cycles=3" not in content
                else:
                    assert code==0 and "RUNTIME303_PASS cycles=3" in content
                current=library_files(lib)
                record.setdefault("library_changes",{})[phase]={
                    "changed":sorted(name for name,value in compiled.items() if current.get(name)!=value),
                    "added":sorted(set(current)-set(compiled)),"removed":sorted(set(compiled)-set(current))}
                save()
            assert all(sha(name)==digest for name,digest in inputs.items())
            save(state="snapshot_reuse_and_runtime_reference_control_passed",
                both_runs_start_from_initial_state=True,runtime_plus_arguments_isolated=True,
                elaborated_library_files=compiled,temporary_build_removed=False)
        save(temporary_build_removed=not folder_path.exists())
    except BaseException as error:
        save(state="failed",exception=repr(error),temporary_build_removed=folder_path is not None and not folder_path.exists())
        raise
    print(json.dumps({key:value for key,value in record.items() if key not in ["source_sha256","control_source","elaborated_library_files"]},indent=2))


if __name__ == "__main__":
    main()
