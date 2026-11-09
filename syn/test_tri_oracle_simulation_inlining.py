"""Guard the zero-delay simulation rewrite, independently of chip RTL."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest

from tri_oracle_simulation_inlining import inline_netlist, simple_cell_models


LIBRARY = """
module BUFFER (I, Z);
 input I; output Z; buf (Z, I);
 specify (I => Z) = (0, 0); endspecify
endmodule
module INVERTER (I, ZN);
 input I; output ZN; not (ZN, I);
endmodule
module STATE (D, CP, Q);
 input D, CP; output Q; reg Q; always @(posedge CP) Q <= D;
endmodule
module DELAYED (I,Z);
 input I; output Z; buf #1 (Z,I);
endmodule
module TRI (I,Z);
 input I; output Z; bufif1 (Z,I,1'b1);
endmodule
"""


class SimulationInliningTest(unittest.TestCase):
    def test_cli_preserves_inputs_rejects_aliases_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory(prefix="simulation_inlining_cli_", dir=".cache") as directory:
            path = Path(directory)
            library, netlist, output, manifest = [path / name for name in ("library.v", "netlist.v", "output.v", "manifest.json")]
            source = "module top(a,z);\ninput a;output z;\nBUFFER b (.I(a),.Z(z));\nendmodule\n"
            library.write_text(LIBRARY)
            netlist.write_text(source)
            def run(destination, record):
                return subprocess.run(
                    [sys.executable, "-B", "syn/tri_oracle_simulation_inlining.py",
                     "--library", str(library), "--netlist", str(netlist),
                     "--output", str(destination), "--manifest", str(record)],
                    capture_output=True, text=True, timeout=30)
            for destination, record in ((library, manifest), (netlist, manifest),
                                         (output, library), (output, netlist), (output, output)):
                rejected = run(destination, record)
                self.assertNotEqual(rejected.returncode, 0)
                self.assertIn("must be distinct", rejected.stderr)
                self.assertEqual(library.read_text(), LIBRARY)
                self.assertEqual(netlist.read_text(), source)
                self.assertFalse(output.exists())
            accepted = run(output, manifest)
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            record = json.loads(manifest.read_text())
            self.assertEqual(record["inlined_instances"], 1)
            self.assertEqual(record["source_sha256"], hashlib.sha256(netlist.read_bytes()).hexdigest())
            self.assertEqual(record["simulation_sha256"], hashlib.sha256(output.read_bytes()).hexdigest())
            self.assertIn("buf b  (z , a );", output.read_text())
            output_bytes, manifest_bytes = output.read_bytes(), manifest.read_bytes()
            rejected = run(output, manifest)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("Refusing to overwrite", rejected.stderr)
            self.assertEqual((output.read_bytes(), manifest.read_bytes()), (output_bytes, manifest_bytes))

    def test_actual_library_four_state_equivalence_and_wrong_primitive_mutant(self):
        library = Path(".cache/physical/library/tcbn28hpcplusbwp12t40p140.v")
        models = simple_cell_models(library.read_text())
        self.assertGreater(len(models), 0)
        original = f"module candidates(stim,result);\ninput stim;\noutput [{len(models)-1}:0] result;\n"
        for index, (model, (_, source, destination)) in enumerate(sorted(models.items())):
            original += f"{model} cell_{index} (.{source}(stim), .{destination}(result[{index}]));\n"
        original += "endmodule\n"
        transformed, counts = inline_netlist(original, models)
        self.assertEqual(sum(counts.values()), len(models))
        transformed = transformed.replace("module candidates(", "module candidates_inline(", 1)
        bench = f"""`timescale 1ns/1ps
module proof;
reg stim;
wire [{len(models)-1}:0] original, transformed;
integer value;
candidates reference (.stim(stim),.result(original));
candidates_inline candidate (.stim(stim),.result(transformed));
initial begin
for(value=0;value<4;value=value+1) begin
case(value) 0:stim=0;1:stim=1;2:stim=1'bx;3:stim=1'bz;endcase
#2;
if(original!==transformed) $fatal(1,"four-state cell-model mismatch");
end
$display("PASS: every eligible library model matches for0/1/X/Z");
$finish;
end
endmodule
"""
        with tempfile.TemporaryDirectory(prefix="simulation_inlining_test_", dir=".cache") as directory:
            path = Path(directory)
            (path / "proof.v").write_text(bench)
            # First run the real rewrite; then prove this same external check
            # detects a deliberately wrong primitive, without changing inputs.
            for mutant in (False, True):
                candidate = transformed
                if mutant:
                    first = next(line for line in transformed.splitlines() if line.startswith(("buf ", "not ")))
                    wrong = ("not" if first.startswith("buf") else "buf") + first[3:]
                    candidate = candidate.replace(first, wrong, 1)
                (path / "cells.v").write_text(original + candidate)
                compiled = subprocess.run(
                    ["iverilog", "-g2012", "-s", "proof", "-o", str(path / "proof.vvp"),
                     str(library), str(path / "cells.v"), str(path / "proof.v")],
                    capture_output=True, text=True, timeout=30)
                self.assertEqual(compiled.returncode, 0, compiled.stderr)
                run = subprocess.run(["vvp", str(path / "proof.vvp")], capture_output=True, text=True, timeout=30)
                if mutant:
                    self.assertNotEqual(run.returncode, 0)
                    self.assertIn("four-state cell-model mismatch", run.stdout)
                else:
                    self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                    self.assertIn("PASS: every eligible library model", run.stdout)

    def test_only_exact_native_one_gate_cells_are_eligible(self):
        models = simple_cell_models(LIBRARY)
        self.assertEqual(set(models), {"BUFFER", "INVERTER"})

    def test_named_connections_and_escaped_names(self):
        source = r"""module top(a,z);
 input a; output z; wire \bank[7].q ;
 BUFFER \buf/0 (.Z(\bank[7].q ), .I(a));
 INVERTER inv (.I(\bank[7].q ), .ZN(z));
endmodule
"""
        result, counts = inline_netlist(source, simple_cell_models(LIBRARY))
        self.assertEqual(counts, {"BUFFER": 1, "INVERTER": 1})
        self.assertIn(r"buf \buf/0  (\bank[7].q , a );", result)
        self.assertIn(r"not inv  (z , \bank[7].q );", result)

    def test_state_vector_unknown_and_complex_connections_are_preserved(self):
        source = """module top(a,z,clk);
 input [3:0] a; input clk; output [3:0] z;
 STATE ff (.D(a[0]), .CP(clk), .Q(z[0]));
 BUFFER vector (.I(a), .Z(z));
 BUFFER unknown (.I(undeclared), .Z(z[1]));
 BUFFER expression (.I(a[1] & a[2]), .Z(z[2]));
 BUFFER selected (.I(a[3]), .Z(z[3]));
endmodule
"""
        result, counts = inline_netlist(source, simple_cell_models(LIBRARY))
        self.assertEqual(counts, {"BUFFER": 1})
        for name in ("STATE ff", "BUFFER vector", "BUFFER unknown", "BUFFER expression"):
            self.assertIn(name, result)
        self.assertIn("buf selected  (z[3] , a[3] );", result)

    def test_duplicate_or_missing_ports_do_not_rewrite(self):
        source = """module top(a,z);
 input a; output z;
 BUFFER duplicate (.I(a), .I(a), .Z(z));
 BUFFER missing (.I(a));
endmodule
"""
        self.assertEqual(inline_netlist(source, simple_cell_models(LIBRARY)), (source, {}))


if __name__ == "__main__":
    unittest.main()
