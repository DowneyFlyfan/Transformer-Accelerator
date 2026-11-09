"""Reject lost cores, moved macros and changed reset ancestry in the new parent."""
import csv
from pathlib import Path
import tempfile
import unittest

from tri_oracle_frame202_preservation import require_macro_poses, require_reset_topology, read_ready_prerequisite


class PreservationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix='frame202_controls_', dir=Path(__file__).resolve().parents[1]/'.cache/physical')
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.macros = []
        self.resets = []
        for cluster in range(5):
            for core in range(4):
                name = f'numeric/engine/backend/clusters[{cluster}].cluster/cores[{core}]'
                self.macros.append([name,'tri_oracle_sram_memory_compute',f'{core*800} {cluster*700}','r0','fixed'])
                self.resets.append([name+'/rst_n','2','numeric/reset_reg,child_rst_n_reg','DFF,DFF','clk,clk'])
            for bank in range(8):
                self.macros.append([f'numeric/engine/backend/clusters[{cluster}].cluster/aggregate_memory[{bank}]','TS6N28HPCPSVTA16X128M2F',f'{bank*40} {cluster*700}','r0','fixed'])
        self.resets.append(['prediction/engine/reg/CDN','1','child_rst_n_reg','DFF','clk'])

    def write(self, name, header, rows):
        path = self.root/name
        with path.open('w') as stream:
            writer = csv.writer(stream,delimiter='\t',lineterminator='\n');writer.writerow(header);writer.writerows(rows)
        return path

    def macro_check(self, rows):
        baseline = self.write('import.tsv',['instance','master','actual_location','orientation','status'],self.macros)
        before = self.write('before.tsv',['instance','master','location','orientation','status'],self.macros)
        after = self.write('after.tsv',['instance','master','location','orientation','status'],rows)
        return require_macro_poses(baseline,before,after)

    def test_all_sixty_macros_can_be_reordered(self):
        self.assertEqual(self.macro_check(list(reversed(self.macros)))['preserved_macros'],60)

    def test_missing_duplicate_renamed_and_moved_macros_rejected(self):
        for kind in ['missing','duplicate','renamed','moved','master','orientation','status']:
            with self.subTest(kind=kind):
                rows=[row[:] for row in self.macros]
                if kind=='missing':rows.pop()
                elif kind=='duplicate':rows[-1]=rows[0][:]
                elif kind=='renamed':rows[0][0]=rows[0][0].replace('numeric/engine/backend','wrong')
                elif kind=='moved':rows[0][2]='1 0'
                elif kind=='master':rows[0][1]='WRONG_CELL'
                elif kind=='orientation':rows[0][3]='r180'
                else:rows[0][4]='placed'
                with self.assertRaises((ValueError,AssertionError)):self.macro_check(rows)

    def reset_check(self,rows):
        header=['endpoint','registered_depth','registered_sources','masters','clock_nets']
        return require_reset_topology(self.write('reset_import.tsv',header,self.resets),self.write('reset_after.tsv',header,rows))

    def test_complete_reset_topology_accepts_row_reorder(self):
        self.assertEqual(self.reset_check(list(reversed(self.resets)))['core_reset_endpoints'],20)

    def test_lost_endpoint_and_changed_reset_chains_rejected(self):
        for kind in ['missing','duplicate','source','master','clock','unknown_endpoint']:
            with self.subTest(kind=kind):
                rows=[row[:] for row in self.resets]
                if kind=='missing':rows.pop()
                elif kind=='duplicate':rows.append(rows[0][:])
                elif kind=='source':rows[0][2]='other_reg,child_rst_n_reg'
                elif kind=='master':rows[0][3]='OTHER,DFF'
                elif kind=='clock':rows[0][4]='other_clk,clk'
                else:rows[0][0]='unknown/core/rst_n'
                with self.assertRaises((ValueError,AssertionError)):self.reset_check(rows)

    def test_terminal_cleanup_update_wins_process_exit_race(self):
        pending=dict(state='passed',temporary_build_removed=False,supervisor_pid=17)
        complete=dict(pending,temporary_build_removed=True)
        for identity in [None,('Z',1),('S',2)]:
            with self.subTest(identity=identity):
                reads=iter([pending,complete])
                actual=read_ready_prerequisite(lambda:next(reads),lambda pid:identity,{'mapped208_full':1},'mapped208_full','passed')
                self.assertEqual(actual,complete)

    def test_lost_or_replaced_pending_owner_still_rejected(self):
        pending=dict(state='running',temporary_build_removed=False,supervisor_pid=17)
        for identity in [None,('Z',1),('S',2)]:
            with self.subTest(identity=identity):
                with self.assertRaises(ValueError):
                    read_ready_prerequisite(lambda:pending,lambda pid:identity,{'mapped208_full':1},'mapped208_full','passed')


if __name__=='__main__':unittest.main()
