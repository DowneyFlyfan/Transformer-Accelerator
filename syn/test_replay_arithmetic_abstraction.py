"""Catch sign, carry, old/new-state phase and final-result hold mistakes."""
import unittest,z3
from replay_arithmetic_abstraction import collapse_old,collapse_new,old_row_step,compress3,compress4

def bv(n,w=19):return z3.BitVecVal(n,w)
def values(words):return [z3.simplify(word).as_long() for word in words]

class AbstractionTests(unittest.TestCase):
 def test_negative_products_preserve_signed_nineteen_bit_total(self):
  old=dict(products=[bv(-2,16),bv(-3,16)]+[bv(0,16)]*6,first=[bv(0)]*4,second=[bv(0)]*2,final=bv(0))
  self.assertEqual(values(collapse_old(old)),[524283,0,0,0])
 def test_new_tree_partial_words_extend_their_actual_signed_width(self):
  words=[[bv(-1,16),bv(-2,16)]+[bv(0,16)]*6,[bv(-3,17),bv(4,17),bv(-5,17),bv(6,17)],[bv(-7,18),bv(8,18)],[bv(9,19)]]
  self.assertEqual(values(collapse_new(words)),[524285,2,1,9])
 def test_every_stage_uses_preedge_previous_stage(self):
  old=dict(products=[bv(n,16) for n in range(1,9)],first=[bv(1),bv(2),bv(4),bv(8)],second=[bv(10),bv(20)],final=bv(13))
  following=old_row_step(old,[bv(2,16)]*8,z3.BoolVal(False))
  self.assertEqual(values(collapse_old(following)),[16,36,15,30])
  self.assertEqual(values(collapse_old(old)),[36,15,30,13])
 def test_full_result_hold_preserves_only_the_final_data_stage(self):
  old=dict(products=[bv(1,16)]*8,first=[bv(0)]*4,second=[bv(10),bv(20)],final=bv(13))
  following=old_row_step(old,[bv(2,16)]*8,z3.BoolVal(True))
  self.assertEqual(values(collapse_old(following)),[16,8,0,13])
 def test_compressor_carry_has_the_correct_weight_and_wrap(self):
  self.assertEqual(values(compress3(bv(3),bv(5),bv(6))),[0,14])
  s,c=compress4(bv(3),bv(5),bv(6),bv(-1))
  self.assertEqual(values([s+c]),[13])
if __name__=='__main__':unittest.main()
