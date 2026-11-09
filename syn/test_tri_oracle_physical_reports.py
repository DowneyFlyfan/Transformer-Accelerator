"""Reject incomplete/incorrect closure evidence using real qualified reports.

Breaks caught: accepting absent reports, negative/rounded-negative slack,
wrong timing corner, unplaced cells, missing active routes, or wrong design.
"""
from pathlib import Path
import shutil
import tempfile
import unittest
from tri_oracle_physical_reports import validate_reports, ReportError, _timing

SOURCE=Path('.cache/physical/pnr/tri_oracle_tile_executor')
TOP='tri_oracle_tile_executor'

class PhysicalReportContract(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(prefix='physical_report_test_',dir='.cache/physical')
        self.folder=Path(self.temporary.name)
        for name in ['export_setup_slow.rpt','export_setup_typ.rpt','export_hold_fast.rpt','route_drc.rpt','route_connectivity.rpt','antenna.rpt','final_placement.rpt','extraction_audit.rpt']:
            shutil.copy2(SOURCE/name,self.folder/name)
    def tearDown(self):
        self.temporary.cleanup()
    def replace(self,name,old,new):
        p=self.folder/name
        text=p.read_text()
        self.assertIn(old,text)
        p.write_text(text.replace(old,new))
    def test_real_qualified_reports_and_harmless_empty_aliases(self):
        result=validate_reports(self.folder,TOP)
        self.assertEqual(result['timing_slack_ns'],{'setup_slow':.009,'setup_typ':.427,'hold_fast':.019})
        self.assertEqual(result['zero_connection_signal_aliases'],35)
        self.assertEqual(result['active_signal_nets_missing_routes'],0)
    def test_missing_report_rejected(self):
        (self.folder/'antenna.rpt').unlink()
        with self.assertRaises(ReportError):validate_reports(self.folder,TOP)
    def test_negative_hold_rejected(self):
        self.replace('export_hold_fast.rpt','MET (0.019 ns)','VIOLATED (-0.001 ns)')
        with self.assertRaises(ReportError):validate_reports(self.folder,TOP)
    def test_rounded_zero_violation_rejected(self):
        self.replace('export_hold_fast.rpt','MET (0.019 ns)','VIOLATED (-0.000 ns)')
        with self.assertRaises(ReportError):validate_reports(self.folder,TOP)
    def test_wrong_hold_view_rejected(self):
        self.replace('export_hold_fast.rpt','View: hold_fast','View: setup_slow')
        with self.assertRaises(ReportError):validate_reports(self.folder,TOP)
    def test_unplaced_cell_rejected(self):
        self.replace('final_placement.rpt','Unplaced = 0','Unplaced = 1')
        with self.assertRaises(ReportError):validate_reports(self.folder,TOP)
    def test_overlapping_placed_cells_rejected(self):
        # Exact diagnostic wording observed after the real feedback-cell ECO.
        p=self.folder/'final_placement.rpt'
        p.write_text('Overlapping with other instance:    31\n'+p.read_text())
        with self.assertRaises(ReportError):validate_reports(self.folder,TOP)
    def test_active_net_missing_route_rejected(self):
        self.replace('extraction_audit.rpt','Signal nets with multiple connections but no wire shapes: 0','Signal nets with multiple connections but no wire shapes: 1')
        with self.assertRaises(ReportError):validate_reports(self.folder,TOP)
    def test_wrong_design_rejected(self):
        self.replace('export_setup_slow.rpt','Design:            '+TOP,'Design:            tri_oracle_wrong')
        with self.assertRaises(ReportError):validate_reports(self.folder,TOP)
    def test_absent_timing_paths_rejected(self):
        p=self.folder/'export_setup_slow.rpt'
        p.write_text(p.read_text().split('Path 1:',1)[0]+'No constrained timing paths found\n')
        with self.assertRaises(ReportError):validate_reports(self.folder,TOP)
    def test_truncated_after_view_rejected(self):
        p=self.folder/'export_hold_fast.rpt'
        p.write_text(p.read_text().split('Group:',1)[0])
        with self.assertRaises(ReportError):validate_reports(self.folder,TOP)
    def test_trailing_incomplete_path_rejected(self):
        p=self.folder/'export_hold_fast.rpt'
        p.write_text(p.read_text()+'\nPath 2: VIOLATED (')
        with self.assertRaises(ReportError):validate_reports(self.folder,TOP)
    def test_negative_detailed_slack_rejected(self):
        self.replace('export_setup_slow.rpt','Slack:=    0.009','Slack:=    -0.001')
        with self.assertRaises(ReportError):validate_reports(self.folder,TOP)
    def test_unparsed_recovery_violation_rejected(self):
        p=self.folder/'export_hold_fast.rpt'
        p.write_text(p.read_text()+'\nPath 2: VIOLATED (-0.000 ns) Recovery Check\n               View: hold_fast\n')
        with self.assertRaises(ReportError):validate_reports(self.folder,TOP)
    def test_negative_zero_detailed_slack_rejected(self):
        self.replace('export_hold_fast.rpt','MET (0.019 ns)','MET (0.000 ns)')
        self.replace('export_hold_fast.rpt','Slack:=    0.019','Slack:=    -0.000')
        with self.assertRaises(ReportError):validate_reports(self.folder,TOP)
    def test_truncated_before_timing_rows_rejected(self):
        p=self.folder/'export_hold_fast.rpt'
        lines=p.read_text().splitlines(keepends=True)
        separators=0
        for index,line in enumerate(lines):
            if line.startswith('#---'):
                separators+=1
                if separators==2:break
        self.assertEqual(separators,2)
        p.write_text(''.join(lines[:index+1]))
        with self.assertRaises(ReportError):validate_reports(self.folder,TOP)
    def test_connectivity_problem_rejected(self):
        self.replace('route_connectivity.rpt','Found no problems or warnings.','Found 1 open net.')
        with self.assertRaises(ReportError):validate_reports(self.folder,TOP)

    def test_real_met_late_output_assertion_is_a_setup_path(self):
        # A valid constrained output-port path can dominate a native setup view.
        # Rejecting it would confuse a report type with failed timing closure.
        path=Path('.cache/physical/pnr/tri_oracle_feedforward_core/unfrozen_prects_setup_typ.rpt')
        result=_timing(path.read_text(),path.name,'setup_typ','Setup')
        self.assertEqual(result,.350240)

    def test_late_output_assertion_does_not_satisfy_hold(self):
        path=Path('.cache/physical/pnr/tri_oracle_feedforward_core/unfrozen_prects_setup_typ.rpt')
        with self.assertRaises(ReportError):
            _timing(path.read_text(),path.name,'setup_typ','Hold')

    def test_late_output_assertion_requires_output_delay_body(self):
        path=Path('.cache/physical/pnr/tri_oracle_feedforward_core/unfrozen_prects_setup_typ.rpt')
        text='\n'.join(line for line in path.read_text().splitlines() if 'Output Delay:' not in line)
        with self.assertRaises(ReportError):
            _timing(text,path.name,'setup_typ','Setup')

    def test_violated_late_output_assertion_is_rejected(self):
        path=Path('.cache/physical/pnr/tri_oracle_feedforward_core/unfrozen_prects_setup_typ.rpt')
        text=path.read_text().replace('MET (0.350240 ns)','VIOLATED (-0.000001 ns)')
        with self.assertRaises(ReportError):
            _timing(text,path.name,'setup_typ','Setup')



class ElectricalReportContract(unittest.TestCase):
    """Use the real cold reload that exposed the missed typical-corner row."""
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='electrical_report_test_', dir='.cache')
        self.folder = Path(self.temporary.name)
        self.source = Path('.cache/physical/pnr/tri_oracle_sram_memory_compute/qualification_cold_reload_54')
        self.rejected = Path('.cache/physical/pnr/tri_oracle_sram_memory_compute/qualification_cold_reload_41')
        for name in [
            'export_setup_slow.rpt', 'export_setup_typ.rpt', 'export_hold_fast.rpt',
            'route_drc.rpt', 'route_connectivity.rpt', 'antenna.rpt',
            'final_placement.rpt', 'extraction_audit.rpt',
            'electrical_violators_slow.rpt', 'electrical_violators_typ.rpt',
            'electrical_base_slow.rpt', 'electrical_base_typ.rpt', 'electrical_reporting_scope.rpt',
        ]:
            shutil.copy2(self.source / name, self.folder / name)
        shutil.copytree(self.source / 'qualification_si_reports', self.folder / 'qualification_si_reports')
    def tearDown(self):
        self.temporary.cleanup()
    def clean_typical_fixture(self):
        shutil.copy2(self.source / 'electrical_violators_typ.rpt',
                     self.folder / 'electrical_violators_typ.rpt')
    def test_real_negative_zero_typical_transition_is_rejected(self):
        shutil.copy2(self.rejected / 'electrical_violators_typ.rpt',
                     self.folder / 'electrical_violators_typ.rpt')
        with self.assertRaises(ReportError):
            validate_reports(self.folder, 'tri_oracle_sram_memory_compute')
    def test_clean_base_and_noisy_electrical_reports(self):
        self.clean_typical_fixture()
        result = validate_reports(self.folder, 'tri_oracle_sram_memory_compute')
        self.assertTrue(result['electrical_report_values_checked'])
        self.assertTrue(result['electrical_report_values_pass'])
    def test_missing_typical_report_is_rejected(self):
        (self.folder / 'electrical_violators_typ.rpt').unlink()
        with self.assertRaises(ReportError):
            validate_reports(self.folder, 'tri_oracle_sram_memory_compute')
    def test_missing_noisy_report_is_rejected(self):
        self.clean_typical_fixture()
        (self.folder / 'qualification_si_reports/qualification_si.tran.gz').unlink()
        with self.assertRaises(ReportError):
            validate_reports(self.folder, 'tri_oracle_sram_memory_compute')
    def test_contradictory_noisy_report_is_rejected(self):
        import gzip
        self.clean_typical_fixture()
        path = self.folder / 'qualification_si_reports/qualification_si.tran.gz'
        text = gzip.open(path, 'rt').read()
        with gzip.open(path, 'wt') as output:
            output.write(text + '\nnet/Q 0.3 0.4 -0.1\n')
        with self.assertRaises(ReportError):
            validate_reports(self.folder, 'tri_oracle_sram_memory_compute')
    def test_wrong_electrical_view_is_rejected(self):
        self.clean_typical_fixture()
        path = self.folder / 'electrical_violators_typ.rpt'
        path.write_text(path.read_text().replace('setup_typ', 'setup_slow'))
        with self.assertRaises(ReportError):
            validate_reports(self.folder, 'tri_oracle_sram_memory_compute')

    def test_explicit_request_rejects_absent_electrical_evidence(self):
        self.clean_typical_fixture()
        for path in self.folder.glob('electrical*'):
            path.unlink()
        shutil.rmtree(self.folder / 'qualification_si_reports')
        with self.assertRaises(ReportError):
            validate_reports(self.folder, 'tri_oracle_sram_memory_compute', require_electrical=True)
    def test_negative_base_transition_is_also_rejected(self):
        self.clean_typical_fixture()
        path = self.folder / 'electrical_base_typ.rpt'
        path.write_text((self.rejected / 'electrical_violators_typ.rpt').read_text())
        with self.assertRaises(ReportError):
            validate_reports(self.folder, 'tri_oracle_sram_memory_compute')
    def test_wrong_noisy_mode_is_rejected(self):
        self.clean_typical_fixture()
        path = self.folder / 'electrical_reporting_scope.rpt'
        path.write_text(path.read_text().replace('noisy_report_timing_max_transition_use_si_transition: true',
                                                'noisy_report_timing_max_transition_use_si_transition: false'))
        with self.assertRaises(ReportError):
            validate_reports(self.folder, 'tri_oracle_sram_memory_compute')

    def test_actual_stale_noisy_report_is_rejected(self):
        stale = Path('.cache/physical/pnr/tri_oracle_sram_memory_compute/qualification_cold_reload_50')
        shutil.copy2(stale / 'qualification_si_reports/qualification_si.tran.gz',
                     self.folder / 'qualification_si_reports/qualification_si.tran.gz')
        with self.assertRaises(ReportError):
            validate_reports(self.folder, 'tri_oracle_sram_memory_compute', require_electrical=True)

if __name__=='__main__':unittest.main()
