"""Real twenty-core memory-fed projection, ownership, abort and recovery."""
from pathlib import Path
import resource
import subprocess
import tempfile
import time
import unittest

from tri_oracle_process_guard import terminate_process_group


class FabricProjectionTest(unittest.TestCase):
    def test_twenty_core_projection_sums_memory_ownership_abort_and_recovery(self):
        def available():
            return int(next(line.split()[1] for line in
                            Path('/proc/meminfo').read_text().splitlines()
                            if line.startswith('MemAvailable:'))) * 1024

        self.assertGreaterEqual(available(), 6 * 1024**3)

        def bounded():
            resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))

        def run(arguments, timeout):
            started = time.monotonic()
            with subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True, preexec_fn=bounded, start_new_session=True) as child:
                try:
                    while True:
                        self.assertGreaterEqual(available(), 6 * 1024**3,
                                                'source test yields before physical host reserve')
                        self.assertLess(time.monotonic() - started, timeout)
                        try:
                            output, _ = child.communicate(timeout=.25)
                            return subprocess.CompletedProcess(arguments, child.returncode, output, '')
                        except subprocess.TimeoutExpired as pending:
                            progress = getattr(self, 'native_progress_path', None)
                            if progress and str(arguments[0]).endswith('/vvp'):
                                Path(progress).write_bytes(pending.output or b'')
                finally:
                    terminate_process_group(child)
                    child.communicate()

        units = ('cluster_projection', 'sparse_weight_dma', 'compute_cluster',
                 'memory_compute', 'pe_array', 'word_bank')
        with tempfile.TemporaryDirectory(prefix='fabric_projection_', dir='.cache') as directory:
            binary = Path(directory) / 'projection.vvp'
            compiled = run([
                '.cache/tools/iverilog', '-B', '.cache/tools/ivl', '-g2012',
                '-s', 'tri_oracle_fabric_projection_tb', '-o', str(binary),
                getattr(self, 'source_path', 'verilog/tri_oracle_fabric_projection.sv'),
                *(getattr(self, 'dependency_overrides', {}).get(
                    unit, f'verilog/tri_oracle_{unit}.sv') for unit in units),
                'verilog/tri_oracle_fabric_projection_tb.sv'], 90)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            native = run(['.cache/tools/vvp', '-M', '.cache/tools/ivl', str(binary)], 5400)
        self.assertFalse(Path(directory).exists())
        self.assertEqual(native.returncode, 0, native.stdout + native.stderr)
        self.assertEqual(native.stdout.count('FABRIC_PROJECTION_CASE_PASS'), 43, native.stdout)
        self.assertIn('FABRIC_PROJECTION_PASS cases=43', native.stdout)
        self.native_stdout = native.stdout


if __name__ == '__main__':
    unittest.main()
