"""Pause owned native tool workers during recoverable host memory pressure."""
import os
from pathlib import Path
import signal
import time

from tri_oracle_process_guard import _processes


class MemoryPressurePolicy:
    """Retain a hard allocation ceiling; allow bounded recovery below reserve."""

    def __init__(self, *, host_reserve_bytes, resume_bytes, anonymous_limit_bytes,
                 recovery_seconds=3, maximum_pause_seconds=300):
        if not (0 < host_reserve_bytes < resume_bytes and anonymous_limit_bytes > 0
                and 0 < recovery_seconds < maximum_pause_seconds):
            raise ValueError('Invalid memory-pressure thresholds')
        self.host_reserve_bytes = host_reserve_bytes
        self.resume_bytes = resume_bytes
        self.anonymous_limit_bytes = anonymous_limit_bytes
        self.recovery_seconds = recovery_seconds
        self.maximum_pause_seconds = maximum_pause_seconds
        self.paused_at = None
        self.recovered_at = None

    def observe(self, available_bytes, anonymous_bytes, now):
        if anonymous_bytes >= self.anonymous_limit_bytes:
            raise MemoryError('Native anonymous memory ceiling exceeded')
        if available_bytes <= self.host_reserve_bytes/2:
            raise MemoryError('Host emergency memory reserve exhausted')
        if self.paused_at is None:
            if available_bytes >= self.host_reserve_bytes:
                return 'run'
            self.paused_at = now
            return 'pause'
        if now-self.paused_at >= self.maximum_pause_seconds:
            raise MemoryError('Host memory recovery deadline exceeded')
        if available_bytes < self.resume_bytes:
            self.recovered_at = None
        elif self.recovered_at is None:
            self.recovered_at = now
        elif now-self.recovered_at >= self.recovery_seconds:
            self.paused_at = None
            self.recovered_at = None
            return 'resume'
        return 'wait'


class OwnedProcessPause:
    """Find launcher descendants and detached native workers by exact log token.

    Process start times bind every remembered identifier. Signals target only
    groups containing a currently verified owned process, never the caller.
    """

    def __init__(self, child, log_argument):
        self.child = child
        self.log_token = os.fsencode(log_argument)
        self.identities = {}
        self.paused = False
        identity = self._identity(child.pid)
        if identity is not None:
            self.identities[child.pid] = identity

    @staticmethod
    def _identity(pid):
        try:
            raw = (Path('/proc')/str(pid)/'stat').read_text()
            fields = raw[raw.rfind(')')+2:].split()
            return int(fields[19]) if fields[0] not in ('Z', 'X') else None
        except (FileNotFoundError, ProcessLookupError):
            return None

    def _owned_groups(self):
        processes = _processes()
        owned = {pid for pid, identity in self.identities.items()
                 if pid in processes and self._identity(pid) == identity}
        for pid, (_, _, argv) in processes.items():
            if any(argv[i] == b'-log' and argv[i+1] == self.log_token
                   for i in range(len(argv)-1)):
                owned.add(pid)
        changed = True
        while changed:
            changed = False
            for pid, (parent, _, _) in processes.items():
                if parent in owned and pid not in owned:
                    owned.add(pid)
                    changed = True
        for pid in owned:
            identity = self._identity(pid)
            if identity is not None:
                self.identities[pid] = identity
        groups = set()
        for pid in owned:
            identity = self._identity(pid)
            if identity is not None and identity == self.identities.get(pid):
                groups.add(processes[pid][1])
        if os.getpgrp() in groups:
            raise RuntimeError('Refusing to signal supervisor process group')
        return groups

    @staticmethod
    def _signal(groups, kind):
        for group in groups:
            try:
                os.killpg(group, kind)
            except ProcessLookupError:
                pass

    def pause(self):
        deadline = time.monotonic()+2
        while True:
            groups = self._owned_groups()
            self._signal(groups, signal.SIGSTOP)
            self.paused = True
            latest_groups = self._owned_groups()
            self._signal(latest_groups-groups, signal.SIGSTOP)
            groups.update(latest_groups)
            # Confirm every surviving owned worker really stopped, including
            # workers that forked or detached while suspension was starting.
            active = []
            for pid, identity in list(self.identities.items()):
                if self._identity(pid) != identity:
                    continue
                try:
                    raw = (Path('/proc')/str(pid)/'stat').read_text()
                    state = raw[raw.rfind(')')+2:].split()[0]
                    if state not in ('T', 't', 'Z', 'X'):
                        active.append(pid)
                except (FileNotFoundError, ProcessLookupError):
                    pass
            if not active:
                return sorted(groups)
            if time.monotonic() >= deadline:
                raise RuntimeError('Owned native workers did not suspend: '+str(active))
            time.sleep(.02)

    def resume(self):
        if not self.paused:
            return []
        groups = self._owned_groups()
        self._signal(groups, signal.SIGCONT)
        self.paused = False
        return sorted(groups)
