"""Accepted head commands must retain controller mode until termination."""
from pathlib import Path
import sys,unittest,z3
sys.path.insert(0,str(Path(__file__).resolve().parent))


class HeadCommandEpochTest(unittest.TestCase):
    def test_active_tile_requires_parent_wait_and_excludes_invalid_parent_states(self):
        from prove_tri_oracle_head_command_epoch import parent_tile_invariant
        for parent,tile,wanted in ((0,0,True),(2,0,True),(3,7,True),(4,0,True),
                                   (2,3,False),(4,3,False),(7,0,False)):
            got=parent_tile_invariant(z3.BitVecVal(parent,3),z3.BitVecVal(tile,3))
            self.assertEqual(z3.is_true(z3.simplify(got)),wanted)
        count=sum(z3.is_true(z3.simplify(parent_tile_invariant(z3.BitVecVal(p,3),z3.BitVecVal(t,3))))
                  for p in range(8) for t in range(8))
        self.assertEqual(count,13)

    def test_head_epoch_rejects_last_emit_or_lost_owner(self):
        from prove_tri_oracle_head_command_epoch import head_invariant
        cases=[(True,5,3,3,True,True,True),(True,5,3,4,True,False,True),
               (True,5,3,4,True,True,False),(True,5,3,5,False,True,False),
               (True,6,3,3,True,False,False),(True,5,3,0,True,False,False),
               (False,0,0,0,False,True,True)]
        for history,layer,parent,tile,owned,last,wanted in cases:
            got=head_invariant(z3.BoolVal(history),z3.BitVecVal(layer,4),z3.BitVecVal(parent,3),
                z3.BitVecVal(tile,3),z3.BoolVal(owned),z3.BoolVal(last))
            self.assertEqual(z3.is_true(z3.simplify(got)),wanted)

    def test_history_acquisition_has_priority_and_idle_edges_hold(self):
        from prove_tri_oracle_head_command_epoch import next_history
        for old,accept,terminal,wanted in ((False,True,False,True),(True,False,False,True),
                (True,False,True,False),(False,False,False,False),(False,True,True,True)):
            got=next_history(*(z3.BoolVal(x) for x in (old,accept,terminal)))
            self.assertEqual(z3.is_true(z3.simplify(got)),wanted)

    def test_saved_tag_uses_physical_q_alias_when_cfg_port_is_undriven(self):
        from prove_tri_oracle_head_command_epoch import current_register_word
        from prove_tri_oracle_command_admission import AdmissionRoutes
        from prove_tri_oracle_head_intensity import WordBridge
        from prove_tri_oracle_tile_command_routes import route_word
        body=b'''module tile(clk, batch_tag, tensor_cfg_tag, score_tag);
input clk;
input [1:0] batch_tag;
output [1:0] tensor_cfg_tag;
output [1:0] score_tag;
DFF \\tensor_cfg_tag_reg[0]  (.CP(clk), .D(batch_tag[0]), .Q(score_tag[0]));
DFF \\tensor_cfg_tag_reg[1]  (.CP(clk), .D(batch_tag[1]), .Q(score_tag[1]));
endmodule'''
        library={('DFF',name):dict(direction=direction,**extra) for name,direction,extra in (
            ('Q','output',dict(function='IQ')),('D','input',{}),('CP','input',{}))}
        routes=AdmissionRoutes(lambda master:body,{'tile'},library,{'DFF':{'ff':1}},'tile',tile='',parent='')
        bridge=WordBridge(routes.graph)
        actual=current_register_word(routes,bridge,'','tensor_cfg_tag',2)
        wanted=route_word(routes,bridge,'','score_tag',2,direction='output')
        self.assertEqual(z3.simplify(actual==wanted),z3.BoolVal(True))
        with self.assertRaisesRegex(AssertionError,'Expected one command route driver'):
            route_word(routes,bridge,'','tensor_cfg_tag',2,direction='output')


if __name__=='__main__':unittest.main()
