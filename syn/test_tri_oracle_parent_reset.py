"""Check reset tracing against small independently understandable hierarchies."""

import importlib.util
from pathlib import Path
import unittest

SOURCE = Path(__file__).with_name("prove_tri_oracle_parent_reset.py")


class ParentResetTests(unittest.TestCase):
    def setUp(self):
        self.engine()

    def engine(self):
        self.assertTrue(SOURCE.exists(), "Parent reset proof is not implemented")
        spec = importlib.util.spec_from_file_location("parent_reset_proof", SOURCE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def fixture(self, extra=b"", connection=b"x"):
        top = (
            b"module top(rst_n,mode); input rst_n,mode; wire x; "
            b"AND gate(.A(rst_n),.B(mode),.Y(x));\n"
            b"leaf child(.rst_n(x),.p1(" + connection + b"));\n" + extra + b"endmodule"
        )
        leaf = b"module leaf(rst_n,p1); input rst_n,p1; endmodule"
        library = {
            ("AND", "A"): {"direction": "input", "function": None},
            ("AND", "B"): {"direction": "input", "function": None},
            ("AND", "Y"): {"direction": "output", "function": "A & B"},
        }
        return {"top": top, "leaf": leaf}, library

    def run_fixture(self, extra=b"", connection=b"x"):
        engine = self.engine()
        modules, library = self.fixture(extra, connection)
        return engine.ResetHierarchy(
            modules.__getitem__, set(modules), library, {}
        ).prove("top", {"child": ("rst_n", "p1")})

    def test_aliases_equal_and_top_assertion_dominates(self):
        result = self.run_fixture()
        self.assertEqual(result["integer_assignments"], 4)
        self.assertEqual(result["array_count"], 1)
        self.assertTrue(result["all_reset_aliases_equal"])
        self.assertTrue(result["top_reset_assertion_dominates"])

    def test_alias_assignment_is_a_driver(self):
        engine = self.engine()
        modules, library = self.fixture(connection=b"alias")
        modules["top"] = modules["top"].replace(
            b"wire x;", b"wire x,alias; assign alias=x;"
        )
        result = engine.ResetHierarchy(
            modules.__getitem__, set(modules), library, {}
        ).prove("top", {"child": ("rst_n", "p1")})
        self.assertTrue(result["all_reset_aliases_equal"])

    def test_incorrect_alias_rejected(self):
        with self.assertRaisesRegex((AssertionError, ValueError), "alias|Alias"):
            self.run_fixture(connection=b"rst_n")

    def test_asserted_top_reset_cannot_be_disconnected(self):
        engine = self.engine()
        modules, library = self.fixture()
        modules["top"] = modules["top"].replace(b".A(rst_n)", b".A(1'b1)")
        with self.assertRaisesRegex((AssertionError, ValueError), "domin"):
            engine.ResetHierarchy(modules.__getitem__, set(modules), library, {}).prove(
                "top", {"child": ("rst_n", "p1")}
            )

    def test_multiple_drivers_rejected(self):
        with self.assertRaisesRegex((AssertionError, ValueError), "driver"):
            self.run_fixture(b"assign x=rst_n;")

    def test_top_input_may_not_be_internally_driven(self):
        with self.assertRaisesRegex((AssertionError, ValueError), "input|Input"):
            self.run_fixture(b"assign rst_n=mode;")

    def test_undriven_and_undeclared_connections_rejected(self):
        for extra, connection in [(b"wire z;", b"z"), (b"", b"absent")]:
            with (
                self.subTest(connection=connection),
                self.assertRaises((AssertionError, ValueError)),
            ):
                self.run_fixture(extra, connection)

    def test_hidden_statement_and_duplicate_instance_rejected(self):
        for extra in (b"always @* x=mode;", b"leaf child(.rst_n(x),.p1(x));"):
            with (
                self.subTest(extra=extra),
                self.assertRaises((AssertionError, ValueError)),
            ):
                self.run_fixture(extra)

    def test_cycle_rejected(self):
        engine = self.engine()
        modules, library = self.fixture()
        modules["top"] = modules["top"].replace(
            b"AND gate(.A(rst_n),.B(mode),.Y(x));", b"assign x=x;"
        )
        with self.assertRaisesRegex((AssertionError, ValueError), "cycle"):
            engine.ResetHierarchy(modules.__getitem__, set(modules), library, {}).prove(
                "top", {"child": ("rst_n", "p1")}
            )

    def test_vector_concatenation_order_and_escaped_port(self):
        engine = self.engine()
        modules = {
            "top": b"module top(rst_n,mode); input rst_n,mode; mid m(.\\r[0] ({mode,rst_n})); endmodule",
            "mid": b"module mid(\\r[0] ); input [1:0] \\r[0] ; leaf child(.rst_n(\\r[0] [0]),.p1(\\r[0] [0])); endmodule",
            "leaf": b"module leaf(rst_n,p1); input rst_n,p1; endmodule",
        }
        result = engine.ResetHierarchy(modules.__getitem__, set(modules), {}, {}).prove(
            "top", {"m/child": ("rst_n", "p1")}
        )
        self.assertEqual(result["integer_assignments"], 2)
        modules["mid"] = modules["mid"].replace(b"[0])", b"[1])")
        with self.assertRaisesRegex((AssertionError, ValueError), "domin"):
            engine.ResetHierarchy(modules.__getitem__, set(modules), {}, {}).prove(
                "top", {"m/child": ("rst_n", "p1")}
            )

    def test_unknown_master_on_reset_cone_rejected(self):
        engine = self.engine()
        modules, library = self.fixture()
        modules["top"] = modules["top"].replace(b"AND gate", b"UNKNOWN gate")
        with self.assertRaises((AssertionError, ValueError)):
            engine.ResetHierarchy(modules.__getitem__, set(modules), library, {}).prove(
                "top", {"child": ("rst_n", "p1")}
            )

    def test_permanently_asserted_reset_is_not_a_working_distribution(self):
        engine = self.engine()
        modules, library = self.fixture()
        modules["top"] = modules["top"].replace(b".A(rst_n)", b".A(1'b0)")
        with self.assertRaisesRegex((AssertionError, ValueError), "constant|depend"):
            engine.ResetHierarchy(modules.__getitem__, set(modules), library, {}).prove(
                "top", {"child": ("rst_n", "p1")}
            )

    def test_legal_escaped_colon_in_instance_name(self):
        engine = self.engine()
        modules, library = self.fixture()
        modules["top"] = modules["top"].replace(b"AND gate(", b"AND \\gate:stage_2 (")
        result = engine.ResetHierarchy(
            modules.__getitem__, set(modules), library, {}
        ).prove("top", {"child": ("rst_n", "p1")})
        self.assertTrue(result["top_reset_assertion_dominates"])

    def test_legal_escaped_colon_in_net_name(self):
        engine = self.engine()
        modules, library = self.fixture()
        modules["top"] = (
            modules["top"]
            .replace(b"wire x;", b"wire \\x:stage ;")
            .replace(b"(x)", b"(\\x:stage )")
        )
        result = engine.ResetHierarchy(
            modules.__getitem__, set(modules), library, {}
        ).prove("top", {"child": ("rst_n", "p1")})
        self.assertTrue(result["top_reset_assertion_dominates"])

    def test_repeated_output_connection_is_multiple_drivers(self):
        engine = self.engine()
        modules = {
            "top": b"module top(rst_n); input rst_n; wire x; mid m(.r(rst_n),.y({x,x})); leaf child(.rst_n(x),.p1(x)); endmodule",
            "mid": b"module mid(r,y); input r; output [1:0] y; assign y={r,r}; endmodule",
            "leaf": b"module leaf(rst_n,p1); input rst_n,p1; endmodule",
        }
        with self.assertRaisesRegex((AssertionError, ValueError), "driver"):
            engine.ResetHierarchy(modules.__getitem__, set(modules), {}, {}).prove(
                "top", {"child": ("rst_n", "p1")}
            )

    def test_unproved_complementary_state_outputs_are_independent(self):
        engine = self.engine()
        modules, library = self.fixture()
        modules["top"] = (
            b"module top(rst_n,mode); input rst_n,mode; wire q,qn,nqn,x,y; "
            b"FF state(.Q(q),.QN(qn)); INV neg(.A(qn),.Y(nqn)); "
            b"AND left(.A(rst_n),.B(q),.Y(x)); "
            b"AND right(.A(rst_n),.B(nqn),.Y(y)); "
            b"leaf child(.rst_n(x),.p1(y)); endmodule"
        )
        library.update(
            {
                ("FF", "Q"): {"direction": "output", "function": "IQ"},
                ("FF", "QN"): {"direction": "output", "function": "IQN"},
                ("INV", "A"): {"direction": "input", "function": None},
                ("INV", "Y"): {"direction": "output", "function": "!A"},
            }
        )
        with self.assertRaisesRegex((AssertionError, ValueError), "alias"):
            engine.ResetHierarchy(
                modules.__getitem__, set(modules), library, {"FF": {"ff": 1}}
            ).prove("top", {"child": ("rst_n", "p1")})


if __name__ == "__main__":
    unittest.main()
