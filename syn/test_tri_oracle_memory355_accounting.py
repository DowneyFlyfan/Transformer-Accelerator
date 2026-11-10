"""Literal storage-size controls; never infer capacity from a part-number name."""
import importlib.util
from pathlib import Path
import unittest


class MemoryTests(unittest.TestCase):
    def setUp(self):
        path=Path('syn/audit_tri_oracle_memory355_accounting.py')
        self.assertTrue(path.exists(),'Candidate-bound memory accounting is missing')
        spec=importlib.util.spec_from_file_location('memory355',path)
        self.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.module)

    def test_single_port_uses_actual_word_and_bit_parameters(self):
        source='module TEST; parameter numWord=32; parameter numBit=128; endmodule'
        self.assertEqual(self.module.capacity_bytes(source,'TEST'),512)

    def test_two_port_ignores_nested_generic_default_dimensions(self):
        source=('module TEST; parameter W=16; parameter N=128; endmodule\n'
                'module TEST_Int_Array; parameter Nword=2; parameter Ndata=1; endmodule')
        self.assertEqual(self.module.capacity_bytes(source,'TEST'),256)

    def test_missing_ambiguous_or_partial_byte_geometry_is_rejected(self):
        for source in ['module TEST; endmodule','module TEST; parameter W=3; parameter N=7; endmodule',
                       'module TEST; parameter W=16; parameter N=128; endmodule '*2]:
            with self.subTest(source=source),self.assertRaises(ValueError):self.module.capacity_bytes(source,'TEST')

    def test_native_duplicate_instance_cannot_double_count_storage(self):
        rows=[dict(instance='core0/weight0',master='TS5N28A'),dict(instance='agg0/slot0',master='TS6N28B')]
        self.assertEqual(self.module.memory_counts(rows),{'TS5N28A':1,'TS6N28B':1})
        with self.assertRaises(ValueError):self.module.memory_counts([*rows,rows[0]])


if __name__=='__main__':unittest.main()
