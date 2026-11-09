"""Fail-closed checks for the supplied library's zero-delay functional mode."""
import ast
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tri_oracle_library_mode import ModeError, audit_library_modes


PRIMITIVES = """
primitive state(q,d,cp,n);
output q; reg q; input d,cp,n;
table
0 (01) ? : ? : 0;
1 (01) ? : ? : 1;
endtable
endprimitive
primitive observe(q,d);
output q; input d;
table
0 : 0;
1 : 1;
endtable
endprimitive
"""
CORE = """
module CELL(D, CP, Q);
input D, CP; output Q; reg notifier;
state (internal, D, CP, notifier);
buf (Q, internal);
{extra}
endmodule
"""
DEFAULT = PRIMITIVES + CORE.replace("{extra}", "observe (probe, D); specify (D => Q)=(0,0); endspecify")
FUNCTIONAL = PRIMITIVES + CORE.replace("{extra}", "")


class LibraryModeTest(unittest.TestCase):
    def test_real_gate_launcher_binds_mode_to_proven_library_and_netlist(self):
        launcher = Path("syn/run_tri_oracle_core_gate_profile.sh").read_text()
        program = launcher.split("<<'PY_GUARD'\n", 1)[1].rsplit("\nPY_GUARD", 1)[0]
        tree = ast.parse(program)
        names = {"digest", "qualify_library_functional_mode"}
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
        self.assertEqual({node.name for node in functions}, names)
        namespace = {"Path": Path, "hashlib": hashlib, "json": json}
        exec(compile(ast.Module(body=functions, type_ignores=[]), "gate_preflight", "exec"), namespace)
        qualify = namespace["qualify_library_functional_mode"]
        digest = namespace["digest"]
        with tempfile.TemporaryDirectory(prefix="library_mode_contract_", dir=".cache") as directory:
            root = Path(directory)
            library, netlist, bench = [root / name for name in ("library.v", "netlist.v", "bench.sv")]
            for path in (library, netlist, bench):
                path.write_text("module example; endmodule\n")
            audit_path = root / "library_functional_mode_structural_audit.json"
            proof_path = root / "library_functional_mode_dynamic_proof.json"
            validator = Path("syn/tri_oracle_library_mode.py")
            audit = {"netlist_sha256": digest(netlist), "library_sha256": digest(library),
                     "validator_sha256": digest(validator), "audited_cell_types": 1}
            audit_path.write_text(json.dumps(audit))
            proof = {"structural_audit_sha256": digest(audit_path), "library_sha256": digest(library),
                     "validator_sha256": digest(validator), "comparison_passed": True,
                     "wrong_functional_primitive_mutant_rejected": True,
                     "every_output_model_produced_known_outputs": True, "cell_types": 1}
            proof_path.write_text(json.dumps(proof))
            self.assertEqual(set(qualify(netlist, library, bench, root)), {audit_path, proof_path, validator})
            for field, wrong in (("comparison_passed", False), ("validator_sha256", "stale"),
                                 ("structural_audit_sha256", "stale"),
                                 ("wrong_functional_primitive_mutant_rejected", False)):
                proof_path.write_text(json.dumps({**proof, field: wrong}))
                with self.assertRaises(ValueError):
                    qualify(netlist, library, bench, root)
            proof_path.write_text(json.dumps(proof))
            netlist.write_text("module changed; endmodule\n")
            with self.assertRaises(ValueError):
                qualify(netlist, library, bench, root)

    def test_dead_observers_may_be_removed_without_changing_state(self):
        result = audit_library_modes(DEFAULT, FUNCTIONAL, {"CELL": 7})
        self.assertEqual(result["audited_cell_types"], 1)
        self.assertEqual(result["audited_cell_instances"], 7)
        self.assertEqual(result["removed_observer_components"], 7)
        self.assertEqual(result["state_components_preserved"], 7)

    def test_functional_connection_change_is_rejected(self):
        mutant = FUNCTIONAL.replace("internal, D, CP", "internal, CP, CP")
        with self.assertRaises(ModeError):
            audit_library_modes(DEFAULT, mutant, {"CELL": 1})

    def test_state_table_change_is_rejected(self):
        mutant = FUNCTIONAL.replace("0 (01) ? : ? : 0", "0 (01) ? : ? : 1")
        with self.assertRaises(ModeError):
            audit_library_modes(DEFAULT, mutant, {"CELL": 1})

    def test_even_unobservable_state_cannot_be_removed(self):
        original = DEFAULT.replace("observe (probe, D);", "state (hidden, D, CP, notifier); observe (probe, D);")
        with self.assertRaises(ModeError):
            audit_library_modes(original, FUNCTIONAL, {"CELL": 1})

    def test_retained_unobservable_state_input_driver_cannot_be_removed(self):
        extra = "state (hidden, feed, CP, notifier);"
        original = DEFAULT.replace("observe (probe, D);", extra + "buf (feed, D); observe (probe, D);")
        candidate = FUNCTIONAL.replace("buf (Q, internal);", "buf (Q, internal);" + extra)
        with self.assertRaises(ModeError):
            audit_library_modes(original, candidate, {"CELL": 1})

    def test_input_port_driver_is_part_of_the_observable_boundary(self):
        original = PRIMITIVES + "module CELL(I,Q); input I; output Q; buf(Q,1'b0); pullup(I); endmodule"
        candidate = original.replace("pullup(I);", "")
        with self.assertRaises(ModeError):
            audit_library_modes(original, candidate, {"CELL": 1})

    def test_unknown_behavior_is_rejected_even_outside_the_output_cone(self):
        mutant = FUNCTIONAL.replace("reg notifier;", "reg notifier; always @(D) notifier = D;")
        with self.assertRaises(ModeError):
            audit_library_modes(DEFAULT, mutant, {"CELL": 1})

    def test_reg_initialization_and_interface_changes_are_rejected(self):
        for mutant in (FUNCTIONAL.replace("reg notifier;", "reg notifier=0;"),
                       FUNCTIONAL.replace("CELL(D, CP, Q)", "CELL(CP, D, Q)")):
            with self.assertRaises(ModeError):
                audit_library_modes(DEFAULT, mutant, {"CELL": 1})

    def test_missing_models_and_empty_audits_are_rejected(self):
        for instances in ({"MISSING": 1}, {}):
            with self.assertRaises(ModeError):
                audit_library_modes(DEFAULT, FUNCTIONAL, instances)

    def test_context_sensitive_directive_relocation_is_rejected(self):
        cell = "module CELL(I,Q); input I; output Q; buf(Q,hidden); endmodule\n"
        original = "`default_nettype wire\n" + cell + "`default_nettype tri1\n"
        candidate = "`default_nettype wire\n`default_nettype tri1\n" + cell
        with self.assertRaises(ModeError):
            audit_library_modes(original, candidate, {"CELL": 1})

    def test_combinational_feedback_cannot_be_classified_as_an_observer(self):
        original = FUNCTIONAL.replace("buf (Q, internal);", "buf (Q, internal); not(n,a); or(a,n,D);")
        with self.assertRaises(ModeError):
            audit_library_modes(original, FUNCTIONAL, {"CELL": 1})


if __name__ == "__main__":
    unittest.main()
