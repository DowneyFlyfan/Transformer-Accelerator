import importlib.util
from io import StringIO
from pathlib import Path
import unittest

import tri_oracle_streaming_netlist_inventory as m
MEMORY='ts5n28hpcpsvta32x128m2fw_130a'

class InventoryContract(unittest.TestCase):
    def setUp(self):
        self.m=m

    def run_case(self,text):
        return self.m.inspect(lambda:StringIO(text),'top',{'BUF'})

    def test_unreachable_memory_is_excluded(self):
        r=self.run_case('module top(a);\n BUF u (.I(a));\nendmodule\nmodule unused(a);\n '+MEMORY+' mem (.A(a));\nendmodule\n')
        self.assertEqual(r['memory_macro_count'],0)
        self.assertEqual(r['leaf_instances'],{'BUF':1})

    def test_shared_module_has_distinct_owned_memories(self):
        r=self.run_case('module top(a);\n tile left (.a(a));\n tile right (.a(a));\nendmodule\nmodule tile(a);\n '+MEMORY+' bank (.A(a));\nendmodule\n')
        self.assertEqual(r['memory_macro_count'],2)
        self.assertEqual(r['compiled_memory_bytes'],1024)
        self.assertEqual([p['path'] for p in r['memories']],['left/bank','right/bank'])

    def test_escaped_instance_is_preserved(self):
        r=self.run_case('module top(a);\n '+MEMORY+' \\cores[0].bank (.A(a));\nendmodule\n')
        self.assertEqual(r['memories'][0]['path'],'cores[0].bank')

    def test_uppercase_memory_master(self):
        r=self.run_case('module top(a);\n TS6N28HPCPSVTA16X128M2F bank (.A(a));\nendmodule\n')
        self.assertEqual(r['compiled_memory_bytes'],256)

    def test_duplicate_instance_is_rejected(self):
        with self.assertRaises(ValueError):
            self.run_case('module top(a);\n BUF same (.I(a));\n BUF same (.I(a));\nendmodule\n')

    def test_missing_module_is_rejected(self):
        with self.assertRaises(ValueError):
            self.run_case('module top(a);\n tri_oracle_missing u (.a(a));\nendmodule\n')

    def test_recursive_hierarchy_is_rejected(self):
        with self.assertRaises(ValueError):
            self.run_case('module top(a);\n tile u (.a(a));\nendmodule\nmodule tile(a);\n top loop (.a(a));\nendmodule\n')

    def test_duplicate_module_is_rejected(self):
        with self.assertRaises(ValueError):
            self.run_case('module top(a);\nendmodule\nmodule top(a);\nendmodule\n')

    def test_unterminated_module_is_rejected(self):
        with self.assertRaises(ValueError): self.run_case('module top(a);\n BUF u (.I(a));\n')

    def test_layout_master_counts(self):
        r=self.m.placement_histogram(StringIO('REGIONS 1 ;\n- region0 ( 0 0 ) ( 1 1 ) ;\nEND REGIONS\nCOMPONENTS 2 ;\n- alpha BUF\n + PLACED ( 0 0 ) N ;\n- beta '+MEMORY+'\n + FIXED ( 1 1 ) N ;\nEND COMPONENTS\n'))
        self.assertEqual(r,{'BUF':1,MEMORY:1})

    def test_truncated_layout_is_rejected(self):
        with self.assertRaises(ValueError): self.m.placement_histogram(StringIO('COMPONENTS 1 ;\n- a BUF\n'))

    def test_incomplete_layout_count_is_rejected(self):
        with self.assertRaises(ValueError): self.m.placement_histogram(StringIO('COMPONENTS 2 ;\n- a BUF\nEND COMPONENTS\n'))

    def test_multiple_layout_sections_are_rejected(self):
        with self.assertRaises(ValueError): self.m.placement_histogram(StringIO('COMPONENTS 1 ;\n- a BUF\nEND COMPONENTS\nCOMPONENTS 1 ;\n- b BUF\nEND COMPONENTS\n'))




def census(text):return m.inspect(lambda:StringIO(text),'top',{'BUFFD1','DFCNQD1'})

class InstanceFormatting(unittest.TestCase):
    def test_genus_no_space_and_innovus_space_both_count(self):
        text='module top(a,z);\n BUFFD1 g0(.I(a),.Z(b));\n BUFFD1 g1 (.I(b),.Z(z));\nendmodule\n'
        self.assertEqual(census(text)['leaf_instances'],{'BUFFD1':2})
    def test_repeated_hierarchy_counts_each_physical_child(self):
        text='module child(a,z);\n BUFFD1 g0(.I(a),.Z(z));\nendmodule\nmodule top(a,z);\n child c0(.a(a),.z(b));\n child c1 (.a(b),.z(z));\nendmodule\n'
        self.assertEqual(census(text)['leaf_instances'],{'BUFFD1':2})
    def test_master_on_previous_line(self):
        self.assertEqual(census('module top(a,z);\n BUFFD1\n g0(.I(a),.Z(z));\nendmodule\n')['leaf_instances'],{'BUFFD1':1})
    def test_escaped_instance_open_paren_on_next_line(self):
        self.assertEqual(census('module top(a,z);\n BUFFD1 \\g[0]\n (.I(a),.Z(z));\nendmodule\n')['leaf_instances'],{'BUFFD1':1})
    def test_master_instance_and_paren_on_separate_lines(self):
        self.assertEqual(census('module top(a,z);\n BUFFD1\n \\g[0]\n (.I(a),.Z(z));\nendmodule\n')['leaf_instances'],{'BUFFD1':1})
    def test_wrapped_unknown_master_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'Unknown reachable'):
            census('module top(a,z);\n MISSING\n g0(.I(a),.Z(z));\nendmodule\n')
    def test_wrapped_duplicate_instance_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'Duplicate instance'):
            census('module top(a,z);\n BUFFD1\n g0(.I(a),.Z(z));\n BUFFD1 g0\n (.I(a),.Z(z));\nendmodule\n')
    def test_wrapped_pin_continuations_are_not_instances(self):
        text='module top(a,z);\n DFCNQD1 \\q_reg[0] (.D\n       (a), .Q (z));\nendmodule\n'
        self.assertEqual(census(text)['leaf_instances'],{'DFCNQD1':1})
    def test_unknown_compact_instance_must_be_rejected(self):
        with self.assertRaisesRegex(ValueError,'Unknown reachable'):
            census('module top(a,z);\n MISSING g0(.I(a),.Z(z));\nendmodule\n')
    def test_duplicate_compact_instances_must_be_rejected(self):
        with self.assertRaisesRegex(ValueError,'Duplicate instance'):
            census('module top(a,z);\n BUFFD1 g0(.I(a),.Z(z));\n BUFFD1 g0(.I(a),.Z(z));\nendmodule\n')

if __name__=='__main__':unittest.main()
