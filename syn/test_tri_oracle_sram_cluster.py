"""Independent cluster arithmetic/queue tests with real compiler memories."""
from pathlib import Path
import resource
import subprocess
import tempfile
import unittest

from test_tri_oracle_sram_memory_compute import models


class SramClusterTest(unittest.TestCase):
    def simulate(self, original=False, fault=None, public=False):
        available = int(next(line.split()[1] for line in
            Path('/proc/meminfo').read_text().splitlines()
            if line.startswith('MemAvailable:'))) * 1024
        self.assertGreater(available, 10*1024**3)

        def bounds():
            resource.setrlimit(resource.RLIMIT_AS, (2*1024**3, 2*1024**3))
            resource.setrlimit(resource.RLIMIT_CPU, (120, 120))

        corners = ['original'] if original else ['tt1v25c'] if fault or public else [
            'tt1v25c', 'ssg0p9v125c', 'ffg1p05vm40c']
        for corner in corners:
            with self.subTest(corner=corner):
                with tempfile.TemporaryDirectory(prefix='sram_cluster_', dir='.cache') as folder:
                    bench = Path(folder)/'bench.sv'
                    source = Path('verilog/tri_oracle_sram_cluster_tb.sv').read_text()
                    if public:
                        source = source.replace('dut.reduce_four', 'dut.implementation.reduce_four')
                        source = source.replace('dut.aggregate_memory',
                                                'dut.implementation.aggregate_memory')
                    elif not original:
                        source = source.replace('tri_oracle_compute_cluster dut',
                                                'tri_oracle_sram_compute_cluster dut')
                    bench.write_text(source)
                    binary = Path(folder)/'sim.vvp'
                    units = ['verilog/tri_oracle_compute_cluster.sv',
                             'verilog/tri_oracle_memory_compute.sv',
                             'verilog/tri_oracle_word_bank.sv'] if original else [
                                 'verilog/tri_oracle_sram_compute_cluster.sv',
                                 'verilog/tri_oracle_sram_memory_compute.sv', *models(corner)]
                    if fault:
                        text = Path(units[0]).read_text()
                        self.assertEqual(text.count(fault[0]), 1)
                        broken = Path(folder)/'broken.sv'
                        broken.write_text(text.replace(fault[0], fault[1]))
                        units[0] = str(broken)
                    defines = [] if original else ['-DTRI_ORACLE_CHECK_CLUSTER_MEMORY']
                    if public:
                        defines.append('-DTRI_ORACLE_SRAM_CLUSTER_BIND_PUBLIC')
                    compiled = subprocess.run(['iverilog', '-g2012', '-DUNIT_DELAY', *defines, '-s',
                        'tri_oracle_compute_cluster_tb', '-o', str(binary),
                        'verilog/tri_oracle_pe_array.sv', *units, str(bench)],
                        capture_output=True, text=True, timeout=120, preexec_fn=bounds)
                    self.assertEqual(compiled.returncode, 0, compiled.stderr[-4000:])
                    ran = subprocess.run(['vvp', str(binary)], capture_output=True, text=True,
                                         timeout=120, preexec_fn=bounds)
                    if fault:
                        self.assertNotEqual(ran.returncode, 0)
                        self.assertIn(fault[2], ran.stdout)
                        print('REJECTED_CLUSTER_HDL_FAULT', fault[2], flush=True)
                        continue
                    self.assertEqual(ran.returncode, 0, ran.stdout+ran.stderr)
                    self.assertIn('SRAM_CLUSTER_PASS outputs=36', ran.stdout)
                    print(corner, ran.stdout.strip(), flush=True)

    def test_original_cluster_establishes_independent_scoreboard(self):
        self.simulate(original=True)

    def test_actual_compiled_core_and_aggregation_memories(self):
        self.simulate()

    def test_public_backend_selection(self):
        self.simulate(public=True)

    def test_actual_aggregation_queue_and_reset_faults_are_rejected(self):
        faults = [
            ('1: return ab > cd ? ab : cd;', '1: return ab < cd ? ab : cd;',
             'CLUSTER_REDUCTION_BOUNDARY'),
            ("2: return 32'(total >>> 2);", "2: return 32'(total);",
             'CLUSTER_REDUCTION_BOUNDARY'),
            ('output_forward <= read_collision;', 'output_forward <= 0;',
             'CLUSTER_ARITHMETIC'),
            ("next_head = retire ? head + 4'd1 : head;",
             "next_head = retire ? head + 4'd2 : head;", 'CLUSTER_OUTPUT_ORDER'),
            ('if (!out_valid || out_ready) begin', "if (1'b1) begin",
             'CLUSTER_OUTPUT_CHANGED_WHILE_STALLED'),
            ('out_valid <= 0;', 'out_valid <= 1;', 'CLUSTER_RESET_FLUSH'),
            ('aggregate_reb = !(output_refill && !read_collision);',
             'aggregate_reb = !output_refill;', 'CLUSTER_NATIVE_READ_WRITE_COLLISION'),
        ]
        for fault in faults:
            with self.subTest(fault=fault[0]):
                self.simulate(fault=fault)


if __name__ == '__main__':
    unittest.main()
