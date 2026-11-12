import unittest

from verify_tri_oracle_compact_ranked_gate import compare_traffic, memory_traffic


ROOT = "tri_oracle_packed_sign_predictor_tb.dut"
SMALL = "TS5N28HPCPSVTA32X128M2FW"
LARGE = "TS5N28HPCPSVTA512X64M4F"


def sample(prefix):
    return [
        f"COMPACT_BANK {SMALL} {prefix}.bank{bank}.traffic {64 + bank} 32 {bank + 1:016x}"
        for bank in range(9)
    ] + [f"COMPACT_BANK {LARGE} {prefix}.lower.traffic 512 128 000000000000000a"]


class CompactBankTrafficTest(unittest.TestCase):
    def test_matches_the_traffic_after_hierarchy_changes(self):
        source = memory_traffic(sample(ROOT), ROOT)
        gate = memory_traffic(reversed(sample(f"{ROOT}.mapped")), f"{ROOT}.mapped")
        compare_traffic(source, gate)

    def test_rejects_duplicate_memory_paths(self):
        lines = sample(ROOT)
        lines[1] = lines[0]
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            memory_traffic(lines, ROOT)

    def test_rejects_missing_compiled_bank(self):
        with self.assertRaisesRegex(ValueError, "inventory"):
            memory_traffic(sample(ROOT)[1:], ROOT)

    def test_rejects_equal_counts_with_changed_addresses(self):
        source = memory_traffic(sample(ROOT), ROOT)
        lines = sample(f"{ROOT}.mapped")
        lines[1] = lines[1][:-1] + "f"
        gate = memory_traffic(lines, f"{ROOT}.mapped")
        with self.assertRaisesRegex(ValueError, "Memory traffic changed"):
            compare_traffic(source, gate)


if __name__ == "__main__":
    unittest.main()
