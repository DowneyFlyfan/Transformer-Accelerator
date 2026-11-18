"""Ownership relation and physical enabled-register semantics use literal cases."""
from pathlib import Path
import sys,unittest,z3
sys.path.insert(0,str(Path(__file__).resolve().parent))

class LayerRowEpochTest(unittest.TestCase):
    def test_control_frame_and_row_epochs_keep_distinct_owners(self):
        from prove_tri_oracle_layer_row_epoch import ownership_invariant
        for layer,row,wanted in ((0,0,True),(5,0,True),(5,7,False),(0,1,False),
            (9,1,True),(3,2,True),(4,2,False),(7,16,True),(7,1,False),(7,31,True),(12,0,False)):
            value=ownership_invariant(z3.BitVecVal(layer,4),z3.BitVecVal(row,5))
            self.assertEqual(z3.is_true(z3.simplify(value)),wanted)

    def test_domain_has51_pairs_and_forbids_active_row_during_head_prediction(self):
        from prove_tri_oracle_layer_row_epoch import ownership_invariant
        accepted=[]
        for layer in range(16):
            for row in range(32):
                if z3.is_true(z3.simplify(ownership_invariant(z3.BitVecVal(layer,4),z3.BitVecVal(row,5)))):
                    accepted.append((layer,row))
        self.assertEqual(len(accepted),51)
        self.assertEqual([row for layer,row in accepted if layer==5],[0])

    def fixture(self,clock='clk',preset=False):
        from prove_tri_oracle_command_admission import AdmissionRoutes
        from prove_tri_oracle_head_intensity import WordBridge
        body=(f'module m(clk, rst_n, d, e, state);\ninput clk, rst_n, d, e;\noutput [0:0] state;\n'
              f'F storage (.CP({clock}),.CDN(rst_n),.D(d),.E(e),.Q(state[0]));\nendmodule\n').encode()
        library={("F",name):{'direction':'input'} for name in ('CP','CDN','D','E')}
        library['F','Q']={'direction':'output','function':'IQ'}
        route=AdmissionRoutes(lambda _:body,{'m'},library,{'F':{'ff':1}},'m')
        primary={'F':{'clocked_on':'CP','next_state':'(D & E) | (!E & IQ)',
                      'preset' if preset else 'clear':'!CDN'}}
        return route,WordBridge(route.graph),primary

    def test_actual_enable_holds_or_captures_the_same_physical_bit(self):
        from prove_tri_oracle_layer_row_epoch import physical_register
        route,bridge,primary=self.fixture()
        record=physical_register(route,bridge,'','storage',primary)
        wanted=z3.If(bridge.boolean('top.e'),bridge.boolean('top.d'),record['old'])
        solver=z3.Solver();solver.add(record['data']!=wanted)
        self.assertEqual(solver.check(),z3.unsat)

    def test_actual_primary_reset_polarity_and_value_are_preserved(self):
        from prove_tri_oracle_layer_row_epoch import physical_register
        for preset in (False,True):
            route,bridge,primary=self.fixture(preset=preset)
            record=physical_register(route,bridge,'','storage',primary)
            solver=z3.Solver();solver.add(record['reset']!=z3.Not(bridge.boolean('top.rst_n')))
            self.assertEqual(solver.check(),z3.unsat)
            self.assertEqual(record['reset_value'],int(preset))

    def test_wrong_register_clock_is_rejected(self):
        from prove_tri_oracle_layer_row_epoch import physical_register
        route,bridge,primary=self.fixture(clock="1'b0")
        with self.assertRaisesRegex(AssertionError,'clock'):
            physical_register(route,bridge,'','storage',primary)

if __name__=='__main__':unittest.main()
