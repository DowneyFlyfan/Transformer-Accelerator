"""Reject weakened reset topologies and altered accepted core inventories."""
import csv
import hashlib
import io
from pathlib import Path
import tempfile
import unittest

from tri_oracle_parent_candidate_acceptance import (
    require_reset_topology, require_snapshot_binding,
)

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT/'.cache/physical/pnr/tri_oracle_predicted_fabric_registered_reset30/placement79/registered_reset_roots.tsv'


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.text = BASELINE.read_text()
        stream = csv.DictReader(io.StringIO(self.text),delimiter='\t')
        self.fields,self.rows = stream.fieldnames,list(stream)
        self.temp = tempfile.TemporaryDirectory(prefix='parent_acceptance_',dir=ROOT/'.cache/physical')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def candidate(self, rows):
        path = self.directory/'candidate.tsv'
        with path.open('w') as stream:
            writer=csv.DictWriter(stream,fieldnames=self.fields,delimiter='\t',lineterminator='\n')
            writer.writeheader();writer.writerows(rows)
        return path

    def test_native_baseline_and_reordering(self):
        value=require_reset_topology(BASELINE,self.candidate(list(reversed(self.rows))))
        self.assertEqual(value['core_endpoints'],20)
        self.assertEqual(value['prediction_endpoints'],961)

    def test_core_chain_cannot_be_shortened_while_min_max_remain(self):
        self.rows[0].update(registered_depth='1',registered_sources='child_rst_n_reg',
                            masters='DFCNQD1BWP12T40P140',clock_nets='clk')
        with self.assertRaisesRegex(ValueError,'topology changed'):
            require_reset_topology(BASELINE,self.candidate(self.rows))

    def test_wrong_registered_root(self):
        self.rows[0]['registered_sources']='another_root,child_rst_n_reg'
        with self.assertRaisesRegex(ValueError,'topology changed'):
            require_reset_topology(BASELINE,self.candidate(self.rows))

    def test_clock_chain_changed(self):
        self.rows[0]['clock_nets']='other_clk,clk'
        with self.assertRaisesRegex(ValueError,'topology changed'):
            require_reset_topology(BASELINE,self.candidate(self.rows))

    def test_registered_master_changed_requires_review(self):
        self.rows[0]['masters']='DFCNQD4BWP12T40P140,DFCNQD1BWP12T40P140'
        with self.assertRaisesRegex(ValueError,'topology changed'):
            require_reset_topology(BASELINE,self.candidate(self.rows))

    def test_missing_prediction_endpoint(self):
        with self.assertRaisesRegex(ValueError,'endpoint set'):
            require_reset_topology(BASELINE,self.candidate(self.rows[:-1]))

    def test_duplicate_endpoint(self):
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            require_reset_topology(BASELINE,self.candidate(self.rows+[self.rows[0]]))

    def test_prediction_chain_cannot_be_lengthened(self):
        row=next(r for r in self.rows if r['endpoint'].startswith('prediction/'))
        row.update(registered_depth='2',registered_sources='fabric/child_rst_n_reg,child_rst_n_reg',
                   masters='DFCNQD1BWP12T40P140,DFCNQD1BWP12T40P140',clock_nets='clk,clk')
        with self.assertRaisesRegex(ValueError,'topology changed'):
            require_reset_topology(BASELINE,self.candidate(self.rows))

    def test_inventory_content_is_bound_to_accepted_digest(self):
        path=self.directory/'core_after.tsv';path.write_text('accepted native inventory\n')
        expected=hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(require_snapshot_binding(path,{str(path):expected}),expected)
        path.write_text('different native inventory\n')
        with self.assertRaisesRegex(ValueError,'snapshot digest'):
            require_snapshot_binding(path,{str(path):expected})

    def test_missing_inventory_binding_rejected(self):
        path=self.directory/'core_after.tsv';path.write_text('inventory\n')
        with self.assertRaisesRegex(ValueError,'Missing accepted'):
            require_snapshot_binding(path,{})


if __name__=='__main__':
    unittest.main()
