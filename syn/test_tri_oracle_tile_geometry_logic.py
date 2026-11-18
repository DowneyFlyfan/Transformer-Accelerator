"""Guard composition against shared-name collisions and floating inputs."""
from pathlib import Path
import sys
import unittest
import z3

sys.path.insert(0,str(Path(__file__).resolve().parent))
from prove_tri_oracle_tile_geometry import ContextBridge,clipped_limit,epoch_invariant,geometry_check
from prove_tri_oracle_head_ratio import ClassifierCone


class GeometryLogicTest(unittest.TestCase):
    def models(self):
        parent=ClassifierCone(b'module parent(p);\ninput p;\nwire dead;\nendmodule\n',{}, {})
        child=ClassifierCone(b'module child(a);\ninput [1:0] a;\nendmodule\n',{}, {})
        return parent,child

    def test_module_states_with_identical_names_are_independent(self):
        parent,child=self.models()
        a=ContextBridge(parent,'parent');b=ContextBridge(child,'tile')
        solver=z3.Solver();solver.add(a.boolean('state[0]')!=b.boolean('state[0]'))
        self.assertEqual(solver.check(),z3.sat)

    def test_used_child_input_is_the_actual_upstream_wire(self):
        parent,child=self.models();a=ContextBridge(parent,'parent')
        b=ContextBridge(child,'tile',upstream=a,bindings={'a':'{dead, p}'})
        got,=b.convert([child.cone('a[0]')])
        solver=z3.Solver();solver.add(got!=a.boolean('p'))
        self.assertEqual(solver.check(),z3.unsat)
        self.assertEqual(set(b.bound_inputs),{'a[0]'})

    def test_consumed_undriven_input_is_rejected(self):
        parent,child=self.models();a=ContextBridge(parent,'parent')
        b=ContextBridge(child,'tile',upstream=a,bindings={'a':'{dead, p}'})
        with self.assertRaisesRegex(AssertionError,'Missing mapped driver'):
            b.convert([child.cone('a[1]')])

    def test_actual_binding_width_must_match(self):
        parent,child=self.models();a=ContextBridge(parent,'parent')
        with self.assertRaisesRegex(AssertionError,'binding width'):
            ContextBridge(child,'tile',upstream=a,bindings={'a':'p'})

    def test_causal_limit_zero_partial_saturation_and_unsigned_width(self):
        for query,token,start,wanted in [(127,0,128,0),(128,0,128,1),(158,0,128,31),
                (159,0,128,32),(160,0,128,32),(127,15,128,15),(8191,15,65530,0)]:
            result=clipped_limit(z3.BitVecVal(query,13),z3.BitVecVal(token,4),z3.BitVecVal(start,16))
            self.assertEqual(z3.simplify(result).as_long(),wanted)

    def test_causal_limit_bounds_also_hold_between_batches(self):
        parent={name:z3.BitVecVal(value,width) for name,width,value in [
            ('state',3,2),('query',13,96),('tokens',11,128),('query_addr',64,0),('key_base',64,0)]}
        tile={name:z3.BitVecVal(value,width) for name,width,value in [
            ('state',3,0),('query',13,0),('inner',8,0),('rows',11,0),('tokens',5,0),
            ('query_addr',64,0),('key_base',64,0),('token',4,0),('key',7,0),('beat',4,0),('limits',18,32)]}
        self.assertTrue(z3.is_true(z3.simplify(epoch_invariant(parent,tile))))
        tile['limits']=z3.BitVecVal(33,18)
        self.assertTrue(z3.is_false(z3.simplify(epoch_invariant(parent,tile))))

    def test_reset_epoch_parent_batch_start_stays_aligned_to16(self):
        parent={name:z3.BitVecVal(value,width) for name,width,value in [
            ('state',3,2),('query',13,97),('tokens',11,128),('query_addr',64,0),('key_base',64,0)]}
        tile={name:z3.BitVecVal(value,width) for name,width,value in [
            ('state',3,0),('query',13,0),('inner',8,0),('rows',11,0),('tokens',5,0),
            ('query_addr',64,0),('key_base',64,0),('token',4,0),('key',7,0),('beat',4,0),('limits',18,0)]}
        self.assertTrue(z3.is_false(z3.simplify(epoch_invariant(parent,tile))))

    def test_numeric_query_selector_cannot_silently_skip_the_proof(self):
        parent,_=self.models();bridge=ContextBridge(parent,'parent')
        with self.assertRaisesRegex(AssertionError,'selector'):
            geometry_check(bridge,[z3.BoolVal(True)],[z3.BoolVal(False)],label='capture',only_query=96)


if __name__=='__main__':unittest.main()
