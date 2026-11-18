"""Check carry/borrow semantics and reject missing or ambiguous mapped drivers."""
from itertools import product
import importlib.util
from pathlib import Path
import unittest

SOURCE = Path(__file__).with_name('prove_tri_oracle_head_ratio.py')


class HeadRatioTests(unittest.TestCase):
    def engine(self):
        self.assertTrue(SOURCE.exists(), 'Mapped head-ratio proof is not implemented')
        spec = importlib.util.spec_from_file_location('head_ratio', SOURCE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_update_matches_exhaustive_three_bit_integer_carries_and_borrows(self):
        engine = self.engine()
        names = ['den', 'num'] + [f'{word}{bit}' for bit in range(3) for word in ('d', 'o', 'i')]
        graph = engine.DecisionGraph(names)
        d, o, i = ([graph.variable(f'{word}{bit}') for bit in range(3)] for word in ('d', 'o', 'i'))
        roots = engine.update_bits(graph, d, o, i, graph.variable('den'), graph.variable('num'))
        for difference, outer, inner, den, num in product(range(8), range(8), range(8), range(2), range(2)):
            values = dict(den=den, num=num)
            values.update({f'{word}{bit}': (value >> bit) & 1 for word, value in [('d', difference), ('o', outer), ('i', inner)] for bit in range(3)})
            actual = sum(graph.evaluate(root, values) << bit for bit, root in enumerate(roots))
            self.assertEqual(actual, ((difference << 1) + outer * den - inner * num) & 7)

    def test_update_checks_operand_widths(self):
        engine = self.engine()
        graph = engine.DecisionGraph([])
        with self.assertRaises(ValueError):
            engine.update_bits(graph, [], [0], [0], 0, 0)
        with self.assertRaises(ValueError):
            engine.update_bits(graph, [0], [0, 0], [0], 0, 0)

    def test_positive_comparison_rejects_zero_and_negative_boundaries(self):
        engine = self.engine()
        self.assertTrue(callable(getattr(engine, 'positive_bits', None)), 'Signed positive comparator is not implemented')
        graph = engine.DecisionGraph([f'x{bit}' for bit in range(5)])
        root = engine.positive_bits(graph, [graph.variable(f'x{bit}') for bit in range(5)])
        for value in range(32):
            assignment = {f'x{bit}': (value >> bit) & 1 for bit in range(5)}
            self.assertEqual(graph.evaluate(root, assignment), int(0 < value < 16))

    def test_capture_model_accepts_boolean_parentheses_but_rejects_polarity_changes(self):
        engine = self.engine()
        self.assertTrue(callable(getattr(engine, 'require_capture_ff', None)), 'Capture model qualifier is not implemented')
        good = dict(clocked_on='CP', next_state='D', clear='(!CDN)')
        engine.require_capture_ff(good)
        for field, wrong in [('clear', 'CDN'), ('next_state', '!D'), ('clocked_on', '!CP')]:
            with self.assertRaisesRegex(AssertionError, 'Capture register state model'):
                engine.require_capture_ff(good | {field: wrong})

    def test_original_gate_function_and_escaped_identifier_are_used(self):
        engine = self.engine()
        body = b'module sample(a,b,y); input a,b; output y; wire \\sum:carry ; XOR x(.A(a),.B(b),.Z(\\sum:carry )); BUF q(.I(\\sum:carry ),.Z(y)); endmodule'
        library = {('XOR', 'A'): {'direction': 'input'}, ('XOR', 'B'): {'direction': 'input'},
                   ('XOR', 'Z'): {'direction': 'output', 'function': 'A ^ B'},
                   ('BUF', 'I'): {'direction': 'input'}, ('BUF', 'Z'): {'direction': 'output', 'function': 'I'}}
        model = engine.ClassifierCone(body, library, {})
        root = model.cone('y')
        for a, b in product(range(2), repeat=2):
            self.assertEqual(model.graph.evaluate([root], dict(a=a, b=b)), [a ^ b])
        changed = dict(library)
        changed['XOR', 'Z'] = {'direction': 'output', 'function': 'A B'}
        other = engine.ClassifierCone(body, changed, {})
        self.assertNotEqual(other.graph.evaluate([other.cone('y')], dict(a=1, b=0)), [1])

    def test_undriven_internal_net_is_rejected_instead_of_becoming_an_input(self):
        engine = self.engine()
        model = engine.ClassifierCone(b'module sample(a,y); input a; output y; endmodule', {}, {})
        with self.assertRaisesRegex(AssertionError, 'driver'):
            model.cone('y')

    def test_input_with_internal_driver_and_multiple_output_drivers_are_rejected(self):
        engine = self.engine()
        library = {('BUF', 'I'): {'direction': 'input'}, ('BUF', 'Z'): {'direction': 'output', 'function': 'I'}}
        for body in [b'module sample(a,y); input a; output y; BUF q(.I(y),.Z(a)); endmodule',
                     b'module sample(a,y); input a; output y; BUF p(.I(a),.Z(y)); BUF q(.I(a),.Z(y)); endmodule']:
            with self.assertRaisesRegex(AssertionError, 'driver'):
                engine.ClassifierCone(body, library, {})


if __name__ == '__main__':
    unittest.main()
