import unittest,json,copy
from pathlib import Path
from replay_clock_gate_contract import validate_ckln_model
class ClockGateTests(unittest.TestCase):
 def model(self):
  p=Path('.cache/wide_packaged_host_link/owner_score_proof/replay_nonarray_resize_group_fixed_comparison.json')
  return copy.deepcopy(json.loads(p.read_text())['three_corner_functional_views']['tt1v25c']['CKLNQD1BWP12T40P140'])
 def test_real_library_clock_gate_has_the_required_low_phase_latch(self):
  self.assertTrue(validate_ckln_model(self.model()))
 def test_changed_output_clock_function_is_rejected(self):
  m=self.model();m['pins']['Q']['state_function']='"!CP*QD"';self.assertFalse(validate_ckln_model(m))
 def test_wrong_low_phase_enable_row_is_rejected(self):
  m=self.model();m['states'][0][2]['table']=m['states'][0][2]['table'].replace('L   L   H :  -  : H','L   L   H :  -  : L');self.assertFalse(validate_ckln_model(m))
 def test_high_phase_input_sampling_is_rejected(self):
  m=self.model();m['states'][0][2]['table']=m['states'][0][2]['table'].replace('H   -   - :  -  : N','H   -   - :  -  : L');self.assertFalse(validate_ckln_model(m))
if __name__=='__main__':unittest.main()
