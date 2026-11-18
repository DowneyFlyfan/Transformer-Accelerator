"""Check parent clock identity using independently understandable netlists."""

import importlib.util
from pathlib import Path
import unittest
import tempfile

from prove_tri_oracle_parent_reset import ResetHierarchy

SOURCE = Path(__file__).with_name("prove_tri_oracle_parent_clock.py")


class ParentClockTests(unittest.TestCase):
    def engine(self):
        self.assertTrue(SOURCE.exists(), "Parent clock proof is not implemented")
        spec = importlib.util.spec_from_file_location("clock_proof", SOURCE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def fixture(self, connection=b"clk", extra=b"", leaf_extra=b""):
        modules = {
            "top": b"module top(clk,enable); input clk,enable; "
            + extra
            + b"leaf child(.clk("
            + connection
            + b")); endmodule",
            "leaf": b"module leaf(clk); input clk; " + leaf_extra + b"endmodule",
        }
        library = {
            ("BUF", "A"): {"direction": "input", "function": None},
            ("BUF", "Y"): {"direction": "output", "function": "A"},
            ("INV", "A"): {"direction": "input", "function": None},
            ("INV", "Y"): {"direction": "output", "function": "!A"},
            ("AND", "A"): {"direction": "input", "function": None},
            ("AND", "B"): {"direction": "input", "function": None},
            ("AND", "Y"): {"direction": "output", "function": "A & B"},
            ("RAM", "CLK"): {"direction": "input", "function": None},
            ("RAM", "Q"): {"direction": "output", "function": None},
        }
        return ResetHierarchy(modules.__getitem__, set(modules), library, {})

    def test_direct_and_buffered_clock_preserve_both_levels(self):
        for connection, extra in [
            (b"clk", b""),
            (b"x", b"wire x; BUF b(.A(clk),.Y(x));"),
            (b"x", b"wire x; assign x=clk;"),
        ]:
            with self.subTest(connection=connection, extra=extra):
                result = self.engine().prove(
                    self.fixture(connection, extra), "top", ["child"]
                )
                self.assertEqual(result["array_count"], 1)
                self.assertEqual(result["integer_assignments"], 2)
                self.assertTrue(result["all_array_clocks_equal_top_clock"])

    def test_stuck_or_inverted_clock_is_rejected(self):
        for connection, extra in [
            (b"1'b0", b""),
            (b"1'b1", b""),
            (b"x", b"wire x; INV b(.A(clk),.Y(x));"),
        ]:
            with self.subTest(connection=connection):
                with self.assertRaisesRegex(
                    (AssertionError, ValueError), "clock identity"
                ):
                    self.engine().prove(
                        self.fixture(connection, extra), "top", ["child"]
                    )

    def test_independently_gated_clock_is_not_accepted_as_identity(self):
        checker = self.fixture(b"x", b"wire x; AND b(.A(clk),.B(enable),.Y(x));")
        with self.assertRaisesRegex((AssertionError, ValueError), "clock identity"):
            self.engine().prove(checker, "top", ["child"])

    def test_memory_clock_load_is_allowed_but_memory_output_drive_is_rejected(self):
        checker = self.fixture(leaf_extra=b"wire q; RAM memory(.CLK(clk),.Q(q));")
        self.assertTrue(
            self.engine().prove(checker, "top", ["child"])[
                "all_array_clocks_equal_top_clock"
            ]
        )
        with self.assertRaisesRegex((AssertionError, ValueError), "internal driver"):
            self.engine().prove(
                self.fixture(leaf_extra=b"RAM memory(.CLK(clk),.Q(clk));"),
                "top",
                ["child"],
            )

    def test_unknown_load_pin_cannot_silently_pass(self):
        with self.assertRaisesRegex(
            (AssertionError, ValueError), "Unknown library pin"
        ):
            self.engine().prove(
                self.fixture(leaf_extra=b"UNKNOWN load(.P(clk));"), "top", ["child"]
            )

    def test_multiple_drivers_and_hidden_statements_are_rejected(self):
        for extra in [b"assign clk=enable;", b"always @* clk=enable;"]:
            with (
                self.subTest(extra=extra),
                self.assertRaises((AssertionError, ValueError)),
            ):
                self.engine().prove(self.fixture(extra=extra), "top", ["child"])

    def test_duplicate_or_missing_targets_are_rejected(self):
        for paths in [[], ["child", "child"], ["missing"]]:
            with (
                self.subTest(paths=paths),
                self.assertRaises((AssertionError, ValueError, KeyError)),
            ):
                self.engine().prove(self.fixture(), "top", paths)

    def test_actual_binding_mutations_are_rejected_without_changing_source(self):
        checker = self.fixture()
        before = checker.body("top")
        engine = self.engine()
        engine.prove(checker, "top", ["child"])
        mutations = engine.mutations(checker, "top", ["child"])
        self.assertEqual(len(mutations), 2)
        self.assertEqual({row["stuck_value"] for row in mutations}, {0, 1})
        self.assertEqual(checker.body("top"), before)

    def test_spaced_compiler_library_names_bind_clock_input(self):
        engine = self.engine()
        self.assertTrue(callable(getattr(engine, "read_clock_library", None)))
        with tempfile.TemporaryDirectory(dir=Path.cwd() / ".cache") as folder:
            path = Path(folder) / "memory.lib"
            path.write_text(
                "capacitive_load_unit (1,pf);\ncell ( RAM ) {\n    pin ( CLK ) {\n        direction : input;\n    }\n}\n"
            )
            self.assertEqual(
                engine.read_clock_library(path, {"RAM"})["RAM", "CLK"]["direction"],
                "input",
            )

    def test_captured_parent_body_must_match_qualified_manifest(self):
        engine = self.engine()
        self.assertTrue(callable(getattr(engine, "bind_parents", None)))
        checker = self.fixture()
        result = engine.prove(checker, "top", ["child"])
        trusted = result["parent_module_sha256"].copy()
        engine.bind_parents(result, trusted)
        trusted["top"] = "0" * 64
        with self.assertRaisesRegex((AssertionError, ValueError), "parent body"):
            engine.bind_parents(result, trusted)

    def test_candidate_capture_is_immutable_and_hash_bound(self):
        engine = self.engine()
        self.assertTrue(callable(getattr(engine, "capture_candidate", None)))
        expected = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        with tempfile.TemporaryDirectory(dir=Path.cwd() / ".cache") as folder:
            path = Path(folder) / "candidate.v"
            path.write_bytes(b"abc")
            captured = engine.capture_candidate(path, expected)
            path.write_bytes(b"abd")
            self.assertEqual(captured, b"abc")
            with self.assertRaisesRegex(
                (AssertionError, ValueError), "candidate snapshot"
            ):
                engine.capture_candidate(path, expected)


if __name__ == "__main__":
    unittest.main()
