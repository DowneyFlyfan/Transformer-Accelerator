"""Verify the complete archived trained layer on the current mapped candidate.

One elaborated image is reused for a wrong-sum counterfactual and the full
2,048-output positive run. This is functional verification within the current
placement step, with prepared normalization/sign inputs and no delay annotation.
It does not advance clock distribution/routing or certify paper accuracy/energy.
Native timing checks are disabled for this functional-only run using the measured
311 simulator control. The full trained workload and unchanged independent
scoreboard remain mandatory; the admission deadline now covers measured cycles.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time

from run_tri_oracle_xcelium303_runtime_control import library_files
from tri_oracle_xcelium308_snapshot import ADMINISTRATIVE, runtime_template, require_runtime_snapshot
from tri_oracle_hierarchy_fingerprint import hierarchy_fingerprint
from tri_oracle_memory_pressure_guard import MemoryPressurePolicy, OwnedProcessPause
from tri_oracle_process_guard import terminate_process_group
from run_tri_oracle_row_guard175_synthesis import memory


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream,"sha256").hexdigest()


def snapshot_digest(files):
    return hashlib.sha256(json.dumps(files,sort_keys=True,separators=(",",":")).encode()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-only",action="store_true")
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    result=root/"records/real310_mapped_pair_result.json"
    out=root/".cache/physical/simulation/real310_mapped_pair"
    assert not result.exists() and not out.exists()
    assert Path("/opt/cadence/bin/xrun").exists(),"Use the main Cadence container with Xcelium"
    control_path=root/"records/xcelium311_snapshot_runtime_control.json"
    assert control_path.exists(),"Snapshot runtime-control311 must finish before the trained mapped pair"
    control=json.loads(control_path.read_text())
    assert control["state"]=="snapshot_reuse_and_runtime_reference_control_passed"
    assert control["both_runs_start_from_initial_state"] and control["runtime_plus_arguments_isolated"]
    assert control["temporary_build_removed"] is True,"Runtime311 control cleanup is incomplete"
    assert set(control["library_changes"])=={"wrong_reference","positive"}
    for changes in control["library_changes"].values():
        assert set(changes)=={"changed","added","removed"}
        assert not changes["added"] and not changes["removed"]
        assert set(changes["changed"])<=ADMINISTRATIVE
    assert control["timing_checks_disabled"] is True
    assert all("-notimingchecks" in run["command"] for run in control["native_runs"].values())
    administrative_template=runtime_template(control)
    admission_path=root/"records/real302_runtime_admission_diagnosis.json"
    admission=json.loads(admission_path.read_text())
    assert admission["state"]=="stopped_before_likely_short_deadline_exhaustion"
    assert admission["next_negative_and_positive_limit_seconds"]==28800
    assert admission["native_functional_result_qualified"] is False
    qualifier_path=root/"records/restore304_preservation_qualification.json"
    qualifier=json.loads(qualifier_path.read_text())
    assert qualifier["state"]=="placed_parent_and_original_full_models_preserved_timing_unqualified"
    restored_path=root/"records/restore295_full_result.json"
    assert qualifier["evidence_sha256"][str(restored_path)]==sha(restored_path)
    restored=json.loads(restored_path.read_text())
    assert restored["state"]=="failed" and restored["phase"]=="corner_setup_slow"
    assert "TRI287_HIGH_FANOUT_SUBSTITUTION_ENABLED" in restored["exception"]
    assert qualifier["native_full_and_cold_restoration_verified"] is True
    assert (qualifier["original_core_cells"],qualifier["original_memory_models"])==(1889420,600)
    assert qualifier["recovered_saved_checkpoint"]==restored["output_database"]
    assert snapshot_digest(restored["output_database_fingerprint"])==qualifier["recovered_checkpoint_fingerprint_sha256"]
    assert restored["guidance_models_removed"] and restored["original600_memory_models_restored"]
    assert restored["full600_memory_restore_pending"] is False
    prep_path=root/"records/real299_mapped_preparation.json"
    prep=json.loads(prep_path.read_text())
    assert prep["state"]=="trained_mapped_bench_prepared_native_compile_pending"
    assert (prep["target_cores"],prep["target_memory_models"],prep["target_input_features"],
            prep["target_intermediate_channels"],prep["target_exact_outputs"])==(20,600,2048,5632,2048)
    identities={}
    def bind(path,digest=None):
        path=str(path); observed=sha(path)
        assert digest is None or observed==digest,"Changed consumed input "+path
        assert path not in identities or identities[path]==observed,"Conflicting input "+path
        identities[path]=observed
    for record,keys in [(admission,["evidence_sha256"]),(prep,["source_sha256","generated_sha256"]),
                        (control,["source_sha256"]),(qualifier,["evidence_sha256"]),
                        (restored,["source_sha256","native_evidence_sha256","generated_sha256"])]:
        for key in keys:
            for name,digest in record.get(key,{}).items(): bind(name,digest)
    for path in [Path(__file__).resolve(),admission_path,control_path,qualifier_path,restored_path,prep_path,
                 root/"syn/run_tri_oracle_xcelium303_runtime_control.py",
                 root/"syn/run_tri_oracle_xcelium311_runtime_control.py",
                 root/"syn/tri_oracle_xcelium308_snapshot.py",
                 root/"syn/tri_oracle_hierarchy_fingerprint.py",
                 root/"syn/tri_oracle_artifact_fingerprint.py",
                 root/"syn/tri_oracle_memory_pressure_guard.py",
                 root/"syn/tri_oracle_process_guard.py",
                 root/"syn/run_tri_oracle_row_guard175_synthesis.py"]:
        bind(path)
    assert control["requested_workers"]==8
    assert set(control["native_runs"])=={"elaborate","wrong_reference","positive"}
    control_library=None
    for phase in ["elaborate","wrong_reference","positive"]:
        native=control["native_runs"][phase]
        log=root/"records"/("xcelium311_"+phase+"_native.log")
        bind(log,native["console_sha256"])
        text=log.read_text(errors="replace")
        command=native["command"]
        assert command[command.index("-mce_sim_thread_count")+1]=="8"
        library=command[command.index("-xmlibdirname")+1]
        if control_library is None: control_library=library
        assert library==control_library
        if phase=="elaborate":
            assert native["native_exit_status"]==0 and "Writing initial simulation snapshot:" in text
            assert "-sequdp_nba_delay" in command and "-elaborate" in command
            assert command[command.index("-mce_build_thread_count")+1]=="8"
        elif phase=="wrong_reference":
            assert native["native_exit_status"]!=0 and "RUNTIME311_EXPECTED_WRONG_REFERENCE" in text
            assert "RUNTIME311_PASS cycles=3" not in text and "-R" in command
        else:
            assert native["native_exit_status"]==0 and "RUNTIME311_PASS cycles=3" in text and "-R" in command
    physical_parent=Path(restored["output_directory"])/"full/restored_parent.v"
    bind(physical_parent,restored["native_evidence_sha256"][str(physical_parent)])
    includes=[Path(name) for name in re.findall(r'^`include "([^"]+)"$',prep["compiled_bundle"],re.M)]
    assert len(includes)==9
    old_parent=includes[2]
    assert str(old_parent) in identities and old_parent.name=="parent.v"
    compiled=prep["compiled_bundle"]
    original='`include "'+str(old_parent)+'"'
    replacement='`include "'+str(physical_parent)+'"'
    assert compiled.count(original)==1
    compiled=compiled.replace(original,replacement)
    assert old_parent!=physical_parent and old_parent.name in str(old_parent)
    clusters=[]; top=[]; inside=False
    with physical_parent.open() as stream:
        for line in stream:
            found=re.match(r"^\s*module\s+([A-Za-z_][A-Za-z0-9_$]*)\b",line)
            if found:
                name=found[1]
                assert name!="tri_oracle_sram_memory_compute","Current parent embeds a duplicate core definition"
                if re.fullmatch(r"tri_oracle_sram_compute_cluster(?:_[A-Za-z0-9_$]+)?",name): clusters.append(name)
                if name=="tri_oracle_predicted_feedforward_frame": inside=True
            if inside:
                top.append(line)
                if re.match(r"^\s*endmodule\b",line): inside=False
    assert sorted(clusters)==prep["cluster_bind_targets"]
    top="".join(top)
    for name in ["packet_valid","packet_ready","packet_last","packet_error","packet_fallback",
                 "packet_tag","packet_count","packet_channels"]:
        assert re.search(r"\bwire\b[^;]*\b"+name+r"\b",top),"Missing current-candidate observer signal "+name
    fixture=Path(prep["fixture"])
    expected_word=int((fixture/"expected.hex").open().readline().strip(),16)
    def signed(value): return value-(1<<32) if value&(1<<31) else value
    source_path=root/"records/real190_full_functional_qualification.json"
    source=json.loads(source_path.read_text())
    bind(source_path,prep["source_sha256"][str(source_path)])
    fingerprint=restored["output_database_fingerprint"]
    dependencies={Path(name):value for name,value in fingerprint.get("directory_dependencies",{}).items()}
    def immutable():
        assert all(sha(name)==digest for name,digest in identities.items()),"Mapped pair input drift"
        assert hierarchy_fingerprint(restored["output_database"],directory_dependencies=dependencies)==fingerprint
    immutable()
    if args.preflight_only:
        print("REAL310_MAPPED_PAIR_PREFLIGHT_PASSED consumed_files="+str(len(identities)))
        return
    start=time.monotonic();child=pause=token=folder_path=None;stopped=False
    def stop(number,frame):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    record=dict(state="waiting_for_serial_headroom",supervisor_pid=os.getpid(),
        started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        source_sha256=identities,requested_simulation_workers=8,
        effective_anonymous_limit_bytes=16*1024**3,host_reserve_bytes=5*1024**3,
        physical_parent=str(physical_parent),physical_parent_sha256=sha(physical_parent),
        compiled_bundle=compiled,cluster_bind_targets=sorted(clusters),
        native_runs={},timing_checks_disabled=True,negative_and_positive_wall_limit_seconds=28800,full_paper_results_matched=False,routed_timing_qualified=False,
        whole_model_accuracy_qualified=False,delay_annotated_simulation_qualified=False,scope=__doc__)
    def save(**changes):
        record.update(changes,elapsed_seconds=time.monotonic()-start)
        temporary=result.with_suffix(".tmp")
        temporary.write_text(json.dumps(record,indent=2)+"\n");temporary.replace(result)
    save()
    try:
        while True:
            available,anonymous=memory()
            if available>14*1024**3 and anonymous<1024**3: break
            assert not stopped and time.monotonic()-start<10800,"Mapped pair serial-headroom deadline"
            time.sleep(2)
        immutable();out.mkdir(parents=True);save(output_directory=str(out))
        with tempfile.TemporaryDirectory(prefix="build_",dir=out) as directory:
            folder=folder_path=Path(directory)
            bundle=folder/"canonical_sources.sv";bundle.write_text(compiled)
            generated={str(bundle):sha(bundle)}
            lib=folder/"xcelium.d"
            def native(phase,arguments,limit):
                nonlocal child,pause,token
                command=["/opt/cadence/bin/xrun","-64bit",*arguments,"-xmlibdirname",str(lib),
                    "-l",str(folder/(phase+".xrun.log")),"-history_file",str(folder/(phase+".history"))]
                console=out/(phase+"_native.log")
                began=time.monotonic();token=str(folder/(phase+".xrun.log"))
                with console.open("w") as stream:
                    child=subprocess.Popen(command,cwd=folder,stdin=subprocess.DEVNULL,stdout=stream,
                        stderr=subprocess.STDOUT,start_new_session=True)
                    pause=OwnedProcessPause(child,token)
                    policy=MemoryPressurePolicy(host_reserve_bytes=5*1024**3,resume_bytes=6*1024**3,
                                                anonymous_limit_bytes=16*1024**3)
                    save(state="native_"+phase+"_running",phase=phase,native_process_group=child.pid,command=command)
                    last=0
                    try:
                        while child.poll() is None:
                            assert not stopped and time.monotonic()-began<limit,"Mapped trained-layer wall/stop guard"
                            available,anonymous=memory()
                            record.update(peak_combined_anonymous_bytes=max(record.get("peak_combined_anonymous_bytes",0),anonymous),
                                minimum_host_available_bytes=min(record.get("minimum_host_available_bytes",available),available),
                                current_host_available_bytes=available,current_combined_anonymous_bytes=anonymous)
                            action=policy.observe(available,anonymous,time.monotonic())
                            if action in ["pause","resume"]:
                                groups=pause.pause() if action=="pause" else pause.resume()
                                record.setdefault("memory_pressure_events",[]).append(dict(action=action,groups=groups,
                                    available=available,anonymous=anonymous))
                            if time.monotonic()-last>5:
                                progress=out/(phase+"_progress.log")
                                tail=""
                                if progress.exists():
                                    with progress.open("rb") as stream:
                                        stream.seek(max(0,progress.stat().st_size-2500));tail=stream.read().decode(errors="replace")
                                save(native_elapsed_seconds=time.monotonic()-began,progress_tail=tail)
                                last=time.monotonic()
                            time.sleep(.2)
                    finally:
                        pause.resume();terminate_process_group(child,log_argument=token)
                content=console.read_text(errors="replace")
                record["native_runs"][phase]=dict(command=command,native_exit_status=child.returncode,
                    elapsed_seconds=time.monotonic()-began,console_sha256=sha(console))
                immutable()
                assert all(sha(name)==digest for name,digest in generated.items())
                save()
                return child.returncode,content
            code,text=native("elaborate",["-sv","-xmerror","RECOME","-sequdp_nba_delay","-notimingchecks",
                "-mce","-mce_sim_thread_count","8","-mce_build_thread_count","8",
                "-elaborate","-top","tri_oracle_predicted_feedforward_frame_tb",str(bundle)],1800)
            assert code==0 and "Writing initial simulation snapshot:" in text and "*E," not in text,text[-3000:]
            assert "REAL_FRAME_PASS outputs=" not in text
            snapshot=library_files(lib);assert snapshot
            save(compiled_snapshot_files=len(snapshot),compiled_snapshot_inventory_sha256=snapshot_digest(snapshot),
                 compiled_bench_sha256=prep["compiled_bench_sha256"],generated_sha256=generated)
            for phase,negative,limit in [("wrong_sum",True,28800),("full",False,28800)]:
                if negative:
                    assert library_files(lib)==snapshot,"Compiled image changed before first simulation"
                else:
                    require_runtime_snapshot(lib,snapshot,administrative_template)
                arguments=["-R","-notimingchecks","-mce","-mce_sim_thread_count","8",
                           "+FIXTURE="+str(fixture),"+PROGRESS_FILE="+str(out/(phase+"_progress.log"))]
                if negative: arguments.append("+CORRUPT_REAL_REFERENCE")
                code,text=native(phase,arguments,limit)
                payload=require_runtime_snapshot(lib,snapshot,administrative_template)
                record.setdefault("runtime_snapshot_checks",{})[phase]=payload
                save()
                assert "REAL_FRAME_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=600" in text
                if negative:
                    match=re.search(r"REAL_FRAME_INTEGER_OUTPUT row=0 got=(-?\d+) expected=(-?\d+)",text)
                    assert code!=0 and match and "REAL_FRAME_PASS outputs=" not in text,text[-3000:]
                    assert (int(match[1]),int(match[2]))==(signed(expected_word),signed(expected_word^1))
                    save(wrong_integer_sum_reference_rejected=True,negative_observed_word=int(match[1]),
                         negative_corrupted_expected_word=int(match[2]))
                else:
                    match=re.search(r"REAL_FRAME_PASS outputs=2048 packets=13 groups=176 strips=45056 channels=5632 prediction_packets=36 stalls=(\d+) requests=(\d+)",text)
                    assert code==0 and match and int(match[1])>0,text[-3000:]
                    assert int(match[2])==source["memory_requests"]
                    save(exact_integer_outputs_checked=2048,actual_cores=20,actual_clusters=5,actual_compiled_memories=600,
                         groups_sent=176,strips_sent=45056,intermediate_channels=5632,prediction_packets=36,
                         successful_backpressure_stalls=int(match[1]),memory_requests=int(match[2]))
            immutable()
            save(state="current_mapped_trained_layer_and_wrong_sum_pair_passed",native_exit_status=0,
                same_compiled_image_for_positive_and_negative=True,trained_mapped_layer_functional_qualified=True,
                temporary_build_removed=False)
        save(temporary_build_removed=not folder_path.exists())
    except BaseException as error:
        if child is not None:
            if pause is not None: pause.resume()
            terminate_process_group(child,log_argument=token)
        save(state="failed",exception=repr(error),native_exit_status=child.returncode if child else None,
             temporary_build_removed=folder_path is not None and not folder_path.exists())
        raise
    print("REAL310_MAPPED_TRAINED_PAIR_FINISHED")


if __name__=="__main__":
    main()
