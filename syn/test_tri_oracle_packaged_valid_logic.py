"""Exercise array valid-state proof against independently enumerated controls."""
from itertools import product
import importlib.util
from pathlib import Path
import unittest

SOURCE = Path(__file__).with_name('prove_tri_oracle_packaged_valid.py')


class ValidLogicTests(unittest.TestCase):
    def engine(self):
        self.assertTrue(SOURCE.exists(), 'Mapped valid-state proof is not implemented')
        spec = importlib.util.spec_from_file_location('valid_proof', SOURCE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def functions(self):
        from prove_tri_oracle_packaged_products import BooleanGraph
        graph = BooleanGraph()
        current = [graph.variable(name) for name in ('valid[0]', 'valid[1]', 'valid[2]', 'out_valid')]
        ready = graph.function('!V + R', {'V': current[3], 'R': graph.variable('out_ready')})
        incoming = [graph.variable('in_valid'), *current[:3]]
        data = [graph.function('(E D)+(!E Q)', dict(E=ready, D=d, Q=q))
                for d, q in zip(incoming, current, strict=True)]
        aliases = ['p1', 'p1', 'p2', 'rst_n']
        clear = [graph.function('!C', {'C': graph.variable(alias)}) for alias in aliases]
        return graph, ready, data, clear, aliases

    def test_all_states_inputs_and_independent_resets(self):
        engine = self.engine()
        functions = self.functions()
        result = engine.prove_control_functions(*functions)
        self.assertEqual(result['independent_integer_cases'], 512)
        self.assertEqual(result['valid_registers'], 4)
        self.assertTrue(result['asynchronous_clear_verified'])

    def test_blocked_pipeline_keeps_each_state_bit(self):
        engine = self.engine()
        graph, ready, data, clear, aliases = self.functions()
        result = engine.prove_control_functions(graph, ready, data, clear, aliases)
        self.assertTrue(result['stall_and_advance_verified'])
        for bits in product(range(2), repeat=3):
            values = dict(zip(['valid[0]', 'valid[1]', 'valid[2]'], bits, strict=True))
            values.update(out_valid=1, out_ready=0, in_valid=1)
            self.assertEqual(graph.evaluate(data, values, 1), [*bits, 1])

    def test_ready_must_allow_an_empty_output_to_advance(self):
        engine = self.engine()
        graph, ready, data, clear, aliases = self.functions()
        with self.assertRaisesRegex(AssertionError, 'Ready'):
            engine.prove_control_functions(graph, graph.variable('out_ready'), data, clear, aliases)

    def test_wrong_valid_source_is_rejected(self):
        engine = self.engine()
        graph, ready, data, clear, aliases = self.functions()
        data[2] = graph.function('(E D)+(!E Q)', dict(
            E=ready, D=graph.variable('valid[0]'), Q=graph.variable('valid[2]')))
        with self.assertRaisesRegex(AssertionError, 'Valid transition'):
            engine.prove_control_functions(graph, ready, data, clear, aliases)

    def test_active_high_clear_is_rejected(self):
        engine = self.engine()
        graph, ready, data, clear, aliases = self.functions()
        clear[0] = graph.variable('p1')
        with self.assertRaisesRegex(AssertionError, 'Asynchronous clear'):
            engine.prove_control_functions(graph, ready, data, clear, aliases)

    def test_foreign_state_and_nonreset_pin_are_rejected(self):
        engine = self.engine()
        graph, ready, data, clear, aliases = self.functions()
        data[0] = graph.operation('^', data[0], graph.variable('foreign_state'))
        with self.assertRaisesRegex(AssertionError, 'Foreign control'):
            engine.prove_control_functions(graph, ready, data, clear, aliases)
        graph, ready, data, clear, aliases = self.functions()
        aliases[0] = 'out_ready'
        with self.assertRaisesRegex(AssertionError, 'Reset alias'):
            engine.prove_control_functions(graph, ready, data, clear, aliases)

    def test_enable_feedback_and_clear_models_are_preserved(self):
        engine = self.engine()
        primary = ('ff(IQ,IQN){clear:"(!CDN)";clocked_on:"CP";'
                   'next_state:"((E D)+(!E IQ))";}')
        nested = 'test_cell(){ff(IQ,IQN){clocked_on:"CP";next_state:"D";}}'
        self.assertEqual(engine.valid_flip_flop(primary + nested), {
            'clear': '(!CDN)', 'clocked_on': 'CP', 'next_state': '((E D)+(!E IQ))'})
        for bad in [primary + primary, primary.replace('"CP"', '"!CP"'),
                    primary.replace('clear:', 'preset:'),
                    primary.replace('ff(IQ,IQN)', 'ff(other,IQN)')]:
            with self.assertRaises(ValueError):
                engine.valid_flip_flop(bad)


if __name__ == '__main__':
    unittest.main()
