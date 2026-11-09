"""Verify memory-pressure decisions and actual suspension of owned tool workers."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

from tri_oracle_memory_pressure_guard import MemoryPressurePolicy, OwnedProcessPause


GIB = 1024**3


class MemoryPressurePolicyTest(unittest.TestCase):
    def policy(self):
        return MemoryPressurePolicy(host_reserve_bytes=4*GIB, resume_bytes=5*GIB,
                                    anonymous_limit_bytes=21*GIB,
                                    recovery_seconds=3, maximum_pause_seconds=300)

    def test_transient_pressure_suspends_then_requires_stable_recovery(self):
        guard = self.policy()
        self.assertEqual(guard.observe(6*GIB, 19*GIB, 10), 'run')
        self.assertEqual(guard.observe(3.85*GIB, 19*GIB, 11), 'pause')
        self.assertEqual(guard.observe(4.5*GIB, 19*GIB, 12), 'wait')
        self.assertEqual(guard.observe(5.5*GIB, 19*GIB, 13), 'wait')
        self.assertEqual(guard.observe(5.5*GIB, 19*GIB, 15.9), 'wait')
        self.assertEqual(guard.observe(5.5*GIB, 19*GIB, 16), 'resume')
        self.assertEqual(guard.observe(6*GIB, 19*GIB, 17), 'run')

    def test_another_pressure_dip_restarts_recovery_interval(self):
        guard = self.policy()
        self.assertEqual(guard.observe(3.9*GIB, 18*GIB, 0), 'pause')
        guard.observe(6*GIB, 18*GIB, 1)
        guard.observe(4.9*GIB, 18*GIB, 3)
        self.assertEqual(guard.observe(6*GIB, 18*GIB, 4), 'wait')
        self.assertEqual(guard.observe(6*GIB, 18*GIB, 6.9), 'wait')
        self.assertEqual(guard.observe(6*GIB, 18*GIB, 7), 'resume')

    def test_hard_anonymous_limit_still_fails_while_paused(self):
        guard = self.policy()
        guard.observe(3.9*GIB, 20*GIB, 0)
        with self.assertRaisesRegex(MemoryError, 'anonymous'):
            guard.observe(6*GIB, 21*GIB, 1)

    def test_sustained_pressure_does_not_wait_forever(self):
        guard = self.policy()
        guard.observe(3.9*GIB, 19*GIB, 10)
        with self.assertRaisesRegex(MemoryError, 'recovery'):
            guard.observe(4.5*GIB, 19*GIB, 310)

    def test_emergency_host_pressure_is_terminal(self):
        with self.assertRaisesRegex(MemoryError, 'emergency'):
            self.policy().observe(1*GIB, 19*GIB, 0)

    def test_invalid_thresholds_are_rejected(self):
        with self.assertRaises(ValueError):
            MemoryPressurePolicy(host_reserve_bytes=4*GIB, resume_bytes=3*GIB,
                                 anonymous_limit_bytes=21*GIB)


class OwnedProcessPauseTest(unittest.TestCase):
    def test_detached_workers_pause_and_resume_without_touching_another_job(self):
        with tempfile.TemporaryDirectory(prefix='memory_pause57_', dir='.cache/physical') as folder:
            folder = Path(folder).resolve()
            heartbeat = "import sys,time; from pathlib import Path; p=Path(sys.argv[1]); n=0\nwhile True:\n n+=1; p.write_text(str(n)); time.sleep(.02)\n"
            worker = folder/'detached.py'
            worker.write_text(heartbeat)
            parent = folder/'parent.py'
            parent.write_text(
                "import subprocess,sys,time; from pathlib import Path\n"
                "child=subprocess.Popen([sys.executable,sys.argv[1],sys.argv[2]],start_new_session=True)\n"
                "Path(sys.argv[3]).write_text(str(child.pid))\n"
                "p=Path(sys.argv[4]); n=0\n"
                "while True:\n n+=1; p.write_text(str(n)); time.sleep(.02)\n")
            own = subprocess.Popen([sys.executable, str(parent), str(worker), str(folder/'worker_count'),
                                    str(folder/'worker_pid'), str(folder/'parent_count'),
                                    '-log', str(folder/'owned_log')], start_new_session=True)
            other = subprocess.Popen([sys.executable, str(worker), str(folder/'other_count')],
                                     start_new_session=True)
            detached = None
            controller = OwnedProcessPause(own, str(folder/'owned_log'))
            try:
                deadline = time.monotonic()+5
                while not all((folder/name).exists() for name in
                              ['worker_pid', 'parent_count', 'worker_count', 'other_count']):
                    self.assertLess(time.monotonic(), deadline)
                    time.sleep(.02)
                detached = int((folder/'worker_pid').read_text())
                # A remembered identifier with a different process start time
                # must never make an unrelated current process ours.
                controller.identities[other.pid] = -1
                controller.pause()
                self.assertTrue(controller.paused)
                time.sleep(.1)
                before = [(folder/name).read_text() for name in
                          ['parent_count', 'worker_count', 'other_count']]
                time.sleep(.15)
                after = [(folder/name).read_text() for name in
                         ['parent_count', 'worker_count', 'other_count']]
                self.assertEqual(after[:2], before[:2])
                self.assertNotEqual(after[2], before[2])
                controller.resume()
                self.assertFalse(controller.paused)
                time.sleep(.15)
                for name, previous in zip(['parent_count', 'worker_count'], after):
                    self.assertGreater(int((folder/name).read_text()), int(previous))
            finally:
                controller.resume()
                for pid in [own.pid, other.pid, detached]:
                    if pid is not None:
                        try:
                            os.killpg(pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                own.wait(timeout=5)
                other.wait(timeout=5)


if __name__ == '__main__':
    unittest.main()
