"""Small physical counterexamples for fragmented space and hard boundaries."""
import itertools
import unittest
import numpy as np
from tri_oracle_row_pack import pack_row


class PackRowTests(unittest.TestCase):
    def test_fragmented_free_sites_can_accept_whole_buffer(self):
        # Two isolated free sites cannot hold a two-site buffer without motion.
        actual = pack_row([2,2,2], [0,2,3], [0,2,2], [1,2,4])
        np.testing.assert_array_equal(actual, [0,2,4])

    def test_fixed_boundary_cell_is_not_moved_to_hide_overflow(self):
        with self.assertRaises(ValueError):
            pack_row([2,2,2], [0,2,3], [0,2,3], [0,2,3])

    def test_total_width_exceeding_row_is_rejected(self):
        with self.assertRaises(ValueError):
            pack_row([4,4], [0,4], [0,0], [3,3])

    def test_already_legal_positions_are_preserved(self):
        np.testing.assert_array_equal(pack_row([2,1], [1,5], [0,0], [4,6]), [1,5])

    def test_small_feasibility_matches_exhaustive_integer_placements(self):
        for widths in ([1,2,1],[2,2,2],[3,1,2]):
            for lower in ([0,1,2],[1,2,3],[0,0,0]):
                for upper in ([2,3,4],[1,2,3],[0,1,2]):
                    feasible = any(all(x[i]+widths[i]<=x[i+1] for i in range(2))
                                   for x in itertools.product(*(range(a,b+1) for a,b in zip(lower,upper))))
                    if not feasible:
                        with self.assertRaises(ValueError):
                            pack_row(widths,[0,2,4],lower,upper)
                    else:
                        x = pack_row(widths,[0,2,4],lower,upper)
                        self.assertTrue(all(a<=v<=b for a,v,b in zip(lower,x,upper)))
                        self.assertTrue(all(x[i]+widths[i]<=x[i+1] for i in range(2)))


if __name__=='__main__':
    unittest.main()
