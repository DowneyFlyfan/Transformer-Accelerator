"""Check the symbolic addition engine against exhaustive small integer sums."""
from itertools import product
import importlib.util
from pathlib import Path
import unittest

SOURCE = Path(__file__).with_name('prove_tri_oracle_packaged_reductions.py')


class ReductionLogicTests(unittest.TestCase):
    def engine(self):
        self.assertTrue(SOURCE.exists(), 'Mapped reduction proof engine is not implemented')
        spec = importlib.util.spec_from_file_location('reduction_proof', SOURCE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_boolean_operations_match_all_three_input_assignments(self):
        graph = self.engine().DecisionGraph(['a', 'b', 'c'])
        a, b, c = [graph.variable(name) for name in ('a', 'b', 'c')]
        outputs = [graph.operation('&', a, b), graph.operation('|', a, b),
                   graph.operation('^', a, b), graph.operation('!', c)]
        for x, y, z in product(range(2), repeat=3):
            self.assertEqual([graph.evaluate(node, dict(a=x, b=y, c=z)) for node in outputs],
                             [x & y, x | y, x ^ y, 1 - z])

    def test_equivalent_functions_have_identical_nodes(self):
        graph = self.engine().DecisionGraph(['a', 'b', 'c'])
        a, b, c = [graph.variable(name) for name in ('a', 'b', 'c')]
        left = graph.operation('!', graph.operation('&', a, b))
        right = graph.operation('|', graph.operation('!', a), graph.operation('!', b))
        self.assertEqual(left, right)
        first = graph.operation('|', graph.operation('&', a, b), graph.operation('&', c, graph.operation('^', a, b)))
        second = graph.operation('|', graph.operation('&', a, b), graph.operation('|', graph.operation('&', a, c), graph.operation('&', b, c)))
        self.assertEqual(first, second)
        self.assertEqual(graph.operation('^', first, second), 0)

    def test_signed_addition_matches_all_five_bit_integer_pairs(self):
        graph = self.engine().DecisionGraph([f'{word}{bit}' for bit in range(5) for word in ('a', 'b')])
        left = [graph.variable(f'a{bit}') for bit in range(5)]
        right = [graph.variable(f'b{bit}') for bit in range(5)]
        sums = graph.signed_sum(left, right)
        self.assertEqual(len(sums), 6)
        for a, b in product(range(32), repeat=2):
            values = {f'{word}{bit}': (value >> bit) & 1
                      for word, value in [('a', a), ('b', b)] for bit in range(5)}
            actual = sum(graph.evaluate(node, values) << bit for bit, node in enumerate(sums))
            signed_a, signed_b = a - 32 if a >= 16 else a, b - 32 if b >= 16 else b
            self.assertEqual(actual, (signed_a + signed_b) & 63)

    def test_distinct_variables_unknowns_and_memory_bound(self):
        engine = self.engine()
        with self.assertRaises(ValueError):
            engine.DecisionGraph(['a', 'a'])
        graph = engine.DecisionGraph(['a', 'b'], maximum_nodes=3)
        self.assertNotEqual(graph.variable('a'), 0)
        with self.assertRaises(ValueError):
            graph.variable('b')
        with self.assertRaises(KeyError):
            graph.variable('unknown')

    def test_conversion_preserves_a_mapped_boolean_function(self):
        engine = self.engine()
        from prove_tri_oracle_packaged_products import BooleanGraph
        mapped = BooleanGraph()
        a, b = mapped.variable('a'), mapped.variable('b')
        root = mapped.function('!((A B) + (!A !B))', {'A': a, 'B': b})
        graph = engine.DecisionGraph(['a', 'b'])
        converted, = graph.convert(mapped, [root])
        self.assertEqual(converted, graph.operation('^', graph.variable('a'), graph.variable('b')))
        with self.assertRaises(KeyError):
            graph.convert(mapped, [mapped.variable('foreign')])

    def test_scan_hold_transition_ignores_nested_test_cell(self):
        engine = self.engine()
        primary = 'ff(IQ,IQN){clocked_on:"CP"; next_state:"((SE SI) + (!SE D))";}'
        nested = 'test_cell(){ff(IQ,IQN){clocked_on:"CP"; next_state:"D";}}'
        expected = {'clocked_on': 'CP', 'next_state': '((SE SI) + (!SE D))'}
        self.assertEqual(engine.sum_flip_flop(primary + nested), expected)
        for bad in [primary.replace('"CP"', '"!CP"'), primary + primary,
                    primary.replace('}', 'clear:"!CDN";}')]:
            with self.assertRaises(ValueError):
                engine.sum_flip_flop(bad)


if __name__ == '__main__':
    unittest.main()
