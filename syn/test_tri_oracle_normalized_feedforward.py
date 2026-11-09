"""Real source simulation from residual prediction through matrix/down sums.

Wrong bus ownership, stale group metadata, skipped-row reads, leaked partial
outputs on error, or a reset context surviving into the next tensor must fail.
"""
from pathlib import Path
import resource
import subprocess
import tempfile
import unittest


class NormalizedFeedforwardTest(unittest.TestCase):
    def test_native_prediction_compute_shared_memory_errors_and_reset(self):
        available = int(next(line.split()[1] for line in
                             Path('/proc/meminfo').read_text().splitlines()
                             if line.startswith('MemAvailable:')))*1024
        self.assertGreaterEqual(available, 8*1024**3)

        def bounded():
            resource.setrlimit(resource.RLIMIT_AS, (2*1024**3, 2*1024**3))

        names = ('rmsnorm', 'sign_fetch', 'prediction_feedforward_core', 'feedforward_core', 'strip_predictor',
                 'channel_compactor', 'predicted_dispatch', 'silu_gate', 'gated_executor',
                 'tile_executor', 'sparse_weight_dma', 'down_executor', 'memory_compute',
                 'pe_array', 'word_bank')
        with tempfile.TemporaryDirectory(prefix='normalized_ff_test_', dir='.cache') as directory:
            root = Path(directory)
            binary = root/'integrated.vvp'
            compiled = subprocess.run([
                'iverilog', '-g2012', '-s', 'tri_oracle_normalized_feedforward_core_tb',
                '-o', str(binary),
                getattr(self, 'source_path', 'verilog/tri_oracle_normalized_feedforward_core.sv'),
                *(f'verilog/tri_oracle_{name}.sv' for name in names),
                'verilog/tri_oracle_normalized_feedforward_core_tb.sv'],
                text=True, capture_output=True, timeout=90, preexec_fn=bounded)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run(['vvp', str(binary)], text=True,
                                    capture_output=True, timeout=180, preexec_fn=bounded)
        self.assertFalse(root.exists())
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertEqual(result.stdout.count('NORMALIZED_FEEDFORWARD_PASS'), 1)
        self.assertEqual(result.stdout.count('NORMALIZED_FF_CASE_PASS'), 20)
        self.native_stdout = result.stdout


if __name__ == '__main__':
    unittest.main()
