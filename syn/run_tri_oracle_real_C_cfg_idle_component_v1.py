"""Draft portable real-C component runner; use --run --case all (or1..20).

Only the existing named cadence-ddi container executes Xcelium as the host UID.
All generated files remain under.cache. FF data, memory and owner seams are
synthetic fixtures; no full264 target frame or trained fabric is qualified.
"""
from pathlib import Path
import argparse,hashlib,json,os,re,resource,shutil,signal,subprocess,sys,time,types
ROOT=Path(__file__).resolve().parents[1]
MANIFEST=ROOT/'syn/tri_oracle_real_C_cfg_idle_component_sources_v1.json'
CONTAINER='cadence-ddi'

def need(value,why):
    if value is not True:raise ValueError(why)

def identity(value):
    return[value.st_dev,value.st_ino,value.st_mode,value.st_uid,value.st_gid,value.st_size,value.st_mtime_ns,value.st_ctime_ns]

def closed(path,wanted=None,expected_sha=None,expected_bytes=None):
    path=Path(path);need(path.is_absolute()and path.resolve(strict=True)==path and not path.is_symlink()and path.is_file(),'canonical regular file')
    h=hashlib.sha256();size=0
    with path.open('rb')as stream:
        before=identity(os.fstat(stream.fileno()))
        if wanted is not None:need(before==wanted,'admitted FD identity')
        for block in iter(lambda:stream.read(262144),b''):h.update(block);size+=len(block)
        after=identity(os.fstat(stream.fileno()))
    at_path=identity(path.stat());need(before==after==at_path and size==before[5],'complete unchanged FD/path EOF')
    need(expected_sha is None or h.hexdigest()==expected_sha,'complete source SHA256')
    need(expected_bytes is None or size==expected_bytes,'exact source extent')
    return dict(path=str(path),bytes=size,sha256=h.hexdigest(),complete_EOF=True,identity_before=before,identity_after_fd=after,identity_after_path=at_path)

def verify_record(row):return closed(row['path'],row['identity_before'],row['sha256'],row['bytes'])

def write_new(path,value):
    with path.open('x')as stream:json.dump(value,stream,indent=2,sort_keys=True);stream.write('\n')

def available():
    return int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines()
                    if line.startswith('MemAvailable:'))) * 1024

def group_usage(group):
    rss = 0
    identities = []
    for path in Path('/proc').iterdir():
        if not path.name.isdecimal():
            continue
        try:
            text = (path / 'stat').read_text()
            fields = text[text.rfind(')') + 2:].split()
            if int(fields[2]) != group:
                continue
            resident = int(fields[21]) * os.sysconf('SC_PAGE_SIZE')
            rss += resident
            identities.append(dict(pid=int(path.name), birth=int(fields[19]), rss_bytes=resident))
        except (OSError, ValueError, IndexError):
            continue
    return rss, identities

def live_owned_group(group):
    """Same-process-group observations only; zombies cannot execute or hold RSS.

    The direct child is not reaped until cleanup ends, so its leader PID stays
    reserved. No group signal is issued after that reservation is released.
    This is not a claim about descendants that create another process group.
    """
    members = []
    for path in Path('/proc').iterdir():
        if not path.name.isdecimal():
            continue
        try:
            fields = (path / 'stat').read_text().rsplit(')', 1)[1].split()
            if int(fields[2]) == group and fields[0] not in ('Z', 'X', 'x'):
                members.append(dict(pid=int(path.name), birth=int(fields[19]),
                                    state=fields[0]))
        except (OSError, ValueError, IndexError):
            continue
    return members

def cleanup_owned_group(native):
    """Bounded TERM/KILL based on live group membership, before leader reap."""
    signals = []
    errors = []

    def send(value):
        try:
            os.killpg(native.pid, value)
            signals.append(int(value))
        except ProcessLookupError:
            pass
        except OSError as error:
            errors.append(type(error).__name__ + ': ' + str(error))

    initial = live_owned_group(native.pid)
    remaining = initial
    if remaining:
        send(signal.SIGTERM)
        deadline = time.monotonic() + 10
        while remaining and time.monotonic() < deadline:
            time.sleep(0.1)
            remaining = live_owned_group(native.pid)
    if remaining:
        send(signal.SIGKILL)
        deadline = time.monotonic() + 5
        while remaining and time.monotonic() < deadline:
            time.sleep(0.1)
            remaining = live_owned_group(native.pid)
    status = None
    if remaining:
        errors.append('Owned group remains live after bounded KILL observation; '
                      'leader is deliberately not reaped by this guard.')
    else:
        # First and only parent-reaping operation, after group cleanup.
        try:
            status = native.wait(timeout=1)
        except (OSError, subprocess.TimeoutExpired) as error:
            errors.append(type(error).__name__ + ': ' + str(error))
    return dict(initial_live_members=initial, remaining_live_members=remaining,
                signals_sent=signals, native_exit_code=status,
                leader_reaped=status is not None,
                error='; '.join(errors) if errors else None,
                scope='Owned process group only; no universal descendant claim.')

def run_owned_native(argv, case, environment, helpers, console, limits,
                     authority_sha, stderr_handle=subprocess.STDOUT):
    """Own the complete spawned lifetime, including failed startup recording."""
    started = time.monotonic()
    minimum_host = helpers.available()
    peak = 0
    samples = []
    stop = None
    ticks = 0
    native = None
    birth = None
    birth_error = None
    startup_error = None
    monitor_error = None
    startup_complete = False
    cleanup = None
    # Ownership starts before Popen: every subsequent exception reaches finally.
    try:
        native = subprocess.Popen(argv, cwd=case, env=environment,
                                  stdout=console, stderr=stderr_handle,
                                  preexec_fn=limits, start_new_session=True)
        try:
            birth = int(Path('/proc/%d/stat' % native.pid).read_text()
                        .rsplit(')', 1)[1].split()[19])
        except (OSError, ValueError, IndexError) as error:
            birth_error = type(error).__name__ + ': ' + str(error)
        launch = dict(container_pid=native.pid, birth=birth,
                      birth_observation_error=birth_error,
                      authority_sha256=authority_sha, argv=argv)
        (case / 'Root_native_launch_v1.json').write_text(
            json.dumps(launch, indent=2) + '\n')
        print('RAW32_NATIVE_CONTAINER_PID=%d BIRTH=%s' % (native.pid, birth), flush=True)
        startup_complete = True
        while True:
            # WNOWAIT observes exit without releasing the process-group leader.
            terminal = os.waitid(os.P_PID, native.pid,
                                 os.WEXITED | os.WNOHANG | os.WNOWAIT)
            if terminal is not None:
                if live_owned_group(native.pid):
                    stop = 'OWNED_GROUP_LIVE_AFTER_PARENT_EXIT'
                break
            minimum_host = min(minimum_host, helpers.available())
            resident, identities = helpers.group_usage(native.pid)
            peak = max(peak, resident)
            if ticks < 4 or ticks % 20 == 0:
                samples.append(dict(elapsed_seconds=time.monotonic() - started,
                                    group_rss_bytes=resident, identities=identities))
            ticks += 1
            log_paths = (case / 'real_C_idle.xrun.log', case / 'native_console_v1.log', case / 'native_stderr_v1.log')
            oversized = any(p.exists() and p.stat().st_size > 16 << 20
                            for p in log_paths)
            stop = ('HOST_MEMORY_FLOOR' if minimum_host < 8 << 30 else
                    'PROCESS_GROUP_MEMORY_CAP' if resident > 1 << 30 else
                    'NATIVE_WALL_LIMIT' if time.monotonic() - started > 900 else
                    'LOG_SIZE_CAP' if oversized else
                    'DISK_FLOOR' if shutil.disk_usage(case).free < 1 << 30 else None)
            if stop:
                break
            time.sleep(1)
    except BaseException as error:
        message = type(error).__name__ + ': ' + str(error)
        if startup_complete:
            monitor_error = message
        else:
            startup_error = message
    finally:
        if native is not None:
            cleanup = cleanup_owned_group(native)
    return dict(native_exit_code=None if cleanup is None else cleanup['native_exit_code'],
                resource_stop_reason=stop, native_wall_seconds=time.monotonic() - started,
                minimum_host_available_bytes=minimum_host, peak_group_RSS_bytes=peak,
                sampled_child_identities=samples,
                container_pid=None if native is None else native.pid, birth=birth,
                birth_observation_error=birth_error, startup_error=startup_error,
                monitor_error=monitor_error, cleanup=cleanup)

def source_packet():
    record=closed(MANIFEST);manifest=json.loads(MANIFEST.read_bytes());verify_record(record)
    need(manifest['schema']=='tri_oracle_real_C_cfg_idle_component_sources_v1','public manifest schema')
    need(manifest['container']==CONTAINER and manifest['runtime_payload_files']==[] and manifest['vendor_models_required']is False,'source-only component')
    common=manifest['ordered_common_sources'];groups=manifest['case_groups']
    need(len(common)==11 and len(groups)==2 and groups[0]['case_ids']==[1,2] and groups[1]['case_ids']==list(range(3,21)),'finite20-case source roles')
    paths=[];records=[record,closed(Path(__file__).resolve())]
    for row in common+[g['source']for g in groups]:
        relative=Path(row['path']);need(not relative.is_absolute() and '..'not in relative.parts,'project-relative source')
        path=ROOT/relative;need(path.is_relative_to(ROOT) and path.suffix=='.sv','public SystemVerilog source')
        paths.append(path);records.append(closed(path,expected_sha=row['sha256'],expected_bytes=row['bytes']))
    need(len(paths)==len(set(paths))==13,'unique explicit public source list')
    need(all(p.name!='tri_oracle_raw32_residual_commit_v1.sv'for p in paths),'exclude combined duplicate packages')
    return manifest,records

def selected_sources(manifest,case_id):
    need(type(case_id)is int and case_id in range(1,21),'typed component case1..20')
    group=next(g for g in manifest['case_groups']if case_id in g['case_ids'])
    return manifest['ordered_common_sources']+[group['source']],group['top']

def clean_lifetime(observed,errors):
    cleanup=observed['cleanup']
    return(type(observed['native_exit_code'])is int and observed['native_exit_code']==0 and
      type(observed['container_pid'])is int and observed['container_pid']>0 and
      type(observed['birth'])is int and observed['birth']>0 and
      all(observed[k]is None for k in('startup_error','monitor_error','resource_stop_reason','birth_observation_error')) and
      type(cleanup)is dict and cleanup['leader_reaped']is True and type(cleanup['native_exit_code'])is int and
      cleanup['native_exit_code']==0 and cleanup['remaining_live_members']==[] and cleanup['signals_sent']==[] and cleanup['error']is None and not errors)

def fields(line):return dict(re.findall(r'\b(\w+)=([^\s]+)',line))

def trace_check(case,case_id):
    summaries=[]
    for name in('real_C_idle.xrun.log','native_console_v1.log'):
        markers={};warm=[]
        with(case/name).open('r',encoding='utf-8',errors='strict')as stream:
            for line in stream:
                need(not re.search(r'\*[EWF],',line),'no Xcelium error/warning/fatal')
                match=re.match(r'^(REAL_C_\w+)\b',line)
                if match:
                    marker=match.group(1);markers.setdefault(marker,[]).append(fields(line))
                    if marker=='REAL_C_WARM_ROW':warm.append(int(markers[marker][-1]['rank']))
        need(warm==list(range(264)),'all264 real warmup rows in each stdout/primary log')
        for marker,count in [('REAL_C_WARM_RETIRED',1),('REAL_C_NATIVE_DONE',1),('REAL_C_SCALE_WORD',128)]:
            need(len(markers.get(marker,[]))==count,'finite marker count '+marker)
        if case_id in(1,2):
            marker='REAL_C_IDLE_CORRECTED_GREEN_PASS';need(len(markers.get(marker,[]))==1,'one corrected component PASS')
            got=markers[marker][0]
            wanted=dict(case=str(case_id),delay=str(0 if case_id==1 else 3),warm_rows='264',warm_strips='67584',physical_cfg='1',target_rows='1',target_count='264',target_strips='256',held_rowDone_cycles='8',target_retire='0')
            need(all(got.get(k)==v for k,v in wanted.items()),'exact healthy finite endpoint')
            need(len(markers.get('REAL_C_FIRST_TARGET_ROW_DONE',[]))==1,'one actual target row')
        else:
            marker='REAL_C_IDLE_NEGATIVE_PASS';need(len(markers.get(marker,[]))==1,'one named negative PASS')
            for one in('REAL_C_NEGATIVE_TRIGGER','REAL_C_NEGATIVE_FAULT'):need(len(markers.get(one,[]))==1,'one causal negative marker')
            got=markers[marker][0];physical=case_id==16
            wanted=dict(case=str(case_id),sticky_cycles='64',stimulus_resolved='1',actual_cfg=str(int(physical)),client_ACK=str(int(case_id in(14,16))),proxy_captures=str(int(physical)),actual_idle=str(int(not physical)),actual_accepted='0'if physical else '264',actual_completed='0'if physical else '264',actual_fault='0',target_demand='0',target_retire='0',owner_retained='1')
            need(all(got.get(k)==v for k,v in wanted.items()),'exact injected-link finite endpoint')
        count=1 if case_id in(1,2,16)else 0
        for marker in('REAL_C_OWN_OFFER_CAPTURE','REAL_C_PHYSICAL_CFG_ACK','REAL_C_PHYSICAL_CFG_POST'):
            need(len(markers.get(marker,[]))==count,'actual physical configuration marker count')
        summaries.append(dict(log=name,case_id=case_id,warm_rows=264,endpoint=got))
    with(case/'native_stderr_v1.log').open('r',encoding='utf-8',errors='strict')as stream:
        for line in stream:need(not re.search(r'\*[EWF],',line),'no Xcelium error/warning/fatal in separate stderr')
    return summaries

def run_case(output,manifest,source_records,case_id):
    case=output/('case%02d'%case_id);need(not case.exists(),'fresh case; no overwrite/restart')
    need(available()>=10<<30 and shutil.disk_usage(output).free>=2<<30,'10GiB host/2GiB disk admission')
    before=[verify_record(row)for row in source_records]
    rows,top=selected_sources(manifest,case_id)
    argv=['/opt/cadence/bin/xrun','-64bit','-sv']+[str(ROOT/row['path'])for row in rows]+['-top',top,'+case='+str(case_id),'-logfile',str(case/'real_C_idle.xrun.log')]
    need(len(argv)==20,'exact12-source ordinary20-argument recipe')
    case.mkdir();scratch=case/'Root_scratch';scratch.mkdir();environment=os.environ.copy()
    for name in('TMPDIR','TMP','TEMP','CDS_TMP_DIR','XDG_CACHE_HOME','PYTHONPYCACHEPREFIX'):environment[name]=str(scratch)
    environment['PYTHONDONTWRITEBYTECODE']='1'
    def limits():
        resource.setrlimit(resource.RLIMIT_AS,(2<<30,2<<30));resource.setrlimit(resource.RLIMIT_CPU,(600,600))
    helpers=types.SimpleNamespace(available=available,group_usage=group_usage)
    with(case/'native_console_v1.log').open('xb')as console,(case/'native_stderr_v1.log').open('xb')as stderr:
        observed=run_owned_native(argv,case,environment,helpers,console,limits,'public_component_'+str(case_id),stderr_handle=stderr)
    errors=[];after=[];outputs={};symlinks={};trace=[]
    for row in before:
        try:after.append(verify_record(row))
        except Exception as error:errors.append(dict(path=row['path'],error=type(error).__name__+': '+str(error)))
    for base,dirs,names in os.walk(case,followlinks=False,onerror=lambda e:errors.append(dict(path=str(e.filename),error=str(e)))):
        for name in dirs+names:
            path=Path(base)/name
            try:
                if path.is_symlink():symlinks[str(path)]=dict(target=os.readlink(path),identity8=identity(path.lstat()))
                elif path.is_file():outputs[str(path)]=closed(path)
                elif not path.is_dir():errors.append(dict(path=str(path),error='unknown generated filesystem kind'))
            except Exception as error:errors.append(dict(path=str(path),error=type(error).__name__+': '+str(error)))
    for name in('real_C_idle.xrun.log','native_console_v1.log','native_stderr_v1.log','Root_native_launch_v1.json'):
        if str(case/name)not in outputs:errors.append(dict(path=name,error='required native output missing'))
    operational=clean_lifetime(observed,errors)
    if operational:
        try:trace=trace_check(case,case_id)
        except Exception as error:errors.append(dict(path='finite_trace',error=type(error).__name__+': '+str(error)))
    for row in before+list(outputs.values()):
        try:verify_record(row)
        except Exception as error:errors.append(dict(path=row['path'],error=type(error).__name__+': '+str(error)))
    for name,row in symlinks.items():
        try:need(identity(Path(name).lstat())==row['identity8'] and os.readlink(name)==row['target'],'unchanged generated symlink')
        except Exception as error:errors.append(dict(path=name,error=type(error).__name__+': '+str(error)))
    result=dict(schema='tri_oracle_real_C_cfg_idle_component_case_result_v1',case_id=case_id,native_argv=argv,source_records_before=before,source_records_after=after,all_case_regular_files=outputs,preserved_symlinks=symlinks,closure_or_trace_errors=errors,trace=trace,operational_clean_exit0=clean_lifetime(observed,errors),finite_component_pass=clean_lifetime(observed,errors) and bool(trace),full264_target_or_trained_or_whole_hardware_qualified=False,paper_matching_qualified=False,**observed)
    write_new(output/('case%02d_result.json'%case_id),result)
    return result['finite_component_pass']

def inside(output,cases):
    need(Path('/.dockerenv').is_file() and Path.cwd().resolve()==ROOT,'execute native only inside cadence-ddi/project')
    need(not output.exists(),'fresh output tree')
    manifest,records=source_packet();need(available()>=10<<30,'10GiB host admission')
    output.mkdir(parents=True);passed=[];error=None
    for case_id in cases:
        try:
            if not run_case(output,manifest,records,case_id):break
            passed.append(case_id)
        except Exception as failure:
            error=type(failure).__name__+': '+str(failure);break
    result=dict(schema='tri_oracle_real_C_cfg_idle_component_suite_result_v1',requested_cases=cases,passed_cases=passed,error=error,finite_component_pass=passed==cases and error is None,all_generated_files_preserved=True,full264_target_or_trained_or_whole_hardware_qualified=False,paper_matching_qualified=False)
    write_new(output/'suite_result.json',result);print(json.dumps(result,sort_keys=True),flush=True)
    return 0 if result['finite_component_pass']else 1

def main():
    need(__debug__ and sys.flags.optimize==0 and sys.dont_write_bytecode,'use unoptimized Python -B')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',action='store_true',help='explicitly execute the finite component suite')
    parser.add_argument('--case',default='all',help='all or one integer1..20')
    parser.add_argument('--output',help='fresh project.cache output directory')
    parser.add_argument('--inside',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args();need(args.run is True,'execution requires --run')
    if args.case=='all':cases=list(range(1,21))
    else:
        need(re.fullmatch(r'(?:[1-9]|1[0-9]|20)',args.case)is not None,'case all or canonical integer1..20');cases=[int(args.case)]
    output=Path(args.output)if args.output else ROOT/'.cache'/('real_C_cfg_idle_component_'+str(time.time_ns()))
    if not output.is_absolute():output=ROOT/output
    cache=ROOT/'.cache'
    need(cache.is_dir() and cache.resolve()==cache and output.resolve()==output and output.is_relative_to(cache) and output!=cache,'outputs strictly in canonical project.cache')
    if args.inside:return inside(output,cases)
    need(not Path('/.dockerenv').exists(),'host entry point; container path is internal')
    environment=os.environ.copy()
    for name in('TMPDIR','TMP','TEMP','CDS_TMP_DIR','XDG_CACHE_HOME','PYTHONPYCACHEPREFIX'):environment[name]=str(cache)
    environment['PYTHONDONTWRITEBYTECODE']='1'
    inspection=subprocess.run(['docker','inspect','--format','{{json .}}',CONTAINER],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=10,env=environment)
    need(len(inspection.stdout)<65536,'bounded named-container metadata');record=json.loads(inspection.stdout)
    need(record['Name']=='/'+CONTAINER and record['State']['Running']is True and record['Config']['Image']=='cadence-ddi:25.10.000-patched','existing sole Cadence container/image tag')
    command=['docker','exec','--user',str(os.getuid())+':'+str(os.getgid()),'--workdir',str(ROOT)]
    for name in('TMPDIR','TMP','TEMP','CDS_TMP_DIR','XDG_CACHE_HOME','PYTHONPYCACHEPREFIX'):command+=['--env',name+'='+str(cache)]
    command+=['--env','PYTHONDONTWRITEBYTECODE=1',CONTAINER,'/usr/bin/python3','-B',str(Path(__file__).resolve()),'--inside','--run','--case',args.case,'--output',str(output)]
    os.execvpe('docker',command,environment)
if __name__=='__main__':sys.exit(main())
