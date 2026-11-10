"""Independent controls for choosing informative trained hardware slices.

Catch original-group renumbering, signed cancellation in coverage ranking,
off-by-one output windows, and silently accepting all-zero test vectors.
"""
import importlib.util
from pathlib import Path
import unittest

import torch


class CoverageTests(unittest.TestCase):
    def setUp(self):
        path = Path('syn/prepare_tri_oracle_format350_fixtures.py')
        self.assertTrue(path.is_file(), 'Protected-format fixture preparation is missing')
        spec = importlib.util.spec_from_file_location('format350', path)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def test_original_channel_groups_and_last_legal_window(self):
        """Hand-derived partials are8 at output1 and15 at output7.
        inputs[D=96], weights[O=8,D=96] start zero on CPU; groups contain32
        channels. Strongest3-output window starts5, retaining original groups1/2.
        """
        inputs = torch.zeros(96, dtype=torch.int8)
        weights = torch.zeros((8, 96), dtype=torch.int8)
        inputs[32] = -2
        inputs[64] = 3
        weights[1, 32] = -4
        weights[7, 64] = 5
        self.assertEqual(self.module.select_coverage(inputs, weights, output_count=3), ([1, 2], 5))

    def test_group_importance_does_not_cancel_opposite_signed_weights(self):
        """inputs[96] ones; weights[4,96] zero except equal opposite output
        weights in group2 and weaker group1. Signed-sum ranking would lose group2.
        """
        inputs = torch.ones(96, dtype=torch.int8)
        weights = torch.zeros((4, 96), dtype=torch.int8)
        weights[0, 64] = 7
        weights[1, 64] = -7
        weights[2, 32] = 1
        self.assertEqual(self.module.select_coverage(inputs, weights, output_count=2), ([1, 2], 0))

    def test_zero_information_and_invalid_geometry_fail_closed(self):
        """CPU inputs[96]/weights[4,96] are zero; no informative slice exists.
        Missing group alignment and oversized output windows must also reject.
        """
        inputs = torch.zeros(96, dtype=torch.int8)
        weights = torch.zeros((4, 96), dtype=torch.int8)
        for left, right, count in [(inputs, weights, 2), (inputs[:95], weights[:, :95], 2),
                                   (inputs, weights, 5)]:
            with self.subTest(shape=tuple(left.shape), count=count), self.assertRaises(ValueError):
                self.module.select_coverage(left, right, output_count=count)


if __name__ == '__main__':
    unittest.main()
