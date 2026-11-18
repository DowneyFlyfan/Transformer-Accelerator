"""Check exact gate conversion, signed thresholds and failed proof handling."""
import importlib.util
from pathlib import Path
import unittest

SOURCE=Path(__file__).with_name('prove_tri_oracle_head_intensity.py')


class HeadIntensityTests(unittest.TestCase):
    def engine(self):
        self.assertTrue(SOURCE.exists(),'Mapped intensity verifier is missing')
        spec=importlib.util.spec_from_file_location('head_intensity',SOURCE)
        engine=importlib.util.module_from_spec(spec);spec.loader.exec_module(engine)
        return engine

    def test_every_graph_operator_and_lsb_word_binding_is_exact(self):
        engine=self.engine()
        import z3
        from prove_tri_oracle_packaged_products import BooleanGraph
        graph=BooleanGraph();a=graph.variable('a[0]');b=graph.variable('a[1]')
        roots=[graph.operation(op,a,b) for op in ('&','|','^')]+[graph.operation('!',a)]
        bridge=engine.WordBridge(graph);word=bridge.word('a',2)
        actual=bridge.convert(roots)
        solver=z3.Solver()
        for value,want in [(0,[False,False,False,True]),(1,[False,True,True,False]),
                           (2,[False,True,True,True]),(3,[True,True,False,False])]:
            solver.push();solver.add(word==value);self.assertEqual(solver.check(),z3.sat)
            self.assertEqual([z3.is_true(solver.model().eval(root)) for root in actual],want)
            solver.pop()

    def test_threshold_is_signed34_unsigned_alpha_and_strict(self):
        engine=self.engine()
        for scores,mask,maximum,alpha,want in [
            ([-2147483648]*8,255,-2147483648,0,0),
            ([-2147483648]*8,255,-2147483648,1,8),
            ([2147483647]*8,129,2147483647,0,0),
            ([2147483647]*8,129,2147483647,1,2),
            ([-1]*8,255,2147483647,4294967295,8),
        ]:
            self.assertEqual(engine.reference_hits(scores,mask,maximum-alpha),want)
        self.assertEqual(engine.reference_maximum([-5,-7,2147483647,-9,-8,-6,-4,-3],3,-10),-5)
        self.assertEqual(engine.reference_maximum([2147483647]*8,0,-11),-11)

    def test_satisfiable_mismatch_and_unknown_never_count_as_proof(self):
        engine=self.engine()
        import z3
        engine.require_unsat(z3.unsat,'matching')
        for result in (z3.sat,z3.unknown):
            with self.assertRaises(AssertionError):engine.require_unsat(result,'bad')

    def test_bridge_equivalence_rejects_a_real_wrong_sign_comparison(self):
        engine=self.engine()
        import z3
        bridge=engine.WordBridge(None);word=bridge.word('score',32)
        with self.assertRaises(AssertionError):
            bridge.check([word>0],[z3.UGT(word,0)],label='unsigned_score')
        bridge.check([word>0],[word>=1],label='same_signed_comparison')

    def test_packet_oracle_final_sink_and_malformed_transitions(self):
        engine=self.engine()
        import z3
        bridge=engine.WordBridge(None);old,next_fields,_=engine.specification(bridge)
        fixed={old['state']:1,old['beat_index']:3,old['rows_left']:1,
               old['row_max']:-20,old['row_has_sink']:False,
               bridge.word('in_scores',256):(2147483647<<224),bridge.word('in_lanes',8):128,
               bridge.word('cfg_alpha',32):4294967295,bridge.word('in_region',2):0,
               bridge.boolean('in_valid'):True,bridge.boolean('in_last'):False}
        solver=z3.Solver();solver.add(*(key==value for key,value in fixed.items()))
        self.assertEqual(solver.check(),z3.sat);model=solver.model()
        self.assertEqual(model.eval(next_fields['state']).as_long(),2)
        self.assertEqual(model.eval(next_fields['row_max']).as_signed_long(),2147483647)
        self.assertEqual(model.eval(next_fields['cutoff']).as_signed_long(),-2147483648)
        solver=z3.Solver();fixed[bridge.boolean('in_last')]=True
        solver.add(*(key==value for key,value in fixed.items()));self.assertEqual(solver.check(),z3.sat);model=solver.model()
        self.assertEqual(model.eval(next_fields['state']).as_long(),6)
        self.assertTrue(z3.is_true(model.eval(next_fields['out_error'])))

    def test_report_cannot_be_written_outside_cache(self):
        engine=self.engine()
        self.assertTrue(hasattr(engine,'verify'),'Bound candidate intensity verifier is missing')
        with self.assertRaises(AssertionError):engine.verify(SOURCE.parent/'forbidden-report.json')

    def test_inductive_count_bound_includes_all4096_rows_and_final_beat(self):
        engine=self.engine()
        self.assertTrue(hasattr(engine,'prove_numeric_invariants'),'Reachable numeric invariants are missing')
        result=engine.prove_numeric_invariants()
        self.assertEqual(result['maximum_region_intensity'],131072)
        self.assertTrue(result['cutoff_upper_bound_preserved'])
        with self.assertRaises(AssertionError):engine.prove_numeric_invariants(maximum_count=131071)

    def test_rejection_controls_require_an_actual_sat_mismatch(self):
        engine=self.engine()
        self.assertTrue(hasattr(engine,'require_counterexample'),'Strict counterexample validation is missing')
        engine.require_counterexample(AssertionError(('Intensity equivalence not proved','bad','sat','witness')))
        for error in [AssertionError(('Intensity equivalence not proved','bad','unknown','timeout')),
                      AssertionError('Missing pin'),KeyError('missing')]:
            with self.assertRaises(AssertionError):engine.require_counterexample(error)

    def test_targeted_counterexample_cannot_be_replaced_by_idle_clear_failure(self):
        engine=self.engine()
        import inspect
        self.assertIn('expected_query',inspect.signature(engine.require_counterexample).parameters,
                      'A counterexample must be bound to its intended numerical update query')
        wrong=AssertionError(('Intensity equivalence not proved','all_score_packet_next_fields_state0','sat','witness'))
        correct=AssertionError(('Intensity equivalence not proved','all_score_packet_next_fields_state2','sat','witness'))
        with self.assertRaises(AssertionError):engine.require_counterexample(wrong,expected_query='all_score_packet_next_fields_state2')
        engine.require_counterexample(correct,expected_query='all_score_packet_next_fields_state2')

    def test_python_optimized_mode_is_rejected_before_assertions_disappear(self):
        import subprocess,sys
        result=subprocess.run([sys.executable,'-O','-B','-c',
            'import sys; sys.path.insert(0,"syn"); import prove_tri_oracle_head_intensity'],
            cwd=SOURCE.parent.parent,capture_output=True,text=True,check=False)
        self.assertNotEqual(result.returncode,0,'Optimized Python must not run assertion-based proofs')
        self.assertIn('requires Python assertions',result.stderr)


if __name__=='__main__':unittest.main()
