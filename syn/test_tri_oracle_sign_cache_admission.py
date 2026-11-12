import unittest

import numpy as np

from measure_tri_oracle_sign_cache_admission import admitted_misses, retained_miss_mask, ranked_miss_mask


class SignCacheAdmissionTest(unittest.TestCase):
    def test_bypassed_collision_does_not_evict_reused_line(self):
        words = np.array([0, 5, 0], dtype=np.uint64)
        admitted = np.array([True, False, True])
        self.assertEqual(admitted_misses(words, admitted, 4).tolist(), [0, 5])

    def test_all_admitted_uses_original_cache_order(self):
        words = np.array([0, 5, 0], dtype=np.uint64)
        self.assertEqual(admitted_misses(words, np.ones(3, dtype=bool), 4).tolist(), [0, 5, 0])

    def test_slot_prefers_more_reused_strip_and_bypasses_collision(self):
        frame = np.array([[True, True, False, False, True],
                          [True, False, False, False, True],
                          [False, False, False, False, True]])
        self.assertEqual(retained_miss_mask(frame, 4, False).tolist(),
                         [True, True, True, True, False, False])

    def test_remapping_reused_strips_avoids_fixed_slot_collisions(self):
        frame = np.array([[True, False, False, False, True],
                          [True, False, False, False, True]])
        self.assertEqual(ranked_miss_mask(frame, 2).tolist(), [True, True, False, False])


if __name__ == "__main__":
    unittest.main()
