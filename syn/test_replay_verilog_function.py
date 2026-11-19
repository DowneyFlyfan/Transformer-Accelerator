"""Catch hidden model changes and unsafe comment/specify normalization."""
import unittest
from replay_verilog_function import functional_models

class ModelTests(unittest.TestCase):
 def test_drive_variants_differ_only_in_disabled_specify(self):
  text='module SMALL(A,Z); input A; output Z; buf(Z,A); specify (A=>Z)=1; endspecify endmodule\nmodule LARGE(A,Z); input A; output Z; /* drive */ buf (Z,A); specify (A=>Z)=9; endspecify endmodule'
  models=functional_models(text,{'SMALL','LARGE'})
  self.assertEqual(models['SMALL'],models['LARGE'])
 def test_changed_primitive_is_not_normalized_away(self):
  text='module A(I,Z); input I; output Z; buf(Z,I); endmodule module B(I,Z); input I; output Z; not(Z,I); endmodule'
  models=functional_models(text,{'A','B'});self.assertNotEqual(models['A'],models['B'])
 def test_comment_markers_inside_strings_remain_significant(self):
  text='module A(I); input I; initial $display("// specify"); endmodule module B(I); input I; initial $display("/* specify"); endmodule'
  models=functional_models(text,{'A','B'});self.assertNotEqual(models['A'],models['B'])
 def test_escaped_specify_identifier_is_not_a_timing_block(self):
  text='module A(I,Z); input I; output Z; wire \\specify ; buf(Z,\\specify ); endmodule'
  tokens=functional_models(text,{'A'})['A'];self.assertIn('\\specify',tokens)
 def test_comments_cannot_merge_distinct_identifiers(self):
  text='module A(I,Z); input I; output Z; buf(Z,I); endmodule module B(I,Z); input I; output Z; b/**/uf(Z,I); endmodule'
  models=functional_models(text,{'A','B'});self.assertNotEqual(models['A'],models['B'])
 def test_unterminated_or_nested_timing_blocks_reject(self):
  for text in ('module A(I); input I; specify (I=>I)=1; endmodule','module A(I); input I; specify specify endspecify endspecify endmodule'):
   with self.subTest(text=text),self.assertRaisesRegex(AssertionError,'specify'):functional_models(text,{'A'})
 def test_duplicate_or_missing_model_rejects(self):
  for text,names in (('module A(I); input I; endmodule module A(I); input I; endmodule',{'A'}),('module B(I); input I; endmodule',{'A'})):
   with self.subTest(text=text),self.assertRaises(AssertionError):functional_models(text,names)
if __name__=='__main__':unittest.main()
