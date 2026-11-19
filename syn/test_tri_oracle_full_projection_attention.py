from pathlib import Path
import importlib.util,unittest

class FullProjectionAttentionCorrectionTest(unittest.TestCase):
 def renderer(self):
  path=Path(__file__).with_name('prepare_tri_oracle_full_projection_attention.py')
  self.assertTrue(path.is_file(),'The full-projection decode correction is not implemented')
  spec=importlib.util.spec_from_file_location('full_projection_attention_correction',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module.render_full_projection_bench
 def test_only_decode_key_count_changes_in_the_full_projection_flow(self):
  source="projected_cache[index] = captured_write;\ncommand(5, tag, 3, 576'({key_base, query_base, 7'(shift), 11'd408, 11'(position), 5'(head)}));\ncheck_all_projection_batches();\n"
  wanted="projected_cache[index] = captured_write;\ncommand(5, tag, 3, 576'({key_base, query_base, 7'(shift), 11'(rank == Slots - 1 ? Slots : Slots - 1), 11'(position), 5'(head)}));\ncheck_all_projection_batches();\n"
  self.assertEqual(self.renderer()(source),wanted)
 def test_missing_row_command_is_rejected(self):
  with self.assertRaisesRegex(ValueError,'one uncorrected row descriptor'):
   self.renderer()('command(4, tag, 3, descriptor);')
 def test_ambiguous_row_commands_are_rejected(self):
  row="7'(shift), 11'd408, 11'(position), 5'(head)"
  with self.assertRaisesRegex(ValueError,'one uncorrected row descriptor'):
   self.renderer()(row+'\n'+row)

if __name__=='__main__':unittest.main(verbosity=2)
