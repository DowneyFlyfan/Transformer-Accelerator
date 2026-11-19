import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()/"syn"))
from replay_resize_liberty import resize_direct_groups,resize_group
class ContinuationTests(unittest.TestCase):
 def test_multiline_table_string_preserves_exact_cell_body(self):
  raw='pin (Z) { direction : output; function : "I"; timing () { values ("0.1, '+chr(92)+'\n0.2"); } }'
  self.assertEqual(resize_direct_groups('cell (B) { '+raw+' }'),[('cell','B',' '+raw+' ')])
 def test_multiline_logic_string_is_not_rewritten(self):
  raw=' next_state : "D & '+chr(92)+'\nE"; clocked_on : "CP"; '
  self.assertEqual(resize_direct_groups('ff (IQ, IQN) {'+raw+'}'),[('ff','IQ, IQN',raw)])
 def test_unclosed_multiline_quote_is_rejected(self):
  with self.assertRaisesRegex(AssertionError,'Unclosed Liberty quoted string'):
   resize_direct_groups('pin (Q) { function : "A '+chr(92)+'\n B; }')
 def test_group_extraction_ignores_braces_inside_continued_string(self):
  raw=' pin (Q) { function : "A '+chr(92)+'\n } B"; } '
  text='cell (X) {'+raw+'} pin (EXTRA) {}'
  self.assertEqual(resize_group(text,text.index('{')+1),raw)
if __name__=='__main__':unittest.main()
