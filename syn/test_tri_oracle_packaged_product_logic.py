"""Independent checks for the Boolean engine used on mapped product cones."""
from itertools import product
import importlib.util
from pathlib import Path
import unittest

SOURCE = Path(__file__).with_name('prove_tri_oracle_packaged_products.py')


class ProductLogicTests(unittest.TestCase):
    def load_engine(self):
        self.assertTrue(SOURCE.exists(), 'Mapped product proof engine is not implemented')
        spec = importlib.util.spec_from_file_location('product_proof', SOURCE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_full_adder_truth_is_integer_addition(self):
        engine = self.load_engine()
        graph = engine.BooleanGraph()
        pins = {name: graph.variable(name) for name in ('A', 'B', 'CI')}
        outputs = [graph.function('((A^B)^CI)', pins),
                   graph.function('(((A B)+(B CI))+(CI A))', pins)]
        for a, b, carry in product(range(2), repeat=3):
            got = graph.evaluate(outputs, dict(A=a, B=b, CI=carry), mask=1)
            self.assertEqual(got, [(a + b + carry) % 2, (a + b + carry) // 2])

    def test_stall_cofactor_preserves_exact_previous_bit(self):
        engine = self.load_engine()
        graph = engine.BooleanGraph()
        pins = {name: graph.variable(name) for name in ('WRITE', 'DATA', 'OLD')}
        output = graph.function('((WRITE DATA) + ((!WRITE) OLD))', pins)
        held, = graph.substitute([output], {'WRITE': 0})
        written, = graph.substitute([output], {'WRITE': 1})
        self.assertEqual(held, pins['OLD'])
        self.assertEqual(written, pins['DATA'])
        self.assertEqual(graph.dependencies(held), frozenset(['OLD']))

    def test_inverting_multi_input_function(self):
        engine = self.load_engine()
        graph = engine.BooleanGraph()
        pins = {name: graph.variable(name) for name in ('A1', 'A2', 'B')}
        output = graph.function('(!((A1 A2)+B))', pins)
        for a, b, c in product(range(2), repeat=3):
            got, = graph.evaluate([output], dict(A1=a, A2=b, B=c), mask=1)
            self.assertEqual(got, int(not ((a and b) or c)))

    def test_packed_truth_vectors_are_not_scalar_boolean_values(self):
        engine = self.load_engine()
        graph = engine.BooleanGraph()
        pins = {name: graph.variable(name) for name in ('A', 'B')}
        outputs = [graph.function('A B', pins), graph.function('A^B', pins),
                   graph.function('!A', pins)]
        self.assertEqual(graph.evaluate(outputs, dict(A=0b1010, B=0b1100), mask=0b1111),
                         [0b1000, 0b0110, 0b0101])

    def test_unknown_syntax_and_unbound_pins_are_rejected(self):
        engine = self.load_engine()
        graph = engine.BooleanGraph()
        a = graph.variable('A')
        for expression in ('A ? 1 : 0', 'A;1', 'A @ 1', '(A', 'A)'):
            with self.assertRaises(ValueError):
                graph.function(expression, {'A': a})
        with self.assertRaises((ValueError, KeyError)):
            graph.function('A B', {'A': a})

    def test_signed_product_truth_vectors_cover_boundaries(self):
        engine = self.load_engine()
        tables = engine.product_truth_tables()
        self.assertEqual(len(tables), 16)
        for a, b, expected in [(0, 0, 0), (127, 127, 16129), (-128, -128, 16384),
                               (-128, 127, -16256), (-1, 127, -127), (-1, -1, 1),
                               (1, -128, -128), (0, -1, 0)]:
            index = ((a & 255) << 8) | (b & 255)
            bits = sum(((table >> index) & 1) << bit for bit, table in enumerate(tables))
            self.assertEqual(bits, expected & 65535)

    def test_unparsed_hardware_statements_are_rejected(self):
        engine = self.load_engine()
        good = b'module m (a,z); input a; output z; wire n;\n ND2 g (.A1(a),.A2(a),.ZN(z));\n endmodule'
        cells, declared = engine.structural_cells(good)
        self.assertEqual(len(cells), 1)
        self.assertIn('a', declared)
        for extra in [b'assign z=a;', b'wire q=a;', b'always @* z=a;', b'not q(z,a);']:
            with self.assertRaisesRegex(ValueError, 'Unsupported mapped module text'):
                engine.structural_cells(good.replace(b'endmodule', extra + b'endmodule'))
        self.assertEqual(len(engine.structural_cells(good.replace(b'wire n;', b'wire n; /* assign z=a; */'))[0]), 1)

    def test_header_and_module_end_bound_the_parsed_body(self):
        engine = self.load_engine()
        for body in [b'module m(input a); wire a; endmodule',
                     b'module m(a); input a; endmodule wire q;',
                     b'module m(a); input a; endmodule\n ND2 g(.A1(a));',
                     b'module m(a); wire a; endmodule']:
            with self.assertRaisesRegex(ValueError, 'Unsupported mapped module text'):
                engine.structural_cells(body)

    def test_escaped_scalar_cannot_impersonate_a_bus_bit(self):
        engine = self.load_engine()
        declared = {'operand_a': (7, 0), 'product[0].value': (15, 0)}
        normal = engine.bindings(b'.D(operand_a[0]),.Q(\\product[0].value [0])', declared)
        self.assertEqual(normal, {'D': 'operand_a[0]', 'Q': 'product[0].value[0]'})
        for spoof in [b'.D(\\operand_a[0] )', b'.Q(\\product[0].value[0] )', b'.D(operand_a[8])']:
            with self.assertRaises(ValueError):
                engine.bindings(spoof, declared)
        alias = b'module m(a); input [7:0] a; wire \\a[0] ; endmodule'
        with self.assertRaisesRegex(ValueError, 'Ambiguous declared net'):
            engine.structural_cells(alias)

    def test_product_flip_flop_semantics_are_checked(self):
        engine = self.load_engine()
        good = 'ff(IQ,IQN) {clocked_on : "CP"; next_state : "D";}'
        self.assertEqual(engine.product_flip_flop(good), {'clocked_on': 'CP', 'next_state': 'D'})
        for bad in [good.replace('"CP"', '"!CP"'), good.replace('"D"', '"!D"'),
                    good.replace('}', 'clear : "!CDN";}'), good + good]:
            with self.assertRaises(ValueError):
                engine.product_flip_flop(bad)


if __name__ == '__main__':
    unittest.main()
