"""Run the real feed-forward bench with and without a high address-bit fault."""
from pathlib import Path
import resource
import subprocess
import tempfile
import unittest


class FeedforwardAddressCheckerTest(unittest.TestCase):
    def run_bench(self, corrupt_down_address):
        available = int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines()
                             if line.startswith('MemAvailable:'))) * 1024
        anonymous = int(dict(line.split() for line in
                             Path('/sys/fs/cgroup/memory.stat').read_text().splitlines())['anon'])
        self.assertGreaterEqual(available, 8 * 1024**3)
        self.assertLess(anonymous + 2 * 1024**3, 18 * 1024**3)
        source = Path('verilog/tri_oracle_feedforward_core_tb.sv').read_text()
        if corrupt_down_address:
            # 2**32 * 192 aliases int32 rows for every exercised dense stride.
            # Perturb the actual request bus seen by the checker/memory model;
            # leave the design, response values and independent sums unchanged.
            declaration = 'wire [63:0] req_address;'
            instance = 'tri_oracle_feedforward_core dut(.*);'
            self.assertEqual(source.count(declaration), 1)
            self.assertEqual(source.count(instance), 1)
            source = source.replace(declaration, '''wire [63:0] injected_raw_address;
    wire [63:0] req_address = injected_raw_address +
        (injected_raw_address >= 64'h80000000 ? 64'h000000c000000000 : 64'd0);''')
            source = source.replace(instance,
                                    'tri_oracle_feedforward_core dut(.req_address(injected_raw_address), .*);')
        units = ('strip_predictor channel_compactor predicted_dispatch sparse_weight_dma '
                 'tile_executor silu_gate gated_executor down_executor feedforward_core '
                 'memory_compute word_bank pe_array').split()

        def bound():
            resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))

        with tempfile.TemporaryDirectory(prefix='feedforward_address_checker_', dir='.cache') as directory:
            root = Path(directory)
            bench, binary = root / 'bench.sv', root / 'simulation.vvp'
            bench.write_text(source)
            compiled = subprocess.run(
                ['iverilog', '-g2012', '-s', 'tri_oracle_feedforward_core_tb', '-o', str(binary),
                 *[f'verilog/tri_oracle_{unit}.sv' for unit in units], str(bench)],
                capture_output=True, text=True, timeout=60, preexec_fn=bound)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            result = subprocess.run(['vvp', str(binary)], capture_output=True, text=True,
                                    timeout=180, preexec_fn=bound)
        self.assertFalse(root.exists())
        return result

    def test_rejects_upper_down_address_bits_before_row_narrowing(self):
        result = self.run_bench(True)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('down request outside full-width output range', result.stdout + result.stderr)
        self.assertNotIn('PASS: prediction-to-gate/up-to-sparse-down', result.stdout)

    def test_unmodified_design_preserves_all_bench_cases(self):
        result = self.run_bench(False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.count('PASS: prediction-to-gate/up-to-sparse-down'), 1)


if __name__ == '__main__':
    unittest.main()
