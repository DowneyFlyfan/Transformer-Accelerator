"""Projection ownership permits only an idle attention layer."""
from pathlib import Path
import sys,unittest,z3
sys.path.insert(0,str(Path(__file__).resolve().parent))

class PipelineLayerEpochTest(unittest.TestCase):
    def test_busy_projection_requires_idle_attention_layer(self):
        from prove_tri_oracle_pipeline_layer_epoch import exclusion_invariant
        for busy,layer,wanted in ((False,0,True),(False,5,True),(True,0,True),(True,5,False),(True,7,False)):
            value=exclusion_invariant(z3.BoolVal(busy),z3.BitVecVal(layer,4))
            self.assertEqual(z3.is_true(z3.simplify(value)),wanted)

    def test_exclusion_domain_has17_pairs(self):
        from prove_tri_oracle_pipeline_layer_epoch import exclusion_invariant
        pairs=[(busy,layer) for busy in (False,True) for layer in range(16)
               if z3.is_true(z3.simplify(exclusion_invariant(z3.BoolVal(busy),z3.BitVecVal(layer,4))))]
        self.assertEqual(len(pairs),17)
        self.assertEqual([layer for busy,layer in pairs if busy],[0])

    def test_wrong_physical_state_width_is_rejected(self):
        from prove_tri_oracle_pipeline_layer_epoch import exclusion_invariant
        with self.assertRaisesRegex(AssertionError,'width'):
            exclusion_invariant(z3.BoolVal(False),z3.BitVecVal(0,5))

if __name__=='__main__':unittest.main()
