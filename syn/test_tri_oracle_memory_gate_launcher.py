"""Run the real memory-core bench through both native gate launchers.

The compact fixture contains the actual source design, not mapped gates. It
checks launcher admission, execution, evidence and cleanup without overlapping
a large physical job. Actual mapped/routed validation remains a separate run.
"""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

from tri_oracle_process_guard import terminate_process_group


class MemoryGateLauncherTest(unittest.TestCase):
    def run_native(self, arguments, *, cwd, env, timeout):
        with subprocess.Popen(arguments, cwd=cwd, env=env, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              start_new_session=True) as child:
            try:
                stdout, stderr = child.communicate(timeout=timeout)
                return subprocess.CompletedProcess(arguments, child.returncode, stdout, stderr)
            finally:
                # Discover descendants before killing the still-live launcher;
                # the guarded native child deliberately has a separate session.
                terminate_process_group(child)
                child.communicate()

    def test_native_timeout_stops_detached_descendants_before_fixture_cleanup(self):
        def live(pid):
            try:
                return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[0] not in ('Z', 'X')
            except FileNotFoundError:
                return False

        program = (
            'import subprocess,sys,time; from pathlib import Path; '
            'child=subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"],'
            'start_new_session=True); '
            'Path(sys.argv[1]).write_text(str(child.pid)); time.sleep(60)'
        )
        with tempfile.TemporaryDirectory(prefix='memory_gate_timeout_', dir='.cache') as directory:
            root = Path(directory).resolve()
            pid_path = root / 'native_child.pid'
            try:
                with self.assertRaises(subprocess.TimeoutExpired):
                    self.run_native([sys.executable, '-c', program, str(pid_path)],
                                    cwd=root, env=os.environ, timeout=1)
                self.assertTrue(pid_path.exists(), 'native descendant never started')
                pid = int(pid_path.read_text())
                deadline = time.monotonic() + .5
                while live(pid) and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertFalse(live(pid), 'native descendant survived launcher timeout')
            finally:
                if pid_path.exists():
                    pid = int(pid_path.read_text())
                    if live(pid):
                        os.killpg(pid, signal.SIGKILL)
        self.assertFalse(root.exists())

    def run_launcher(self, guarded):
        project = Path.cwd()
        units = (
            'memory_feedforward_core', 'activation_loader', 'cached_feedforward_core',
            'activation_cache', 'rms_activation', 'affine_quantizer', 'rmsnorm',
            'sign_fetch', 'prediction_feedforward_core', 'feedforward_core',
            'strip_predictor', 'channel_compactor', 'predicted_dispatch', 'silu_gate',
            'gated_executor', 'tile_executor', 'sparse_weight_dma', 'down_executor',
            'memory_compute', 'pe_array', 'word_bank',
        )
        bench = 'tri_oracle_memory_feedforward_core_tb'
        stage = 'memory_launcher_contract'
        with tempfile.TemporaryDirectory(prefix='memory_gate_launcher_', dir='.cache') as directory:
            root = Path(directory).resolve()
            for name in ('syn', 'verilog', '.cache/physical/library',
                         '.cache/physical/pnr/tri_oracle_memory_compute'):
                (root / name).mkdir(parents=True)
            for name in ('run_tri_oracle_core_gate_profile.sh',
                         'run_tri_oracle_core_gate_simulation.sh',
                         'tri_oracle_process_guard.py'):
                shutil.copyfile(project / 'syn' / name, root / 'syn' / name)
            shutil.copyfile(project / 'verilog' / (bench + '.sv'),
                            root / 'verilog' / (bench + '.sv'))
            netlist = root / 'source_fixture.v'
            netlist.write_text('\n'.join(
                (project / 'verilog' / f'tri_oracle_{unit}.sv').read_text()
                for unit in units))
            models = root / '.cache/physical/library/tcbn28hpcplusbwp12t40p140.v'
            models.write_text('// Source fixture needs no standard-cell primitives.\n')
            environment = {
                **os.environ,
                'TRI_ORACLE_CORE_BENCH': bench,
                'TRI_ORACLE_CORE_NETLIST': str(netlist),
                'TRI_ORACLE_GATE_STAGE': stage,
                'TRI_ORACLE_FUNCTIONAL_LIBRARY_MODE': '0',
                'TRI_ORACLE_GATE_ANON_GIB': '1.5',
                'TRI_ORACLE_GATE_SECONDS': '240',
            }
            script = ('run_tri_oracle_core_gate_profile.sh' if guarded else
                      'run_tri_oracle_core_gate_simulation.sh')
            run = self.run_native(['bash', 'syn/' + script], cwd=root,
                                  env=environment, timeout=270)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            if guarded:
                out = root / '.cache/physical/pnr/tri_oracle_memory_compute'
                result = json.loads((out / (stage + '_guard_result.json')).read_text())
                self.assertEqual(result['exit_status'], 0, result)
                self.assertIs(result['inputs_unchanged'], True)
                self.assertIs(result['delay_annotation'], False)
                self.assertEqual(result['positive_marker'], 'MEMORY_FEEDFORWARD_PASS cases=34')
                output = (out / (stage + '_console.log')).read_text()
            else:
                output = run.stdout
            self.assertEqual(output.count('MEMORY_FF_CASE_PASS'), 34, output)
            self.assertEqual(output.count('MEMORY_FEEDFORWARD_PASS cases=34'), 1, output)
            self.assertFalse((root / '.cache' / (bench + '_gate_simulation.vvp')).exists())
        self.assertFalse(root.exists())

    def test_memory_bench_runs_through_native_compile_launcher(self):
        self.run_launcher(guarded=False)

    def test_memory_bench_runs_through_guard_and_records_success(self):
        self.run_launcher(guarded=True)


if __name__ == '__main__':
    unittest.main()
