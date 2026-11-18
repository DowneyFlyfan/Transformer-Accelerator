"""Reciprocal weights must preserve the floating gated feed-forward function."""
from pathlib import Path
import sys,unittest
import torch
import torch.nn.functional as functional
sys.path.insert(0,str(Path(__file__).resolve().parent))


class ReciprocalWeightsTest(unittest.TestCase):
    def test_opposite_channel_ranges_balance_in_opposite_directions(self):
        from measure_tri_oracle_reciprocal_weight_equalization import channel_powers
        # Literal trained-weight stand-ins: Up[K=2,H=2], Down[O=2,K=2].
        up=torch.tensor([[1.,0.],[0.,4.]])
        down=torch.tensor([[4.,0.],[0.,1.]])
        self.assertEqual(channel_powers(up,down).tolist(),[1,-1])

    def test_zero_contribution_channels_keep_their_original_scale(self):
        from measure_tri_oracle_reciprocal_weight_equalization import channel_powers
        # Up[K=2,H=2] and Down[O=2,K=2] have no contributing channel.
        up=torch.tensor([[0.,0.],[1.,0.]])
        down=torch.tensor([[1.,0.],[0.,0.]])
        self.assertEqual(channel_powers(up,down).tolist(),[0,0])

    def test_reciprocal_transform_preserves_signed_swiglu_output(self):
        from measure_tri_oracle_reciprocal_weight_equalization import reciprocal_weights
        # Fixed X[M=2,H=2], Gate/Up[K=2,H=2], Down[O=2,K=2], powers[K].
        x=torch.tensor([[1.,-2.],[.25,3.]],dtype=torch.float64)
        gate=torch.tensor([[-1.,2.],[3.,.5]],dtype=torch.float64)
        up=torch.tensor([[1.,-4.],[-2.,3.]],dtype=torch.float64)
        down=torch.tensor([[2.,1.],[-3.,4.]],dtype=torch.float64)
        powers=torch.tensor([2,-1],dtype=torch.int32)
        changed_up,changed_down=reciprocal_weights(up,down,powers)
        old=functional.linear(functional.silu(functional.linear(x,gate))*functional.linear(x,up),down)
        new=functional.linear(functional.silu(functional.linear(x,gate))*functional.linear(x,changed_up),changed_down)
        torch.testing.assert_close(new,old,rtol=1e-12,atol=1e-12)

    def test_malformed_or_nonfinite_weights_are_rejected(self):
        from measure_tri_oracle_reciprocal_weight_equalization import channel_powers
        # Invalid matrix shapes and a nonfinite checkpoint entry must fail closed.
        with self.assertRaisesRegex(ValueError,'shapes'):
            channel_powers(torch.ones(2,3),torch.ones(3,4))
        with self.assertRaisesRegex(ValueError,'finite'):
            channel_powers(torch.tensor([[float('nan')]]),torch.ones(1,1))

    def test_lowest_signed_power_is_rejected_before_negation_overflow(self):
        from measure_tri_oracle_reciprocal_weight_equalization import reciprocal_weights
        # Scalar-channel matrices [1,1]; int32 minimum has an overflowing abs().
        with self.assertRaisesRegex(ValueError,'Bounded'):
            reciprocal_weights(torch.ones(1,1),torch.ones(1,1),
                               torch.tensor([-2**31],dtype=torch.int32))


if __name__=='__main__':unittest.main()
