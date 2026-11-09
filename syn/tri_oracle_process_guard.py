"""Stop owned tool groups even when the initial launcher exits first."""
import os
from pathlib import Path
import signal
import time

def _processes():
    result={}
    for directory in Path('/proc').iterdir():
        if not directory.name.isdigit():continue
        try:
            text=(directory/'stat').read_text()
            fields=text[text.rfind(')')+2:].split()
            if fields[0] in ('Z','X'):continue
            argv=(directory/'cmdline').read_bytes().split(b'\0')
            result[int(directory.name)]=(int(fields[1]),int(fields[2]),argv)
        except (FileNotFoundError,ProcessLookupError,PermissionError):continue
    return result

def terminate_process_group(child, grace_seconds=5, log_argument=None):
    groups={child.pid}
    roots={child.pid}
    term_sent=set()
    def discover():
        processes=_processes()
        if log_argument is not None:
            token=os.fsencode(log_argument)
            for pid,(_,_,argv) in processes.items():
                if any(argv[i]==b'-log' and argv[i+1]==token for i in range(len(argv)-1)):
                    roots.add(pid)
        changed=True
        while changed:
            changed=False
            for pid,(parent,group,_) in processes.items():
                if parent in roots and pid not in roots:
                    roots.add(pid);changed=True
        groups.update(processes[pid][1] for pid in roots if pid in processes)
        return {group for _,group,_ in processes.values() if group in groups}
    def send(group,kind):
        try:os.killpg(group,kind)
        except ProcessLookupError:pass
    deadline=time.monotonic()+grace_seconds
    live=discover()
    while live and time.monotonic()<deadline:
        for group in live-term_sent:send(group,signal.SIGTERM);term_sent.add(group)
        child.poll();time.sleep(.05);live=discover()
    if live:
        print('Escalating surviving owned tool groups to SIGKILL: '+str(sorted(live)),flush=True)
    # Keep the caller's execution lock until no non-zombie member remains.
    # Native tool workers may have detached; exact -log tokens identify them.
    while live:
        for group in live:send(group,signal.SIGKILL)
        child.poll();time.sleep(.05);live=discover()
    return child.wait()
