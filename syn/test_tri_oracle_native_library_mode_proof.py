"""Check the real native-proof command's evidence boundaries."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tri_oracle_library_mode import audit_library_modes


class NativeProofBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.library = Path(".cache/physical/library/tcbn28hpcplusbwp12t40p140.v")
        cls.validator = Path("syn/tri_oracle_library_mode.py")
        with tempfile.TemporaryDirectory(prefix="proof_boundary_library_", dir=".cache") as directory:
            sources = []
            for name, flags in (("default", []), ("functional", ["-DTETRAMAX"])):
                path = Path(directory) / (name + ".v")
                subprocess.run(["iverilog", "-g2012", "-E", *flags, "-o", str(path), str(cls.library)], check=True)
                sources.append(path.read_text())
            cls.audit_template = audit_library_modes(*sources, {"CKBD1BWP12T40P140": 1})

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="proof_boundary_", dir=".cache")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def audit(self, name="audit.json", extra_cell=False):
        netlist = self.root / "netlist.v"
        cells = ["CKBD1BWP12T40P140 buffer0 (.I(I), .Z(mid));"]
        if extra_cell:
            cells.append("INVD1BWP12T40P140 inverter0 (.I(mid), .ZN(Z));")
        else:
            cells.append("assign Z=mid;")
        netlist.write_text("module fixture(input I, output Z); wire mid;\n" + "\n".join(cells) + "\nendmodule\n")
        record = dict(self.audit_template)
        record.update(netlist=str(netlist), netlist_sha256=hashlib.sha256(netlist.read_bytes()).hexdigest(),
                      library_sha256=hashlib.sha256(self.library.read_bytes()).hexdigest(),
                      validator_sha256=hashlib.sha256(self.validator.read_bytes()).hexdigest())
        path = self.root / name
        path.write_text(json.dumps(record) + "\n")
        return path

    def run_proof(self, audit, proof):
        return subprocess.run([sys.executable, "-B", "syn/tri_oracle_native_library_mode_proof.py", str(audit), str(proof)],
                              text=True, capture_output=True, timeout=30)

    def test_existing_log_is_never_overwritten(self):
        audit = self.audit()
        proof = self.root / "proof.json"
        log = proof.with_suffix(".log")
        log.write_bytes(b"prior evidence must survive")
        result = self.run_proof(audit, proof)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Proof output", result.stderr)
        self.assertEqual(log.read_bytes(), b"prior evidence must survive")
        self.assertFalse(proof.exists())

    def test_log_alias_of_audit_is_rejected_before_comparison(self):
        audit = self.audit("proof.log")
        original = audit.read_bytes()
        proof = self.root / "proof.json"
        result = self.run_proof(audit, proof)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Proof output", result.stderr)
        self.assertEqual(audit.read_bytes(), original)
        self.assertFalse(proof.exists())

    def test_proof_and_log_cannot_be_the_same_output(self):
        audit = self.audit()
        proof = self.root / "proof.log"
        result = self.run_proof(audit, proof)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Proof output", result.stderr)
        self.assertFalse(proof.exists())

    def test_audit_cannot_omit_a_used_cell_model(self):
        audit = self.audit(extra_cell=True)
        proof = self.root / "proof.json"
        result = self.run_proof(audit, proof)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("used-model inventory", result.stderr)
        self.assertFalse(proof.exists())

    def omitted_model_variant(self, old, new):
        audit = self.audit(extra_cell=True)
        record = json.loads(audit.read_text())
        netlist = Path(record["netlist"])
        source = netlist.read_text()
        self.assertIn(old, source)
        netlist.write_text(source.replace(old, new))
        record["netlist_sha256"] = hashlib.sha256(netlist.read_bytes()).hexdigest()
        audit.write_text(json.dumps(record) + "\n")
        proof = self.root / "proof.json"
        result = self.run_proof(audit, proof)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("used-model inventory", result.stderr)
        self.assertFalse(proof.exists())

    def test_same_line_second_instance_cannot_be_omitted(self):
        self.omitted_model_variant(".Z(mid));\nINVD1", ".Z(mid)); INVD1")

    def test_attribute_prefixed_instance_cannot_be_omitted(self):
        self.omitted_model_variant("INVD1BWP12T40P140 inverter0", "(* keep = 1 *) INVD1BWP12T40P140 inverter0")

    def test_unsupported_instance_array_cannot_be_omitted(self):
        self.omitted_model_variant("INVD1BWP12T40P140 inverter0", "INVD1BWP12T40P140 inverter0[0:0]")

    def test_escaped_cell_type_cannot_be_omitted(self):
        self.omitted_model_variant("INVD1BWP12T40P140 inverter0", r"\INVD1BWP12T40P140 inverter0")

    def test_valid_native_negative_control_and_model_comparison(self):
        audit = self.audit()
        proof = self.root / "proof.json"
        result = self.run_proof(audit, proof)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        record = json.loads(proof.read_text())
        self.assertEqual(record["cell_types"], 1)
        self.assertTrue(record["comparison_passed"])
        self.assertTrue(record["wrong_functional_primitive_mutant_rejected"])
        self.assertTrue(record["every_output_model_produced_known_outputs"])
        log = proof.with_suffix(".log").read_text()
        self.assertIn("NATIVE_MODE_MISMATCH CKBD1BWP12T40P140", log)
        self.assertIn("NATIVE_MODE_PASS models=1", log)


if __name__ == "__main__":
    unittest.main()
