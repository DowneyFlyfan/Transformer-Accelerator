"""Ensure named upstream roots stay checked after their fanout drops."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from tri_oracle_explicit_pin_tables import measured_table


class PinTableTests(unittest.TestCase):
    def read(self,row,explicit):
        with TemporaryDirectory(dir=Path(__file__).parent,prefix='pin_fixture_') as tmp:
            path=Path(tmp)/'data.tsv'
            path.write_text('net\tdriver\tloads\tpin_load_pf\tlimit_pf\tmissing_sink_caps\n'+row+'\n')
            return measured_table(path,explicit)

    def test_original_root_with_four_buffer_inputs_is_still_checked(self):
        try:
            data=self.read('root\tdriver/Z\t4\t0.01\t1.0\t0',{'root':4})
        except AssertionError:
            self.fail('Explicit repaired root disappeared when its fanout fell below64')
        self.assertEqual(data['root']['loads'],4)

    def test_unknown_low_fanout_net_is_rejected(self):
        with self.assertRaises(AssertionError):
            self.read('other\tdriver/Z\t4\t0.01\t1.0\t0',{})

    def test_required_root_cannot_be_omitted(self):
        with self.assertRaises(AssertionError):
            self.read('other\tdriver/Z\t64\t0.01\t1.0\t0',{'root':4})

    def test_required_root_count_must_match_even_above_threshold(self):
        with self.assertRaises(AssertionError):
            self.read('root\tdriver/Z\t64\t0.01\t1.0\t0',{'root':4})

    def test_normal_high_fanout_net_remains_eligible(self):
        self.assertEqual(self.read('ordinary\tdriver/Z\t128\t0.01\t1.0\t0',{})['ordinary']['loads'],128)

    def test_duplicate_net_is_rejected(self):
        with self.assertRaises(AssertionError):
            self.read('ordinary\tdriver/Z\t128\t0.01\t1.0\t0\nordinary\tdriver/Z\t128\t0.01\t1.0\t0',{})


if __name__=='__main__':
    unittest.main()
