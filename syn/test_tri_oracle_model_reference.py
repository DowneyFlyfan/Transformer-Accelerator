"""Integer contract: ties, signed saturation, SiLU tails and interpolation.
A lost sign or truncation in the golden reference must fail these literals.
"""
import unittest
from tri_oracle_model_reference import requantize, silu_code, select_up_shift, rms_prediction_codes, classify_prediction

class IntegerContract(unittest.TestCase):
    def test_signed_ties_and_saturation(self):
        for value, shift, bits, expected in [(3,1,8,2),(-3,1,8,-2),(1,1,8,1),(-1,1,8,-1),(256,0,8,127),(-256,0,8,-128),(32768,0,16,32767),(-32769,0,16,-32768),(127,63,8,0)]:
            with self.subTest(value=value,shift=shift):
                self.assertEqual(requantize(value,shift,bits),expected)
    def test_linear_up_precision_preserves_range(self):
        for magnitude, original, expected in [(0,7,0),(32767,7,0),(32768,7,1),(65534,7,1),(65535,7,2),(1000000,3,3)]:
            with self.subTest(magnitude=magnitude):
                self.assertEqual(select_up_shift(magnitude,original),expected)
    def test_prediction_uses_root_mean_square_without_centering(self):
        self.assertEqual(rms_prediction_codes([-3,0,4,0],0),[-307,0,410,0])
        self.assertEqual(rms_prediction_codes([0]*8,1e-5),[0]*8)
    def test_pre_weight_outlier_is_retained(self):
        codes=rms_prediction_codes([10]+[1]*15,0)
        self.assertEqual(codes,[955]+[95]*15)
        self.assertEqual([i for i,v in enumerate(codes) if abs(v)>768],[0])
    def test_paper_gate_is_one_sided_and_up_is_interval(self):
        self.assertEqual(classify_prediction([-8,8,0,-8],[0,0,0,-8],8),([True,False,True,True],[True,True,True,False],[True,False,True,False]))
        self.assertEqual(classify_prediction([-8,8,0,-8],[0,0,0,-8],8,gate_threshold=-4)[2],[True,False,False,False])
        self.assertEqual(classify_prediction([0],[0],0),([False],[False],[False]))
    def test_silu_samples_and_tails(self):
        for value, expected in [(-32768,0),(-2048,0),(-256,-69),(0,0),(256,187),(2048,2048),(32767,32767)]:
            with self.subTest(value=value):
                self.assertEqual(silu_code(value),expected)

if __name__=="__main__":unittest.main()
