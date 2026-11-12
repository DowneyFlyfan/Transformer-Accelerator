import unittest

from audit_tri_oracle_linked_response_placement import matched_delta


class MatchedDeltaTest(unittest.TestCase):
    def test_matched_clocks_allow_a_slack_comparison(self):
        self.assertAlmostEqual(matched_delta(
            [{"period_ns": 1.72414, "slack_ns": -45.748207}],
            [{"period_ns": 1.72414, "slack_ns": -10.2}],
        ), 35.548207)

    def test_changed_clock_cannot_be_reported_as_a_timing_improvement(self):
        with self.assertRaisesRegex(ValueError, "clock period"):
            matched_delta([{"period_ns": 1.72414, "slack_ns": -45.748207}],
                          [{"period_ns": 2.0, "slack_ns": -10.2}])


if __name__ == "__main__":
    unittest.main()
