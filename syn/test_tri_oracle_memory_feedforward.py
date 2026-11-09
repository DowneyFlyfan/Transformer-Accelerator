"""Native memory-driven preparation joined to prediction and gate/up/down."""
from pathlib import Path
import resource
import subprocess
import tempfile
import unittest


class MemoryFeedforwardTest(unittest.TestCase):
    def test_native_memory_driven_preparation_compute_faults_and_recovery(self):
        available = int(next(line.split()[1] for line in
                             Path('/proc/meminfo').read_text().splitlines()
                             if line.startswith('MemAvailable:'))) * 1024
        self.assertGreaterEqual(available, 8 * 1024**3)

        def bounded():
            resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))

        units = ('activation_loader', 'cached_feedforward_core', 'activation_cache',
                 'rms_activation', 'affine_quantizer', 'rmsnorm', 'sign_fetch',
                 'prediction_feedforward_core', 'feedforward_core', 'strip_predictor',
                 'channel_compactor', 'predicted_dispatch', 'silu_gate', 'gated_executor',
                 'tile_executor', 'sparse_weight_dma', 'down_executor', 'memory_compute',
                 'pe_array', 'word_bank')
        with tempfile.TemporaryDirectory(prefix='memory_ff_', dir='.cache') as directory:
            binary = Path(directory) / 'core.vvp'
            compiled = subprocess.run([
                'iverilog', '-g2012', '-s', 'tri_oracle_memory_feedforward_core_tb',
                '-o', str(binary),
                getattr(self, 'source_path', 'verilog/tri_oracle_memory_feedforward_core.sv'),
                *(getattr(self, 'dependency_overrides', {}).get(
                    unit, f'verilog/tri_oracle_{unit}.sv') for unit in units),
                'verilog/tri_oracle_memory_feedforward_core_tb.sv'],
                text=True, capture_output=True, timeout=90, preexec_fn=bounded)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            native = subprocess.run(['vvp', str(binary)], text=True, capture_output=True,
                                    timeout=180, preexec_fn=bounded)
        self.assertFalse(Path(directory).exists())
        self.assertEqual(native.returncode, 0, native.stdout + native.stderr)
        self.assertEqual(native.stdout.count('MEMORY_FF_CASE_PASS'), 34)
        self.assertIn('MEMORY_FEEDFORWARD_PASS cases=34', native.stdout)
        self.native_stdout = native.stdout


if __name__ == '__main__':
    unittest.main()
