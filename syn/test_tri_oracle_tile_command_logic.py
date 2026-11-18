"""Literal fixtures catch key-region,160-bit token stride and prefix errors."""
from pathlib import Path
import sys
import unittest
import z3
sys.path.insert(0,str(Path(__file__).resolve().parent))
from prove_tri_oracle_tile_command import key_for_column,reference_keep,reference_channel,decode_keep_index,initialized_column

class CommandLogicTest(unittest.TestCase):
    def test_three_disjoint_key_regions(self):
        query=z3.BitVecVal(112,13)
        for column,wanted in [(0,0),(31,31),(32,32),(63,63),(64,96),(95,127)]:
            self.assertEqual(z3.simplify(key_for_column(query,column)).as_long(),wanted)

    def test_partial_recent_keys_are_omitted(self):
        query=z3.BitVecVal(96,13);count=z3.BitVecVal(1,5)
        for column,wanted in [(0,0),(31,31),(32,32),(63,63),(64,96),(65,0),(95,0),(96,0),(159,0)]:
            self.assertEqual(z3.simplify(reference_channel(query,count,column)).as_long(),wanted)

    def test_keep_uses_actual_query_and_active_token(self):
        for query,count,row,column,wanted in [(96,1,0,64,True),(96,1,0,65,False),
                (96,1,1,0,False),(112,16,15,95,True),(112,15,15,0,False),(96,1,0,96,False)]:
            actual=reference_keep(z3.BitVecVal(query,13),z3.BitVecVal(count,5),row,column)
            self.assertEqual(z3.is_true(z3.simplify(actual)),wanted)

    def test_keep_storage_uses160_columns_per_token(self):
        for index,wanted in [(0,(0,0)),(127,(0,127)),(159,(0,159)),(160,(1,0)),(2527,(15,127)),(2559,(15,159))]:
            self.assertEqual(decode_keep_index(index),wanted)

    def test_initialization_prefix_before_and_after_last_write(self):
        for state,key,column,wanted in [(0,0,0,False),(1,12,11,True),(1,12,12,False),
                (1,95,95,False),(2,95,95,True),(4,95,95,True),(0,0,96,True)]:
            actual=initialized_column(z3.BitVecVal(state,3),z3.BitVecVal(key,7),column)
            self.assertEqual(z3.is_true(z3.simplify(actual)),wanted)

if __name__=='__main__':unittest.main()
