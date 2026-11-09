"""Reject lost or modified original cells without loading a full chip into Python."""
from pathlib import Path
import shutil
import tempfile
import unittest

from tri_oracle_core_preservation import verify_core_snapshots


HEADER = "instance\tmaster\tlocation\torientation\n"
CORE = "fabric/clusters[0].unit/cluster/implementation/cores[0]"
OTHER = "fabric/clusters[4].unit/cluster/implementation/cores[3]"


class CorePreservationTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="core_preservation24_", dir=".cache/physical")
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.before = self.folder/"before.tsv"
        self.after = self.folder/"after.tsv"
        self.lines = []
        # Independently enumerated complete-core inventory: 18+2+8 memory banks
        # and 94443 ordinary cells, totaling the native core's 94471 cells.
        for master, count in [("TS5N28HPCPSVTA32X128M2FW", 18),
                              ("TS5N28HPCPSVTA512X64M4F", 2),
                              ("TS6N28HPCPSVTA16X128M2F", 8),
                              ("DFQD1BWP12T40P140", 94443)]:
            for i in range(count):
                self.lines.append(f"{CORE}/{master}_{i}\t{master}\t{{210.0 45.0}}\tr0\n")
        self.before.write_text(HEADER+"".join(self.lines))
        shutil.copyfile(self.before, self.after)

    def test_reordered_complete_native_records_preserve_all_original_cells(self):
        # A line-order-sensitive comparison would reject unchanged model cells.
        self.after.write_text(HEADER+"".join(reversed(self.lines)))
        result = verify_core_snapshots(self.before, self.after, [CORE])
        self.assertEqual(result["cells_per_core"], {CORE: 94471})
        self.assertEqual(result["memory_macros_per_core"], {CORE: {
            "TS5N28HPCPSVTA32X128M2FW": 18,
            "TS5N28HPCPSVTA512X64M4F": 2,
            "TS6N28HPCPSVTA16X128M2F": 8}})
        self.assertTrue(result["all_original_cell_names_masters_and_geometry_preserved"])

    def test_coordinate_change_cannot_pass_equal_cell_counts(self):
        changed = self.lines.copy()
        changed[-1] = changed[-1].replace("210.0 45.0", "210.14 45.0")
        self.after.write_text(HEADER+"".join(changed))
        with self.assertRaisesRegex(ValueError, "changed"):
            verify_core_snapshots(self.before, self.after, [CORE])

    def test_master_change_cannot_pass_equal_cell_counts(self):
        changed = self.lines.copy()
        changed[-1] = changed[-1].replace("\tDFQD1BWP12T40P140\t", "\tDFQD2BWP12T40P140\t")
        self.after.write_text(HEADER+"".join(changed))
        with self.assertRaisesRegex(ValueError, "changed"):
            verify_core_snapshots(self.before, self.after, [CORE])

    def test_identically_missing_cells_are_rejected(self):
        self.before.write_text(HEADER+"".join(self.lines[:-1]))
        shutil.copyfile(self.before, self.after)
        with self.assertRaisesRegex(ValueError, "94471"):
            verify_core_snapshots(self.before, self.after, [CORE])

    def test_duplicate_name_cannot_replace_a_missing_cell(self):
        changed = self.lines.copy()
        changed[-1] = changed[-2]
        self.before.write_text(HEADER+"".join(changed))
        shutil.copyfile(self.before, self.after)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            verify_core_snapshots(self.before, self.after, [CORE])

    def test_both_snapshots_need_all_original_memory_masters(self):
        changed = self.lines.copy()
        changed[0] = changed[0].replace("\tTS5N28HPCPSVTA32X128M2FW\t", "\tDFQD1BWP12T40P140\t")
        self.before.write_text(HEADER+"".join(changed))
        shutil.copyfile(self.before, self.after)
        with self.assertRaisesRegex(ValueError, "memory"):
            verify_core_snapshots(self.before, self.after, [CORE])

    def test_cells_of_an_unexpected_core_are_rejected(self):
        self.before.write_text(HEADER+"".join(self.lines).replace(CORE, OTHER))
        shutil.copyfile(self.before, self.after)
        with self.assertRaisesRegex(ValueError, "Unexpected"):
            verify_core_snapshots(self.before, self.after, [CORE])

    def test_total_count_cannot_hide_missing_cells_in_one_core(self):
        # Total remains 188942, but distribution is 94470+94472.
        second = [line.replace(CORE, OTHER) for line in self.lines]
        moved = self.lines[-1].replace(CORE, OTHER).replace("DFQD1BWP12T40P140_94442", "extra_original")
        self.before.write_text(HEADER+"".join(self.lines[:-1]+second+[moved]))
        shutil.copyfile(self.before, self.after)
        with self.assertRaisesRegex(ValueError, "94471"):
            verify_core_snapshots(self.before, self.after, [CORE, OTHER])

    def test_empty_or_duplicated_core_list_is_rejected(self):
        for prefixes in [[], [CORE, CORE]]:
            with self.subTest(prefixes=prefixes), self.assertRaises(ValueError):
                verify_core_snapshots(self.before, self.after, prefixes)


if __name__ == "__main__":
    unittest.main()
