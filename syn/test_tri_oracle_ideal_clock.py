"""Native clock-race regression and rejection of unsafe clock rewrites."""
from pathlib import Path
import resource
import subprocess
import tempfile
import unittest

from tri_oracle_ideal_clock import rewrite_clocks


LIBRARY = """
primitive tsmc_dff(q,d,cp);
output q; reg q; input d,cp;
table
0 (01) : ? : 0;
1 (01) : ? : 1;
? (10) : ? : -;
* ? : ? : -;
endtable
endprimitive
module BUF(I,Z); input I; output Z; buf(Z,I); endmodule
module INV(I,ZN); input I; output ZN; not(ZN,I); endmodule
module FF(D,CP,Q); input D,CP; output Q; wire qi;
tsmc_dff(qi,D,CP); buf(Q,qi); endmodule
"""
NETLIST = """
module chip(clk,go,closed);
input clk,go; output closed;
wire cs,c0,c1,c2,c3,c4,c5,c6,c7,cc,state;
BUF s(.I(clk),.Z(cs));
BUF b0(.I(clk),.Z(c0));
BUF b1(.I(c0),.Z(c1));
BUF b2(.I(c1),.Z(c2));
BUF b3(.I(c2),.Z(c3));
BUF b4(.I(c3),.Z(c4));
BUF b5(.I(c4),.Z(c5));
BUF b6(.I(c5),.Z(c6));
BUF b7(.I(c6),.Z(c7));
BUF b8(.I(c7),.Z(cc));
FF first(.D(go),.CP(cs),.Q(state));
FF second(.D(state),.CP(cc),.Q(closed));
endmodule
"""
COUNTS = {"BUF": 10, "FF": 2}
BENCH = """
`timescale 1ns/1ps
module tb;
reg clk=0,go=0; wire closed;
always #5 clk=~clk;
chip dut(.clk(clk),.go(go),.closed(closed));
initial begin
 #20;go=1;#6;
 if(closed!==0) $fatal(1,"CLOCK_RACE_WAS_NOT_REMOVED");
 #10;if(closed!==1) $fatal(1,"DATA_LOGIC_WAS_CHANGED");
 $display("IDEAL_CLOCK_NATIVE_PASS");$finish;
end
endmodule
"""


class IdealClockTest(unittest.TestCase):
    def simulate(self, netlist, bench=BENCH):
        def bounded():
            resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
        with tempfile.TemporaryDirectory(prefix="ideal_clock_test_", dir=".cache") as directory:
            root = Path(directory)
            files = []
            for name, text in [("library.v", LIBRARY), ("chip.v", netlist), ("bench.sv", bench)]:
                path = root/name
                path.write_text(text)
                files.append(str(path))
            binary = root/"test.vvp"
            compiled = subprocess.run(["iverilog", "-g2012", "-s", "tb", "-o", str(binary), *files],
                                      capture_output=True, text=True, timeout=30, preexec_fn=bounded)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run(["vvp", str(binary)], capture_output=True, text=True,
                                    timeout=30, preexec_fn=bounded)
        self.assertFalse(root.exists())
        return result

    def rewrite(self, source=NETLIST, counts=COUNTS):
        return rewrite_clocks(source, LIBRARY, counts, "chip", "tb.dut.clk")

    def test_native_unequal_clock_depth_race_and_shared_event_repair(self):
        original = self.simulate(NETLIST)
        self.assertNotEqual(original.returncode, 0)
        self.assertIn("CLOCK_RACE_WAS_NOT_REMOVED", original.stdout)
        derived, report = self.rewrite()
        result = self.simulate(derived)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertIn("IDEAL_CLOCK_NATIVE_PASS", result.stdout)
        self.assertEqual(report["rewritten_clock_pins"], 2)

    def test_clock_derived_data_reset_or_enable_load_is_rejected(self):
        for source in [NETLIST.replace(".D(go)", ".D(c0)"),
                       NETLIST.replace(".D(state)", ".D(clk)")]:
            with self.subTest(source=source):
                with self.assertRaisesRegex(ValueError, "non.clock load"):
                    self.rewrite(source)

    def test_duplicate_clock_driver_is_rejected(self):
        source = NETLIST.replace("endmodule", "BUF duplicate(.I(go),.Z(cs));\nendmodule")
        with self.assertRaisesRegex(ValueError, "multiple drivers"):
            self.rewrite(source, {"BUF": 11, "FF": 2})

    def test_gated_or_inverted_clock_is_rejected(self):
        source = NETLIST.replace("BUF s(.I(clk),.Z(cs));", "INV s(.I(clk),.ZN(cs));")
        with self.assertRaisesRegex(ValueError, "root clock|non-clock load"):
            self.rewrite(source, {"BUF": 9, "INV": 1, "FF": 2})

    def test_non_wire_clock_net_is_rejected(self):
        source = NETLIST.replace("wire cs,c0", "tri cs; wire c0")
        with self.assertRaisesRegex(ValueError, "wire"):
            self.rewrite(source)

    def test_behavioral_or_force_input_is_rejected(self):
        source = NETLIST.replace("endmodule", "initial force cs=clk;\nendmodule")
        with self.assertRaisesRegex(ValueError, "behavioral"):
            self.rewrite(source)

    def test_inventory_mismatch_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "inventory"):
            self.rewrite(counts={"BUF": 9, "FF": 2})

    def test_binary_clock_guard_rejects_high_impedance(self):
        derived, _ = self.rewrite()
        bench = BENCH.replace("#20;go=1;#6;", "#2;clk=1'bz;#1;")
        result = self.simulate(derived, bench)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("IDEAL_CLOCK_NONBINARY", result.stdout)

    def test_hierarchical_clock_ports_preserve_data_and_share_root(self):
        source = """
module leaf(c,d,q); input c,d; output q; FF f(.D(d),.CP(c),.Q(q)); endmodule
module chip(clk,go,closed); input clk,go; output closed;
wire x; BUF b(.I(clk),.Z(x)); leaf unit(.c(x),.d(go),.q(closed)); endmodule
"""
        derived, report = self.rewrite(source, {"BUF": 1, "FF": 1})
        self.assertIn(".D(d)", derived)
        self.assertIn(".CP(tb.dut.clk)", derived)
        self.assertEqual(report["rewritten_clock_pins"], 1)

    def test_shared_module_definition_is_rejected(self):
        source = """
module leaf(c,d,q); input c,d; output q; FF f(.D(d),.CP(c),.Q(q)); endmodule
module chip(clk,go,closed); input clk,go; output closed; wire other;
leaf a(.c(clk),.d(go),.q(closed)); leaf b(.c(clk),.d(go),.q(other)); endmodule
"""
        with self.assertRaisesRegex(ValueError, "unique"):
            self.rewrite(source, {"FF": 1})

    def test_wrong_data_connection_still_fails_native_comparison(self):
        wrong = NETLIST.replace(".D(state)", ".D(1'b0)")
        derived, _ = self.rewrite(wrong)
        result = self.simulate(derived)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DATA_LOGIC_WAS_CHANGED", result.stdout)

    def test_unnamed_primitive_cannot_hide_a_driver_or_clock_data_load(self):
        for primitive in ["buf (cs,go);", "buf (state,clk);"]:
            source = NETLIST.replace("endmodule", primitive+"\nendmodule")
            with self.subTest(primitive=primitive):
                with self.assertRaisesRegex(ValueError, "unconsumed|primitive"):
                    self.rewrite(source)

    def test_unresolved_hierarchical_clock_data_connections_are_rejected(self):
        for declaration, expression, reference in [
            ("input [0:0] d;", "clk", "d[0]"),
            ("inout d;", "clk", "d"),
            ("input d;", "clk & go", "d"),
            ("input [1:0] d;", "{go,clk}", "d[0]"),
        ]:
            source = f"""
module leaf(c,d,q); input c; {declaration} output q;
FF f(.D({reference}),.CP(c),.Q(q)); endmodule
module chip(clk,go,closed); input clk,go; output closed;
leaf unit(.c(clk),.d({expression}),.q(closed)); endmodule
"""
            with self.subTest(declaration=declaration, expression=expression):
                with self.assertRaisesRegex(ValueError, "non-clock load"):
                    self.rewrite(source, {"FF": 1})

    def test_unused_unconnected_hierarchical_input_remains_unconnected(self):
        source = """
module leaf(c,d,unused,q); input c,d,unused; output q;
FF f(.D(d),.CP(c),.Q(q)); endmodule
module chip(clk,go,closed); input clk,go; output closed;
leaf unit(.c(clk),.d(go),.q(closed)); endmodule
"""
        try:
            derived, report = self.rewrite(source, {"FF": 1})
        except ValueError as error:
            self.fail("Unused unconnected input must not prevent clock proof: "+str(error))
        self.assertIn(".D(d)", derived)
        self.assertEqual(report["rewritten_clock_pins"], 1)

    def test_complex_leaf_clock_data_expression_is_rejected(self):
        for expression in ["{clk}", "clk & go", "clk[0]"]:
            with self.subTest(expression=expression):
                with self.assertRaisesRegex(ValueError, "non-clock load"):
                    self.rewrite(NETLIST.replace(".D(go)", ".D("+expression+")"))

    def test_second_external_input_in_clock_tree_is_rejected(self):
        source = """
module chip(clk,go,closed); input clk,go; output closed;
BUF b(.I(clk),.Z(go)); FF f(.D(1'b0),.CP(go),.Q(closed)); endmodule
"""
        with self.assertRaisesRegex(ValueError, "external driver|top-level"):
            self.rewrite(source, {"BUF": 1, "FF": 1})


if __name__ == "__main__":
    unittest.main()
