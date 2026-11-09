"""Catch overlapping assignments, wrong rows/orientations and unsafe grids."""
import unittest

try:
    from tri_oracle_endpoint_slots import assign_slots, verify_slots
except ModuleNotFoundError:
    assign_slots = verify_slots = None


class EndpointSlotsTest(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(assign_slots, "Measured free-slot allocator is not implemented")

    def test_nearest_slots_split_gaps_and_then_use_another_row(self):
        gaps = [(0, 40, 0, "N"), (0, 40, 10, "FS")]
        targets = [(name, 18, 0) for name in "ABCD"]
        slots = assign_slots(gaps, targets, width=8, site=2, origin=0, height=10)
        self.assertEqual(slots, {
            "A": (18, 0, "N"), "B": (10, 0, "N"),
            "C": (26, 0, "N"), "D": (18, 10, "FS"),
        })
        verify_slots(gaps, slots, list("ABCD"), width=8, site=2, origin=0, height=10)

    def test_grid_rounding_and_equal_distance_choose_lower_coordinate(self):
        slots = assign_slots([(2, 30, 0, "N")], [("A", 9, 0), ("B", 10, 0)],
                             width=8, site=4, origin=2, height=10)
        self.assertEqual(slots, {"A": (10, 0, "N"), "B": (2, 0, "N")})

    def test_vertical_distance_can_beat_horizontal_distance(self):
        slots = assign_slots([(100, 120, 0, "N"), (0, 20, 10, "FS")], [("A", 0, 0)],
                             width=8, site=2, origin=0, height=10)
        self.assertEqual(slots, {"A": (0, 10, "FS")})

    def test_exhaustion_does_not_mutate_supplied_geometry(self):
        gaps = [(0, 8, 0, "N")]
        with self.assertRaises(ValueError):
            assign_slots(gaps, [("A", 0, 0), ("B", 0, 0)],
                         width=8, site=2, origin=0, height=10)
        self.assertEqual(gaps, [(0, 8, 0, "N")])

    def test_rejects_invalid_geometry_capacity_and_duplicate_targets(self):
        for gaps in [[], [(0, 16, 0, "N"), (8, 24, 0, "N")],
                     [(0, 16, 0, "N"), (0, 16, 5, "FS")],
                     [(1, 17, 0, "N")], [(0, 16, 0, "FN")]]:
            with self.subTest(gaps=gaps), self.assertRaises(ValueError):
                assign_slots(gaps, [("A", 0, 0)], width=8, site=2, origin=0, height=10)
        for width in [0, -2, 3, True]:
            with self.subTest(width=width), self.assertRaises(ValueError):
                assign_slots([(0, 16, 0, "N")], [("A", 0, 0)],
                             width=width, site=2, origin=0, height=10)
        with self.assertRaises(ValueError):
            assign_slots([(0, 16, 0, "N")], [("A", 0, 0), ("A", 2, 0)],
                         width=8, site=2, origin=0, height=10)

    def test_independent_verifier_rejects_overlap_missing_off_grid_and_wrong_row(self):
        gaps = [(0, 40, 0, "N")]
        for slots in [{"A": (0, 0, "N"), "B": (0, 0, "N")},
                      {"A": (0, 0, "N")},
                      {"A": (1, 0, "N"), "B": (10, 0, "N")},
                      {"A": (0, 0, "FS"), "B": (10, 0, "N")},
                      {"A": (0, 10, "N"), "B": (10, 0, "N")},
                      {"A": (-2, 0, "N"), "B": (10, 0, "N")}]:
            with self.subTest(slots=slots), self.assertRaises(ValueError):
                verify_slots(gaps, slots, ["A", "B"], width=8, site=2, origin=0, height=10)


if __name__ == "__main__":
    unittest.main()
