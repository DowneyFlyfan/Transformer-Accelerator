"""Check unreset mux flip-flops and strict score-packet verification guards."""
from pathlib import Path
import importlib.util
import subprocess
import sys
import unittest

SOURCE=Path(__file__).with_name('prove_tri_oracle_tile_score_packet.py')


class TileScorePacketTests(unittest.TestCase):
    def engine(self):
        self.assertTrue(SOURCE.exists(),'Tile score packet verifier is missing')
        spec=importlib.util.spec_from_file_location('tile_score_packet',SOURCE)
        engine=importlib.util.module_from_spec(spec);spec.loader.exec_module(engine)
        return engine

    def test_primary_mux_model_preserves_no_reset_semantics(self):
        engine=self.engine()
        primary=engine.primary_tile_state('ff (IQ, IQN) {clocked_on : "CP"; next_state : "((SA DA)+(!SA DB))";}')
        self.assertEqual(set(primary),{'clocked_on','next_state'})
        for description in ['ff (IQ,IQN) {clocked_on:"CP";next_state:"D";clear:"!CDN";preset:"!SDN";}',
                            'ff (OTHER,IQN) {clocked_on:"CP";next_state:"D";}']:
            with self.assertRaises(AssertionError):engine.primary_tile_state(description)

    def test_actual_mux_transition_uses_library_select_and_clock(self):
        engine=self.engine()
        import z3
        library={('MUXFF',name):{'direction':'input'} for name in ['CP','DA','DB','SA']}
        library['MUXFF','Q']={'direction':'output','function':'IQ'}
        library['MUXFF','__tile_ff__']={'clocked_on':'CP','next_state':'((SA DA)+(!SA DB))'}
        body=b'module tile(clk,rst_n,a,b,s,q); input clk,rst_n,a,b,s; output q; MUXFF reg0(.CP(clk),.DA(a),.DB(b),.SA(s),.Q(q)); endmodule'
        model=engine.TileCone(body,library,{'MUXFF':{'ff':1}})
        data,reset,value=model.transition('reg0','q')
        self.assertIsNone(reset);self.assertIsNone(value)
        bridge=engine.WordBridge(model.graph)
        bridge.check(bridge.convert([data]),[z3.If(bridge.boolean('s'),bridge.boolean('a'),bridge.boolean('b'))],label='mux_equation')
        altered=body.replace(b'.CP(clk)',b'.CP(a)')
        with self.assertRaisesRegex(AssertionError,'clock'):
            engine.TileCone(altered,library,{'MUXFF':{'ff':1}}).transition('reg0','q')

    def test_optimized_python_cannot_disable_checks(self):
        self.engine()
        result=subprocess.run([sys.executable,'-O','-B','-c','import sys;sys.path.insert(0,"syn");import prove_tri_oracle_tile_score_packet'],
            cwd=SOURCE.parent.parent,capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0);self.assertIn('requires Python assertions',result.stderr)

    def test_completion_priority_blocks_capture_and_certifies_last_row(self):
        engine=self.engine()
        self.assertTrue(hasattr(engine,'packet_expressions'),'Independent packet specification is missing')
        import z3
        bridge=engine.WordBridge(None)
        old={name:bridge.word(name,width) for name,width in [('state',3),('key_index',7),('token_index',4),
             ('score_beat',4),('tag',32),('tokens',5),('saved_scores',3072),('row_limits',18)]}
        old.update(extra_packet=bridge.boolean('extra_packet'),last_batch=bridge.boolean('last_batch'))
        expected=engine.packet_expressions(bridge,old)
        fixed=[old['state']==3,old['tag']==17,old['tokens']==1,old['token_index']==0,
               bridge.word('tensor_out_tag',32)==17,bridge.word('tensor_out_token',4)==0,
               bridge.word('tensor_out_count',8)==96,bridge.boolean('tensor_out_last'),bridge.boolean('tensor_out_valid')]
        for done,capture,want_state in [(False,True,5),(True,False,7)]:
            solver=z3.Solver();solver.add(*fixed,bridge.boolean('tensor_done_valid')==done)
            self.assertEqual(solver.check(),z3.sat);model=solver.model()
            self.assertEqual(z3.is_true(model.eval(expected['capture'])),capture)
            self.assertEqual(model.eval(expected['next_state'][3]).as_long(),want_state)

    def test_buffer_initialization_invariant_excludes_uncaptured_normal_emit(self):
        engine=self.engine()
        self.assertTrue(hasattr(engine,'packet_safety'),'Capture safety invariant is missing')
        result=engine.packet_safety()
        self.assertTrue(result['ordinary_emit_requires_capture'])
        self.assertTrue(result['normal_emit_beat_bound_verified'])

    def test_report_outside_cache_is_rejected(self):
        engine=self.engine()
        self.assertTrue(hasattr(engine,'verify'),'Candidate-bound tile verifier is missing')
        with self.assertRaises(AssertionError):engine.verify(SOURCE.parent/'forbidden-report.json')

    def test_undriven_alias_is_excluded_only_when_parent_does_not_consume_it(self):
        engine=self.engine()
        self.assertTrue(hasattr(engine,'unused_output_alias'),'Unused alias qualification is missing')
        from prove_tri_oracle_parent_reset import Module
        tile=b'module tile(clk,rst_n,ready,alias); input clk,rst_n; output ready,alias; assign ready=clk; endmodule'
        parent=b'module parent(clk,rst_n,ready,observed); input clk,rst_n; output ready,observed; wire spare; TILE tile(.clk(clk),.rst_n(rst_n),.ready(ready),.alias(spare)); endmodule'
        model=engine.TileCone(tile,{}, {})
        result=engine.unused_output_alias(model,Module(parent),'tile','alias')
        self.assertEqual(result['parent_consumers'],0)
        used=parent.replace(b'endmodule',b'assign observed=spare; endmodule')
        with self.assertRaises(AssertionError):engine.unused_output_alias(model,Module(used),'tile','alias')
        driven=engine.TileCone(tile.replace(b'endmodule',b'assign alias=clk; endmodule'),{}, {})
        with self.assertRaises(AssertionError):engine.unused_output_alias(driven,Module(parent),'tile','alias')

    def test_alias_bit_read_through_whole_bus_is_not_missed(self):
        engine=self.engine()
        from prove_tri_oracle_parent_reset import Module
        tile=b'module tile(clk,rst_n,ready,alias); input clk,rst_n; output ready,alias; assign ready=clk; endmodule'
        parent=b'module parent(clk,rst_n,ready); input clk,rst_n; output ready; wire [1:0] spare; TILE tile(.clk(clk),.rst_n(rst_n),.ready(ready),.alias(spare[0])); CONSUMER peer(.data(spare)); endmodule'
        with self.assertRaises(AssertionError):
            engine.unused_output_alias(engine.TileCone(tile,{}, {}),Module(parent),'tile','alias')

    def test_targeted_query_uses_activation_and_cannot_count_skips_as_proof(self):
        engine=self.engine()
        self.assertTrue(hasattr(engine,'packet_query'),'Targeted packet query helper is missing')
        import z3
        bridge=engine.WordBridge(None);value=bridge.word('value',1)
        self.assertFalse(engine.packet_query(bridge,[value],[z3.BitVecVal(0,1)],label='other',selected_label='target'))
        self.assertTrue(engine.packet_query(bridge,[value],[z3.BitVecVal(0,1)],label='target',selected_label='target',activation=[value==0]))
        with self.assertRaises(AssertionError):
            engine.packet_query(bridge,[value],[z3.BitVecVal(0,1)],label='target',selected_label='target',activation=[value==1])


if __name__=='__main__':unittest.main()
