import unittest

from verify_tri_oracle_ranked_sign_gate import bindings


class RankedGatePortTest(unittest.TestCase):
    def setUp(self):
        self.source = {"rsp_data": ("input", ((1, 0), (511, 0))), "clk": ("input", ())}

    def test_binds_split_lanes_by_index_regardless_of_export_order(self):
        mapped = {"rsp_data[1]": ("input", (511, 0)), "clk": ("input", None),
                  "rsp_data[0]": ("input", (511, 0))}
        self.assertEqual(bindings(self.source, mapped), [
            r".\rsp_data[0] (rsp_data[0])", r".\rsp_data[1] (rsp_data[1])", ".clk(clk)",
        ])

    def test_rejects_a_reversed_lane(self):
        mapped = {"rsp_data[0]": ("input", (0, 511)), "rsp_data[1]": ("input", (511, 0)),
                  "clk": ("input", None)}
        with self.assertRaisesRegex(ValueError, "Port shape"):
            bindings(self.source, mapped)


if __name__ == "__main__":
    unittest.main()
