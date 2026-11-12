from fractions import Fraction
import unittest

from measure_tri_oracle_outlier_thresholds import outlier_limits


class OutlierLimitsTest(unittest.TestCase):
    def test_signed_gate_threshold_rounds_down(self):
        self.assertEqual(outlier_limits(11, -4, 8), (-2, 2))

    def test_integer_comparisons_match_fractional_cutoffs(self):
        for count in (1, 11, 32, 2048):
            for gate, up in ((-8, 2), (0, 0), (4, 12), (32, 32)):
                limits = outlier_limits(count, gate, up)
                for limit, threshold in zip(limits, (gate, up), strict=True):
                    self.assertIs(type(limit), int)
                    for margin in (limit - 1, limit, limit + 1):
                        self.assertEqual(margin <= limit, Fraction(margin, count) <= Fraction(threshold, 32))


if __name__ == "__main__":
    unittest.main()
