"""Memory-fed projection through four real cores and their sum aggregator."""
from pathlib import Path
import os
import resource
import signal
import subprocess
import tempfile
import time
import unittest


class ClusterProjectionTest(unittest.TestCase):
    def test_four_core_projection_shapes_traffic_stalls_faults_and_recovery(self):
        available = int(next(line.split()[1] for line in
                             Path('/proc/meminfo').read_text().splitlines()
                             if line.startswith('MemAvailable:'))) * 1024
        self.assertGreaterEqual(available, 6 * 1024**3)

        def bounded():
            resource.setrlimit(resource.RLIMIT_AS, (768 * 1024**2, 768 * 1024**2))

        self.resources = {'minimum_host_available_bytes': available,
                          'peak_container_anonymous_bytes': 0}

        def run(arguments, timeout):
            started = time.monotonic()
            child = subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, preexec_fn=bounded, start_new_session=True)
            try:
                while True:
                    host = int(next(line.split()[1] for line in
                        Path('/proc/meminfo').read_text().splitlines()
                        if line.startswith('MemAvailable:'))) * 1024
                    anon = int(next(line.split()[1] for line in
                        Path('/sys/fs/cgroup/memory.stat').read_text().splitlines()
                        if line.startswith('anon ')))
                    self.resources['minimum_host_available_bytes'] = min(
                        self.resources['minimum_host_available_bytes'], host)
                    self.resources['peak_container_anonymous_bytes'] = max(
                        self.resources['peak_container_anonymous_bytes'], anon)
                    self.assertGreaterEqual(host, 6 * 1024**3,
                                            'test yields to physical job below host reserve')
                    self.assertLess(time.monotonic() - started, timeout)
                    try:
                        stdout, _ = child.communicate(timeout=.25)
                        return subprocess.CompletedProcess(arguments, child.returncode, stdout, '')
                    except subprocess.TimeoutExpired:
                        pass
            finally:
                if child.poll() is None:
                    try:
                        os.killpg(child.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    try:
                        child.communicate(timeout=2)
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid, signal.SIGKILL)
                        child.communicate()

        units = ('sparse_weight_dma', 'compute_cluster', 'memory_compute',
                 'pe_array', 'word_bank')
        with tempfile.TemporaryDirectory(prefix='cluster_projection_', dir='.cache') as directory:
            binary = Path(directory) / 'projection.vvp'
            compiled = run([
                '.cache/tools/iverilog', '-B', '.cache/tools/ivl', '-g2012',
                '-s', 'tri_oracle_cluster_projection_tb', '-o', str(binary),
                getattr(self, 'source_path', 'verilog/tri_oracle_cluster_projection.sv'),
                *(getattr(self, 'dependency_overrides', {}).get(
                    unit, f'verilog/tri_oracle_{unit}.sv') for unit in units),
                'verilog/tri_oracle_cluster_projection_tb.sv'], 90)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            native = run(['.cache/tools/vvp', '-M', '.cache/tools/ivl', str(binary)], 180)
        self.assertFalse(Path(directory).exists())
        self.assertEqual(native.returncode, 0, native.stdout + native.stderr)
        self.assertEqual(native.stdout.count('CLUSTER_PROJECTION_CASE_PASS'), 41)
        self.assertIn('CLUSTER_PROJECTION_PASS cases=41', native.stdout)
        self.native_stdout = native.stdout
        print(native.stdout)


if __name__ == '__main__':
    unittest.main()
