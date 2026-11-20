import math,unittest

import verify_tri_oracle_channel_scale_domain as m

class ScaleDomain(unittest.TestCase):
    def test_exact_quantizer_boundary(self):
        self.assertEqual(m.exponent_for_maximum(127.0),0)
        self.assertEqual(m.exponent_for_maximum(math.nextafter(127.0,math.inf)),1)
        self.assertEqual(m.exponent_for_maximum(128.0),1)
        self.assertEqual(m.exponent_for_maximum(0),0)
    def test_current_archived_token_scales(self):
        row=m.case(-8,-8,[-11,-7],-6,0,-6)
        self.assertTrue(row['representable'])
        self.assertEqual((row['gain'],row['down_shift'],row['base_shift'],row['lane_shifts']),(0,0,11,[7,11]))
    def test_negative_gain_is_not_clamped_to_zero(self):
        row=m.case(-8,-8,[-7],0,-8,9)
        self.assertEqual((row['gain'],row['up_shift'],row['down_shift'],row['base_shift']),(-8,8,1,20))
    def test_reference_invalid_shift_is_not_hardware_success(self):
        self.assertIsNone(m.case(-8,-8,[-7],-63,-8,9))
    def test_unencodable_base_and_decrement_are_rejected(self):
        self.assertFalse(m.case(-8,-8,[20],-6,0,-6)['representable'])
        self.assertFalse(m.case(-8,-8,[-15,-7],-6,0,-6)['representable'])
    def test_lane_underflow_is_rejected_with_valid_base(self):
        row=m.case(-8,-8,[-20,-17],-6,0,-6)
        self.assertEqual(row['base_shift'],1)
        self.assertEqual(row['lane_shifts'],[-2,1])
        self.assertFalse(row['representable'])

if __name__=='__main__':unittest.main()
