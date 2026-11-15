"""Paper-derived acceptance must fail closed before the next physical phase."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from check_tri_oracle_paper300_gate import (
    CONCURRENT_IMPORT, LEGACY_QUALIFICATION, REPEATER_PLACEMENT, placement_checks, qualification_source,
)
from verify_tri_oracle_repeater_placement_evidence import compiled_memory_inventory

class PaperPlacementGateTests(unittest.TestCase):
    def test_placed_memory_matches_netlist_instance_and_master(self):
        verilog = """module chip (clk);
  tri_oracle_bank \\banks[0].unit  (.clk(clk));
endmodule
module tri_oracle_bank (clk);
  TS5N28_EXAMPLE \\entries[0]  (.CLK(clk));
endmodule
"""
        definition = """COMPONENTS 1 ;
- banks[0].unit/entries[0] TS5N28_EXAMPLE + FIXED ( 0 0 ) N ;
END COMPONENTS
"""
        with TemporaryDirectory(dir=".cache") as directory:
            netlist = Path(directory) / "placed.v"
            placement = Path(directory) / "placed.def"
            netlist.write_text(verilog)
            placement.write_text(definition)
            _, macros = compiled_memory_inventory(netlist, placement, top="chip")
            self.assertEqual(macros, {"banks[0].unit.entries[0]": "TS5N28_EXAMPLE"})

            placement.write_text(definition.replace("entries[0]", "entries[1]"))
            with self.assertRaisesRegex(ValueError, "netlist and placement"):
                compiled_memory_inventory(netlist, placement, top="chip")

    def test_current_candidate_selected_while_receipt_is_pending(self):
        with TemporaryDirectory(dir=".cache") as directory:
            root = Path(directory).resolve()
            older = root / "previous.json"
            older.touch()
            self.assertEqual(qualification_source(root, None, older), older)
            current = root / CONCURRENT_IMPORT
            current.mkdir(parents=True)
            self.assertEqual(qualification_source(root, None, older), current / "receipt.json")
            legacy = root / LEGACY_QUALIFICATION
            self.assertEqual(qualification_source(root, legacy, older), legacy)

    def test_repeater_record_takes_precedence_over_older_concurrent_import(self):
        with TemporaryDirectory(dir=".cache") as directory:
            root = Path(directory).resolve()
            older = root / CONCURRENT_IMPORT / "receipt.json"
            older.parent.mkdir(parents=True)
            older.touch()
            latest = root / REPEATER_PLACEMENT
            latest.parent.mkdir()
            latest.touch()
            self.assertEqual(qualification_source(root, None), latest)
            self.assertEqual(qualification_source(root, older), older)

    def test_scalar_cold_placement_supersedes_the_repeater_by_default(self):
        with TemporaryDirectory(dir=".cache") as directory:
            root = Path(directory).resolve()
            repeater = root / REPEATER_PLACEMENT
            repeater.parent.mkdir()
            repeater.touch()
            scalar = repeater.with_name("tri_oracle_scalar_whole_chip_cold_reload.json")
            scalar.touch()
            self.assertEqual(qualification_source(root, None), scalar)
            self.assertEqual(qualification_source(root, repeater), repeater)

    def test_guarded_cold_placement_supersedes_the_original_scalar_by_default(self):
        with TemporaryDirectory(dir=".cache") as directory:
            root = Path(directory).resolve()
            scalar = root / "records/tri_oracle_scalar_whole_chip_cold_reload.json"
            scalar.parent.mkdir()
            scalar.touch()
            guarded = scalar.with_name("tri_oracle_guarded_scalar_whole_chip_cold_reload.json")
            guarded.touch()
            self.assertEqual(qualification_source(root, None), guarded)
            self.assertEqual(qualification_source(root, scalar), scalar)

    def test_buffered_grant_cold_placement_supersedes_guarded_scalar_by_default(self):
        with TemporaryDirectory(dir=".cache") as directory:
            root = Path(directory).resolve()
            guarded = root / "records/tri_oracle_guarded_scalar_whole_chip_cold_reload.json"
            guarded.parent.mkdir()
            guarded.touch()
            buffered = guarded.with_name("tri_oracle_buffered_grant_whole_chip_cold_reload.json")
            buffered.touch()
            self.assertEqual(qualification_source(root, None), buffered)
            self.assertEqual(qualification_source(root, guarded), guarded)

    def test_reduced_port_placement_supersedes_buffered_grant_by_default(self):
        with TemporaryDirectory(dir=".cache") as directory:
            root = Path(directory).resolve()
            buffered = root / "records/tri_oracle_buffered_grant_whole_chip_cold_reload.json"
            buffered.parent.mkdir()
            buffered.touch()
            reduced = buffered.with_name("tri_oracle_reduced_port_placement_and_reload.json")
            reduced.touch()
            self.assertEqual(qualification_source(root, None), reduced)
            self.assertEqual(qualification_source(root, buffered), buffered)

    def complete(self):
        return dict(candidate_cold_qualified=True,native_workers_terminal=True,
            original_full_models_verified=True,clusters=5,cores=20,
            array_instances=20,array_geometry=[32,8],operand_bits=8,
            die_width_mm=3.6,die_height_mm=3.6,clock_period_ns=1.72414,
            corner_slack_ns={"setup_slow":0.02,"setup_typ":0.24,"hold_fast":0.005},
            high_fanout_substitution_disabled=True,
            complete_paper_architecture_verified=True,memory_capacity_reconciled=True,
            trained_mapped_layer_verified=True,paper_accuracy_protocol_verified=True)

    def test_boolean_metadata_cannot_certify_unimplemented_verification_flows(self):
        checks=placement_checks(self.complete())
        for key in ["complete_paper_architecture_verified","memory_capacity_reconciled",
                    "trained_mapped_layer_verified","paper_accuracy_protocol_verified"]:
            with self.subTest(requirement=key):
                self.assertFalse(checks[key])
        self.assertFalse(all(checks.values()))

    def test_complete_supported_physical_metrics_pass_but_hold_is_preserved(self):
        checks=placement_checks(self.complete())
        held={"complete_paper_architecture_verified","memory_capacity_reconciled",
              "trained_mapped_layer_verified","paper_accuracy_protocol_verified"}
        self.assertTrue(all(value for key,value in checks.items() if key not in held))
        self.assertFalse(all(checks.values()))

    def test_counts_and_floorplan_alone_never_admit_next_phase(self):
        facts=dict(clusters=5,cores=20,die_width_mm=3.6,die_height_mm=3.6)
        self.assertFalse(all(placement_checks(facts).values()))

    def test_any_negative_corner_rejects_even_subpicosecond_deficit(self):
        for view in ["setup_slow","setup_typ","hold_fast"]:
            facts=self.complete()
            facts["corner_slack_ns"][view]=-0.000001
            with self.subTest(view=view):
                self.assertFalse(placement_checks(facts)["all_three_original_corner_slacks_nonnegative"])

    def test_skipped_detailed_analysis_rejects_positive_slack(self):
        facts = self.complete()
        facts["detailed_analysis_skipped_nets"] = {"setup_slow": ["test_net"]}
        self.assertFalse(placement_checks(facts)["all_three_original_corner_slacks_nonnegative"])

    def test_missing_or_extra_corner_rejected(self):
        for operation in ["missing","extra"]:
            facts=self.complete()
            if operation=="missing": del facts["corner_slack_ns"]["hold_fast"]
            else: facts["corner_slack_ns"]["unrelated"]=1
            with self.subTest(operation=operation):
                self.assertFalse(placement_checks(facts)["all_three_original_corner_slacks_nonnegative"])

    def test_nan_or_infinite_slack_rejected(self):
        for value in [float("nan"),float("inf"),float("-inf")]:
            facts=self.complete();facts["corner_slack_ns"]["setup_slow"]=value
            self.assertFalse(placement_checks(facts)["all_three_original_corner_slacks_nonnegative"])

    def test_relaxed_clock_rejected(self):
        facts=self.complete();facts["clock_period_ns"]=2.0
        self.assertFalse(placement_checks(facts)["paper_580_megahertz_period"])

    def test_changed_die_or_core_scale_rejected(self):
        for key,value,check in [("die_width_mm",4.0,"paper_3_6_millimeter_die"),
                                ("die_height_mm",4.0,"paper_3_6_millimeter_die"),
                                ("cores",19,"paper_five_clusters_twenty_cores"),
                                ("clusters",4,"paper_five_clusters_twenty_cores")]:
            facts=self.complete();facts[key]=value
            with self.subTest(key=key):
                self.assertFalse(placement_checks(facts)[check])

    def test_array_geometry_must_match_alongside_core_count(self):
        self.assertTrue(placement_checks(self.complete())["paper_compute_array_geometry"])
        for key, value in (("array_instances", 19), ("array_geometry", [8, 32]), ("operand_bits", 16)):
            facts = self.complete()
            facts[key] = value
            with self.subTest(key=key):
                self.assertTrue(placement_checks(facts)["paper_five_clusters_twenty_cores"])
                self.assertFalse(placement_checks(facts)["paper_compute_array_geometry"])

    def test_all_required_qualifications_fail_when_missing_or_not_exact_true(self):
        fields=["candidate_cold_qualified","native_workers_terminal","original_full_models_verified",
                "high_fanout_substitution_disabled","complete_paper_architecture_verified",
                "memory_capacity_reconciled","trained_mapped_layer_verified","paper_accuracy_protocol_verified"]
        for field in fields:
            for value in [None,False,"true",1]:
                facts=self.complete();facts[field]=value
                with self.subTest(field=field,value=value):
                    self.assertFalse(placement_checks(facts)[field])
            facts=self.complete();del facts[field]
            self.assertFalse(placement_checks(facts)[field])

if __name__=="__main__":
    unittest.main()
