"""Run the real reader against independent memory/stream contract checks."""
from pathlib import Path
import resource
import subprocess
import tempfile
import unittest


class ActivationLoaderTest(unittest.TestCase):
    def test_native_memory_order_bounds_fault_drain_stalls_and_reset(self):
        available = int(next(line.split()[1] for line in
                             Path('/proc/meminfo').read_text().splitlines()
                             if line.startswith('MemAvailable:'))) * 1024
        self.assertGreaterEqual(available, 4 * 1024**3)

        def bounded():
            resource.setrlimit(resource.RLIMIT_AS, (512 * 1024**2, 512 * 1024**2))

        with tempfile.TemporaryDirectory(prefix='activation_loader_', dir='.cache') as directory:
            binary = Path(directory) / 'loader.vvp'
            compiled = subprocess.run([
                'iverilog', '-g2012', '-s', 'tri_oracle_activation_loader_tb',
                '-o', str(binary),
                getattr(self, 'source_path', 'verilog/tri_oracle_activation_loader.sv'),
                'verilog/tri_oracle_activation_loader_tb.sv'],
                text=True, capture_output=True, timeout=30, preexec_fn=bounded)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            native = subprocess.run(['vvp', str(binary)], text=True, capture_output=True,
                                    timeout=30, preexec_fn=bounded)
        self.assertFalse(Path(directory).exists())
        self.assertEqual(native.returncode, 0, native.stdout + native.stderr)
        self.assertEqual(native.stdout.count('ACTIVATION_LOADER_CASE_PASS'), 20)
        self.assertIn('ACTIVATION_LOADER_PASS cases=20 reset_recoveries=2', native.stdout)
        self.native_stdout = native.stdout


if __name__ == '__main__':
    unittest.main()
