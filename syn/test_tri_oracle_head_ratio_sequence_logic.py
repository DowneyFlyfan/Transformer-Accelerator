"""Exercise real scan/enable equations and primary asynchronous state models."""
from itertools import product
import importlib.util
from pathlib import Path
import unittest

SOURCE = Path(__file__).with_name('prove_tri_oracle_head_ratio_sequence.py')


class RatioSequenceTests(unittest.TestCase):
    def engine(self):
        self.assertTrue(SOURCE.exists(), 'Head-ratio sequence proof is not implemented')
        spec = importlib.util.spec_from_file_location('ratio_sequence', SOURCE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_primary_preset_and_scan_state_ignore_nested_test_model(self):
        engine = self.engine()
        primary = 'ff(IQ,IQN){clocked_on:"CP";next_state:"((SE SI) + (!SE D))";preset:"(!SDN)";}'
        nested = 'test_cell(){ff(IQ,IQN){clocked_on:"!CP";next_state:"!D";}}'
        self.assertEqual(engine.primary_state(primary + nested),
                         dict(clocked_on='CP', next_state='((SE SI) + (!SE D))', preset='(!SDN)'))

    def test_multiple_primary_groups_and_unknown_state_attributes_are_rejected(self):
        engine = self.engine()
        valid = 'ff(IQ,IQN){clocked_on:"CP";next_state:"D";clear:"!CDN";}'
        for invalid in [valid + valid, valid.replace('}', 'preset:"!SDN";}'),
                        valid.replace('}', 'unknown:"D";}')]:
            with self.assertRaises((AssertionError, ValueError)):
                engine.primary_state(invalid)

    def test_enabled_state_uses_feedback_instead_of_assuming_data_pin(self):
        engine = self.engine()
        body = b'module sample(clk,rst_n,d,e,q); input clk,rst_n,d,e; output q; FF r(.CP(clk),.CDN(rst_n),.D(d),.E(e),.Q(q)); endmodule'
        library = {('FF', name): {'direction': 'input'} for name in ['CP', 'CDN', 'D', 'E']}
        library['FF', 'Q'] = dict(direction='output', function='IQ')
        library['FF', '__sequence_ff__'] = dict(clocked_on='CP', next_state='((E D) + (!E IQ))', clear='(!CDN)')
        model = engine.SequentialClassifier(body, library, {'FF': {'ff': 1}})
        data, reset, reset_value = model.transition('r', 'q')
        self.assertEqual(reset_value, 0)
        for d, e, q, rst_n in product(range(2), repeat=4):
            actual = model.graph.evaluate([data, reset], dict(d=d, e=e, q=q, rst_n=rst_n))
            self.assertEqual(actual, [d if e else q, 1-rst_n])

    def test_register_wrong_clock_and_wrong_output_polarity_are_rejected(self):
        engine = self.engine()
        library = {('FF', name): {'direction': 'input'} for name in ['CP', 'CDN', 'D']}
        library['FF', 'Q'] = dict(direction='output', function='IQ')
        library['FF', '__sequence_ff__'] = dict(clocked_on='CP', next_state='D', clear='!CDN')
        for clock, polarity in [('d', 'IQ'), ('clk', 'IQN')]:
            body = f'module sample(clk,rst_n,d,q); input clk,rst_n,d; output q; FF r(.CP({clock}),.CDN(rst_n),.D(d),.Q(q)); endmodule'.encode()
            altered = library | {('FF', 'Q'): dict(direction='output', function=polarity)}
            model = engine.SequentialClassifier(body, altered, {'FF': {'ff': 1}})
            with self.assertRaises(AssertionError):
                model.transition('r', 'q')

    def test_clock_and_reset_must_be_scalar_inputs(self):
        engine = self.engine()
        for body in [b'module sample(clk,rst_n); output clk; input rst_n; endmodule',
                     b'module sample(clk,rst_n); input clk; output rst_n; endmodule']:
            with self.assertRaisesRegex(AssertionError, 'Clock/reset port'):
                engine.SequentialClassifier(body, {}, {})

    def test_retention_proof_eliminates_irrelevant_large_score_comparator(self):
        engine = self.engine()
        from prove_tri_oracle_packaged_products import BooleanGraph
        boolean = BooleanGraph()
        less, equal = 0, 1
        for bit in range(19, -1, -1):
            a, b = boolean.variable(f'a[{bit}]'), boolean.variable(f'b[{bit}]')
            less = boolean.operation('|', less, boolean.operation('&', equal, boolean.operation('&', boolean.operation('!', a), b)))
            equal = boolean.operation('&', equal, boolean.operation('!', boolean.operation('^', a, b)))
        q = boolean.variable('q')
        observed = boolean.operation('&', boolean.operation('|', q, less),
                                     boolean.operation('|', q, boolean.operation('!', less)))
        try:
            engine.equal_functions(boolean, [observed], [q])
        except ValueError as error:
            self.fail(f'Irrelevant comparator exhausted the retention proof: {error}')
        for wrong in (0, 1):
            with self.assertRaisesRegex(AssertionError, 'transition differs'):
                engine.equal_functions(boolean, [wrong], [q])


if __name__ == '__main__':
    unittest.main()
