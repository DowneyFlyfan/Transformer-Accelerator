"""Behavioral controls for current-candidate storage qualification."""
import importlib.util
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))


class NativeStorageTests(unittest.TestCase):
    def helper(self):
        spec = importlib.util.find_spec('tri_oracle_native_storage')
        self.assertIsNotNone(spec, 'Native storage census is not implemented')
        import tri_oracle_native_storage
        return tri_oracle_native_storage

    def test_repeated_modules_multiply_leaves_and_memory_paths(self):
        # Counting definitions instead of physical instances would yield one RAM.
        source = b'''module leaf();
 RAM mem (.A(1'b0));
 FF state_bit (.D(1'b0));
endmodule
module top();
 leaf a ();
 leaf b ();
endmodule
'''
        result = self.helper().census(source, 'top', {'RAM', 'FF'}, {'RAM'})
        self.assertEqual(result['leaves'], {'RAM': 2, 'FF': 2})
        self.assertEqual(result['memory'], {'a/mem': 'RAM', 'b/mem': 'RAM'})
        self.assertEqual(result['module_count'], 2)

    def test_unknown_leaf_is_rejected(self):
        helper = self.helper()
        with self.assertRaisesRegex(ValueError, 'Unknown leaf'):
            helper.census(b'module top();\n MYSTERY x ();\nendmodule\n', 'top', {'RAM'}, {'RAM'})

    def test_cycle_is_rejected(self):
        source = b'module top();\n child a ();\nendmodule\nmodule child();\n top b ();\nendmodule\n'
        helper = self.helper()
        with self.assertRaisesRegex(ValueError, 'cycle'):
            helper.census(source, 'top', set(), set())

    def test_uninstantiated_definition_is_reported_without_adding_its_storage(self):
        source = b'module top();\nendmodule\nmodule hidden();\n RAM x ();\nendmodule\n'
        helper = self.helper()
        failure = None
        try:
            result = helper.census(source, 'top', {'RAM'}, {'RAM'})
        except ValueError as error:
            failure = str(error)
        self.assertIsNone(failure, 'A legal unused module must not invalidate the actual hierarchy')
        self.assertEqual(result['leaves'], {})
        self.assertEqual(result['memory'], {})
        self.assertEqual(result['module_count'], 2)
        self.assertEqual(result['reachable_module_count'], 1)
        self.assertEqual(result['unreachable_modules'], ['hidden'])

    def test_unsupported_behavior_is_rejected(self):
        helper = self.helper()
        with self.assertRaises((ValueError, AssertionError)):
            helper.census(b'module top();\n reg state_bit;\n initial state_bit=0;\nendmodule\n', 'top', set(), set())

    def test_duplicate_instance_is_rejected(self):
        helper = self.helper()
        with self.assertRaises((ValueError, AssertionError)):
            helper.census(b'module top();\n RAM a ();\n RAM a ();\nendmodule\n', 'top', {'RAM'}, {'RAM'})

    def test_duplicate_module_is_rejected(self):
        helper = self.helper()
        with self.assertRaisesRegex(ValueError, 'Duplicate module'):
            helper.census(b'module top();\nendmodule\nmodule top();\nendmodule\n', 'top', set(), set())

    def test_outside_module_instance_is_rejected(self):
        helper = self.helper()
        with self.assertRaisesRegex(ValueError, 'Outside'):
            helper.census(b'RAM lost ();\nmodule top();\nendmodule\n', 'top', {'RAM'}, {'RAM'})

    def test_changed_memory_master_is_rejected(self):
        logical = {'leaves': {'RAM': 1}, 'memory': {'mem': 'RAM'}}
        helper = self.helper()
        with self.assertRaisesRegex(ValueError, 'memory'):
            helper.compare_physical(logical, {'RAM': 1}, {'mem': 'OTHER_RAM'})

    def test_missing_physical_support_bank_is_rejected(self):
        logical = {'leaves': {'RAM': 2}, 'memory': {'mem': 'RAM', 'support': 'RAM'}}
        helper = self.helper()
        with self.assertRaisesRegex(ValueError, 'memory'):
            helper.compare_physical(logical, {'RAM': 2}, {'mem': 'RAM'})

    def test_changed_standard_cell_count_is_rejected(self):
        logical = {'leaves': {'RAM': 1, 'FF': 8}, 'memory': {'mem': 'RAM'}}
        helper = self.helper()
        with self.assertRaisesRegex(ValueError, 'leaf'):
            helper.compare_physical(logical, {'RAM': 1, 'FF': 7}, {'mem': 'RAM'})

    def test_matching_physical_memory_and_all_leaf_counts_are_accepted(self):
        logical = {'leaves': {'RAM': 1, 'FF': 8}, 'memory': {'mem': 'RAM'}}
        self.helper().compare_physical(logical, {'RAM': 1, 'FF': 8}, {'mem': 'RAM'})

    def test_duplicate_named_pin_is_rejected(self):
        helper = self.helper()
        with self.assertRaises((ValueError, AssertionError)):
            helper.census(b"module top();\n RAM a (.A(1'b0), .A(1'b1));\nendmodule\n", 'top', {'RAM'}, {'RAM'})

    def test_escaped_alias_of_same_pin_is_rejected(self):
        helper = self.helper()
        with self.assertRaises((ValueError, AssertionError)):
            helper.census(b"module top();\n RAM a (.\\A (1'b0), .A(1'b1));\nendmodule\n", 'top', {'RAM'}, {'RAM'})

    def test_malformed_pin_list_is_rejected(self):
        helper = self.helper()
        with self.assertRaises((ValueError, AssertionError)):
            helper.census(b'module top();\n RAM a (this is not a pin association);\nendmodule\n', 'top', {'RAM'}, {'RAM'})

    def test_malformed_module_header_is_rejected(self):
        helper = self.helper()
        with self.assertRaises((ValueError, AssertionError)):
            helper.census(b'module top(parameter integer WIDTH=8)();\n RAM a ();\nendmodule\n', 'top', {'RAM'}, {'RAM'})

    def test_storage_hidden_in_unsupported_ansi_header_is_rejected(self):
        helper = self.helper()
        with self.assertRaises((ValueError, AssertionError)):
            helper.census(b"module top(output reg stored = 1'b0);\nendmodule\n", 'top', set(), set())

    def test_module_text_inside_leading_comment_is_ignored(self):
        helper = self.helper()
        source = b'/* example:\nmodule ignored();\nendmodule\n*/\nmodule top();\n RAM a ();\nendmodule\n'
        failure = None
        try:
            result = helper.census(source, 'top', {'RAM'}, {'RAM'})
        except ValueError as error:
            failure = str(error)
        self.assertIsNone(failure)
        self.assertEqual(result['module_count'], 1)
        self.assertEqual(result['memory'], {'a': 'RAM'})

    def test_endmodule_text_inside_body_comment_is_ignored(self):
        helper = self.helper()
        source = b'module top();\n/* example:\nendmodule\n*/\n RAM a ();\nendmodule\n'
        failure = None
        try:
            result = helper.census(source, 'top', {'RAM'}, {'RAM'})
        except (ValueError, AssertionError) as error:
            failure = str(error)
        self.assertIsNone(failure)
        self.assertEqual(result['memory'], {'a': 'RAM'})


if __name__ == '__main__':
    unittest.main()
