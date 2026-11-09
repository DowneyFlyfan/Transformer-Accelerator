"""Reject jointly drifted candidate/baseline poses against an accepted inventory."""
from pathlib import Path
import hashlib
import importlib.util
import tempfile
import unittest


ROOT=Path(__file__).resolve().parents[1]
HELPER=Path(__file__).with_name('tri_oracle_accepted_macro104.py')


class AcceptedMacro104Tests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory(prefix='macro104_test_',dir=ROOT/'.cache/physical')
        self.addCleanup(self.folder.cleanup)
        self.directory=Path(self.folder.name)
        self.inventory=self.directory/'inventory.tsv'
        self.baseline=self.directory/'macros.tsv'
        rows=['instance\tmaster\tlocation\torientation\n'];macros=[]
        for c in range(5):
            prefix=f'fabric/clusters[{c}].unit/cluster/implementation/'
            for k in range(4):
                row=f'{prefix}cores[{k}]\ttri_oracle_sram_memory_compute\t{{{c*100}.0 {k*100}.0}}\tr0\n'
                rows.append(row);macros.append(row.rstrip()+'\tfixed\t3158\n')
            for k in range(8):
                row=f'{prefix}aggregate_memory[{k}]\tTS6N28HPCPSVTA16X128M2F\t{{{c*100+50}.0 {k*20}.0}}\tr0\n'
                rows.append(row);macros.append(row.rstrip()+'\tfixed\t268\n')
        self.inventory.write_text(''.join(rows));self.baseline.write_text(''.join(macros))
        self.digest=hashlib.sha256(''.join(sorted(rows)).encode()).hexdigest()

    def check(self):
        self.assertTrue(HELPER.is_file(),'Accepted-inventory macro checker is missing')
        spec=importlib.util.spec_from_file_location('macro104',HELPER)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module.require_accepted_macro_poses(self.inventory,self.digest,self.baseline,self.directory)

    def test_accepts_exact_all60_macro_poses(self):
        self.assertEqual(self.check()['accepted_macros'],60)

    def test_rejects_bank_pose_drift_even_when_candidate_and_sidecar_agree(self):
        text=self.baseline.read_text().replace('{50.0 0.0}','{51.0 0.0}')
        self.baseline.write_text(text)
        with self.assertRaisesRegex(AssertionError,'macro geometry'):self.check()

    def test_rejects_joint_inventory_and_sidecar_drift(self):
        for p in [self.baseline,self.inventory]:p.write_text(p.read_text().replace('{50.0 0.0}','{51.0 0.0}'))
        with self.assertRaisesRegex(AssertionError,'accepted inventory digest'):self.check()

    def test_rejects_missing_macro_and_changed_fixed_status(self):
        original=self.baseline.read_text();self.baseline.write_text(''.join(original.splitlines(keepends=True)[1:]))
        with self.assertRaisesRegex(AssertionError,'macro count'):self.check()
        self.baseline.write_text(original.replace('\tfixed\t268','\tplaced\t268',1))
        with self.assertRaisesRegex(AssertionError,'fixed interface'):self.check()


if __name__=='__main__':unittest.main()
