"""Require an exact, disconnected, non-preserved wrapper input set for cleanup."""
from copy import deepcopy
import unittest
from tri_oracle_dead_wrapper206 import validate_dead_wrapper_pins


class DeadWrapperTests(unittest.TestCase):
    def setUp(self):
        self.rows=[]
        for name in ['wrapper/a','wrapper/b']:
            row=dict(pin=name,direction='in')
            for side in ['outer','inner']:
                row[side+'_net']='';row[side+'_constant']=''
                for field in ['leaf_loads','top_loads','leaf_drivers','top_drivers']:row[side+'_'+field]='0'
            self.rows.append(row)
        self.reported={'wrapper/a','wrapper/b'}

    def test_exact_disconnected_inputs_accepted(self):
        self.assertEqual(validate_dead_wrapper_pins(self.rows,self.reported,{'protected/x'},expected_count=2),self.reported)

    def test_live_renamed_duplicate_missing_and_protected_pins_rejected(self):
        for mutation in ['outer_net','inner_net','outer_leaf_loads','inner_top_loads','outer_leaf_drivers','inner_top_drivers','direction','rename','duplicate','missing','protected']:
            with self.subTest(mutation=mutation):
                rows=deepcopy(self.rows);preserved={'protected/x'}
                if mutation.endswith('_net'):rows[0][mutation]='live_net'
                elif mutation in ['outer_leaf_loads','inner_top_loads','outer_leaf_drivers','inner_top_drivers']:rows[0][mutation]='1'
                elif mutation=='direction':rows[0]['direction']='out'
                elif mutation=='rename':rows[0]['pin']='other/a'
                elif mutation=='duplicate':rows[1]=deepcopy(rows[0])
                elif mutation=='missing':rows.pop()
                else:preserved.add('wrapper/a')
                with self.assertRaises((ValueError,AssertionError)):validate_dead_wrapper_pins(rows,self.reported,preserved,expected_count=2)


if __name__=='__main__':unittest.main()
