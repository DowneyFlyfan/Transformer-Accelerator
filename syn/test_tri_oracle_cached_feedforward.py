"""Native once-per-token activation generation, cached reads and group reuse."""
from pathlib import Path
import resource
import subprocess
import tempfile
import unittest


class CachedFeedforwardTest(unittest.TestCase):
    def test_native_generated_activations_local_reads_prediction_reuse_and_errors(self):
        available = int(next(line.split()[1] for line in
                             Path('/proc/meminfo').read_text().splitlines()
                             if line.startswith('MemAvailable:')))*1024
        self.assertGreaterEqual(available, 8*1024**3)

        def bounded():
            resource.setrlimit(resource.RLIMIT_AS, (2*1024**3, 2*1024**3))

        names = ('activation_cache', 'rms_activation', 'affine_quantizer', 'rmsnorm',
                 'sign_fetch', 'prediction_feedforward_core', 'normalized_feedforward_core',
                 'feedforward_core', 'strip_predictor', 'channel_compactor',
                 'predicted_dispatch', 'silu_gate', 'gated_executor', 'tile_executor',
                 'sparse_weight_dma', 'down_executor', 'memory_compute', 'pe_array', 'word_bank')
        with tempfile.TemporaryDirectory(prefix='cached_ff_test_', dir='.cache') as directory:
            root = Path(directory);binary = root/'cached.vvp'
            compiled = subprocess.run([
                'iverilog', '-g2012', '-s', 'tri_oracle_normalized_feedforward_core_tb',
                '-P', 'tri_oracle_normalized_feedforward_core_tb.CACHED_MODE=1', '-o', str(binary),
                getattr(self, 'source_path', 'verilog/tri_oracle_cached_feedforward_core.sv'),
                *(f'verilog/tri_oracle_{name}.sv' for name in names),
                'verilog/tri_oracle_normalized_feedforward_core_tb.sv'],
                text=True, capture_output=True, timeout=90, preexec_fn=bounded)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            native = subprocess.run(['vvp', str(binary)], text=True, capture_output=True,
                                    timeout=180, preexec_fn=bounded)
        self.assertFalse(root.exists())
        self.assertEqual(native.returncode, 0, native.stdout+native.stderr)
        self.assertEqual(native.stdout.count('NORMALIZED_FF_CASE_PASS'), 24)
        self.assertEqual(native.stdout.count('NORMALIZED_FEEDFORWARD_PASS'), 1)
        self.native_stdout = native.stdout


if __name__ == '__main__':
    unittest.main()
