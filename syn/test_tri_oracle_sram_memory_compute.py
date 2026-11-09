"""Actual compiler models and independent arithmetic/transaction scoreboards."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parent))
from test_tri_oracle_sram_activation_cache import run_bounded


def models(corner):
    result = []
    for name in ['records/sram_core_bank_views.json',
                 'records/sram_activation_cache_bank_views.json']:
        banks = json.loads(Path(name).read_text())['banks']
        for key, bank in banks.items():
            if key == 'metadata':
                continue
            model = bank['models'][corner]
            assert hashlib.sha256(Path(model).read_bytes()).hexdigest() == bank['sha256'][model]
            result.append(model)
    return result


class CompiledMemoryComputeTest(unittest.TestCase):
    def simulate(self, bench, original=False, fault=None):
        available = int(next(line.split()[1] for line in
                             Path('/proc/meminfo').read_text().splitlines()
                             if line.startswith('MemAvailable:'))) * 1024
        self.assertGreater(available, 6 * 1024**3)
        for corner in (['original'] if original else ['tt1v25c'] if fault else
                       ['tt1v25c', 'ssg0p9v125c', 'ffg1p05vm40c']):
            with self.subTest(corner=corner):
                with tempfile.TemporaryDirectory(prefix='sram_compute_', dir='.cache') as folder:
                    source = Path(folder) / 'bench.sv'
                    source.write_text(bench if original else bench.replace(
                        'tri_oracle_memory_compute dut', 'tri_oracle_sram_memory_compute dut'))
                    binary = Path(folder) / 'sim.vvp'
                    dependencies = ['verilog/tri_oracle_memory_compute.sv',
                                    'verilog/tri_oracle_word_bank.sv'] if original else [
                        'verilog/tri_oracle_sram_memory_compute.sv', *models(corner)]
                    if fault:
                        text = Path(dependencies[0]).read_text()
                        self.assertEqual(text.count(fault[0]), 1)
                        broken = Path(folder) / 'broken.sv'
                        broken.write_text(text.replace(fault[0], fault[1]))
                        dependencies[0] = str(broken)
                    compiled = run_bounded(['iverilog', '-g2012', '-DUNIT_DELAY', '-s',
                                            'tri_oracle_memory_compute_tb', '-o', str(binary),
                                            'verilog/tri_oracle_pe_array.sv',
                                            *dependencies, str(source)])
                    self.assertEqual(compiled['exit_status'], 0, compiled['stderr'])
                    ran = run_bounded(['vvp', str(binary)])
                    if fault:
                        self.assertNotEqual(ran['exit_status'], 0)
                        self.assertIn(fault[2], ran['stdout'])
                        print('REJECTED_HDL_FAULT', fault[2], flush=True)
                        continue
                    self.assertEqual(ran['exit_status'], 0, ran['stdout'] + ran['stderr'])
                    self.assertIn('PASS:', ran['stdout'])
                    print(corner, ran['stdout'].strip(), flush=True)

    def test_original_full_capacity_contract_at_actual_model_corners(self):
        self.simulate(Path('verilog/tri_oracle_memory_compute_tb.sv').read_text())

    def test_independent_hazard_scoreboard_on_original(self):
        self.simulate(Path('verilog/tri_oracle_sram_memory_hazards_tb.sv').read_text(), True)

    def test_masked_writes_collisions_forwarding_backpressure_and_retention(self):
        self.simulate(Path('verilog/tri_oracle_sram_memory_hazards_tb.sv').read_text())

    def test_actual_faults_are_rejected(self):
        faults = [
            ('accumulator_forward_data <= writeback_data;',
             'accumulator_forward_data <= 0;', 'CORE_READ_OLD_OR_FORWARD'),
            ('weight_bweb[row*64+:64] = {64{!load_row_enable[row]}};',
             'weight_bweb[row*64+:64] = 0;', 'CORE_READ_OLD_OR_FORWARD'),
            ('if (current_write_hit) response_bypass_data <= accumulator_word;',
             'if (current_write_hit) response_bypass_data <= writeback_data;',
             'CORE_READ_OLD_OR_FORWARD'),
            ('recent_valid <= 1;', 'recent_valid <= 0;', 'CORE_COMPLETION_READ_THROUGHPUT'),
            (': held_result;', ": (rst_n ? output_q : 1024'b0);", 'CORE_RESPONSE_HOLD'),
            ('writeback_valid <= 0;', 'writeback_valid <= writeback_valid;',
             'CORE_COMPLETION_ORDER'),
        ]
        for fault in faults:
            with self.subTest(fault=fault[0]):
                self.simulate(Path('verilog/tri_oracle_sram_memory_hazards_tb.sv').read_text(),
                              fault=fault)


if __name__ == '__main__':
    unittest.main()
