"""Protect the real mapped controller when adding its physical macro declaration."""
import unittest

from tri_oracle_parent_import import native_parent_netlist


PARENT = ('// Preserve this mapped logic and spacing.\n'
          'module tri_oracle_predicted_fabric(input wire clk);\n'
          '  tri_oracle_sram_memory_compute core0(.clk(clk));\n'
          'endmodule\n')
CORE = ('module tri_oracle_sram_memory_compute(input wire clk);\n'
        'endmodule\n')
WRAPPER = 'module unrelated; endmodule\n' + CORE


class NativeParentImportTest(unittest.TestCase):
    def test_missing_macro_declaration_is_added_without_changing_mapped_logic(self):
        result = native_parent_netlist(PARENT, WRAPPER)
        self.assertTrue(result.startswith(PARENT))
        self.assertEqual(result[len(PARENT):], CORE)

    def test_existing_macro_definition_is_preserved_exactly(self):
        original = PARENT + '\n' + CORE
        self.assertEqual(native_parent_netlist(original, WRAPPER), original)

    def test_missing_or_ambiguous_canonical_interface_is_rejected(self):
        for interface in ['module unrelated; endmodule\n', CORE + CORE]:
            with self.subTest(interface=interface), self.assertRaises(ValueError):
                native_parent_netlist(PARENT, interface)

    def test_unterminated_interface_cannot_consume_another_module(self):
        broken = ('module tri_oracle_sram_memory_compute(input wire clk);\n'
                  'module unrelated;\nendmodule\n')
        with self.assertRaises(ValueError):
            native_parent_netlist(PARENT, broken)

    def test_wrong_parent_is_rejected_before_writing_a_physical_input(self):
        with self.assertRaises(ValueError):
            native_parent_netlist('module wrong_parent;\nendmodule\n', WRAPPER)


if __name__ == '__main__':
    unittest.main()
