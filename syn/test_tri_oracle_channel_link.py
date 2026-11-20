from pathlib import Path
import subprocess,sys,unittest

import link_tri_oracle_channel_scale as m

class Closure(unittest.TestCase):
    def test_preserved_and_library_masters(self):
        text='module parent(a);\n child core (.a(a));\n BUFFD1 clock_buf (.I(a),.Z(b));\nendmodule'
        self.assertEqual(len(m.verify_reference_closure(text,{'child','BUFFD1'})),2)
    def test_missing_internal_child_is_rejected(self):
        with self.assertRaises(ValueError):
            m.verify_reference_closure('module parent(a);\n missing child (.a(a));\nendmodule',{'known'})
    def test_missing_standard_cell_is_rejected(self):
        with self.assertRaises(ValueError):
            m.verify_reference_closure('module parent(a);\n BUFFD99 g1 (.I(a));\nendmodule',{'BUFFD1'})
    def test_escaped_instance_cannot_hide_unknown_master(self):
        with self.assertRaises(ValueError):
            m.verify_reference_closure('module parent(a);\n missing \\lane[3].unit (.a(a));\nendmodule',{'known'})
    def test_renamed_child_must_resolve(self):
        text='module parent(a);\n tri_oracle_chscale_v1_child u (.a(a));\nendmodule'
        self.assertEqual(len(m.verify_reference_closure(text,{'tri_oracle_chscale_v1_child'})),1)
        with self.assertRaises(ValueError):m.verify_reference_closure(text,{'child'})
    def test_declarations_are_not_masters(self):
        self.assertEqual(m.verify_reference_closure('module parent(a);\n input a;\n wire b;\n assign b=a;\nendmodule',set()),[])

class EntryGuards(unittest.TestCase):
    def test_optimized_entrypoint_rejects_before_io(self):
        result=subprocess.run([sys.executable,'-O',m.__file__,'--help'],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('assertions',result.stderr)
    def test_existing_candidate_is_never_overwritten(self):
        with self.assertRaisesRegex(AssertionError,'overwrite'):m.main(m.WORK/'linked_v1')
    def test_generated_candidate_must_stay_in_cache(self):
        with self.assertRaisesRegex(AssertionError,'cache'):m.main(m.ROOT/'not_a_generated_output')

if __name__=='__main__':unittest.main()
