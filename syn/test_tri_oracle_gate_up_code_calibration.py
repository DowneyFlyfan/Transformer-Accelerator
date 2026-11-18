"""Bounded calibration must preserve physical scale, limits and source codes."""
from pathlib import Path
import sys,unittest
import torch
sys.path.insert(0,str(Path(__file__).resolve().parent))


class ProjectionCodeCalibrationTest(unittest.TestCase):
    def test_one_code_step_uses_original_weight_exponent(self):
        from measure_tri_oracle_gate_up_code_calibration import fit_projection_codes
        # Caller fixtures: activation[M=2,H=1], weight/codes[K=1,H=1].
        activation=torch.tensor([[1.],[2.]])
        codes=torch.tensor([[4]],dtype=torch.int8)
        saved=codes.clone()
        for exponent in (0,-2):
            weight=torch.tensor([[5.*2.**exponent]])
            changed=fit_projection_codes(activation,weight,codes,exponent)
            self.assertEqual(changed.tolist(),[[5]])
            self.assertEqual(changed.dtype,torch.int8)
            self.assertTrue(torch.equal(codes,saved))

    def test_updates_bound_and_saturate_in_wider_integer_type(self):
        from measure_tri_oracle_gate_up_code_calibration import fit_projection_codes
        # Fixture A[M=2,H=1], W/C[K=4,H=1] covers both signed endpoints.
        activation=torch.ones(2,1)
        weight=torch.tensor([[1000.],[-1000.],[1000.],[-1000.]])
        codes=torch.tensor([[127],[-128],[0],[0]],dtype=torch.int8)
        changed=fit_projection_codes(activation,weight,codes,0)
        self.assertEqual(changed.tolist(),[[127],[-128],[1],[-1]])

    def test_identity_and_zero_input_leave_all_channel_codes_unchanged(self):
        from measure_tri_oracle_gate_up_code_calibration import fit_projection_codes
        # Fixture A[M=2,H=2], W/C[K=3,H=2] distinguishes output/input axes.
        codes=torch.tensor([[1,2],[-3,4],[5,-6]],dtype=torch.int8)
        for activation in (torch.eye(2),torch.zeros(2,2)):
            changed=fit_projection_codes(activation,codes.float(),codes,0)
            self.assertEqual(changed.shape,(3,2))
            self.assertTrue(torch.equal(changed,codes))

    def test_invalid_inputs_rejected_before_code_calibration(self):
        from measure_tri_oracle_gate_up_code_calibration import fit_projection_codes
        # Valid caller fixtures A[M=2,H=2], W/C[K=3,H=2]; cases mutate one input.
        activation=torch.eye(2);weight=torch.ones(3,2);codes=torch.ones(3,2,dtype=torch.int8)
        cases=[(activation[:0],weight,codes,0),(activation,weight.T,codes,0),
               (activation,weight,codes.float(),0),(activation.long(),weight,codes,0),
               (activation,weight.long(),codes,0),(activation,weight,codes,True),
               (activation,weight,codes,-2147483648),(activation,weight,codes,1.5),
               (activation*float('nan'),weight,codes,0),(activation,weight*float('inf'),codes,0)]
        for args in cases:
            with self.subTest(exponent=args[3]),self.assertRaises(ValueError):
                fit_projection_codes(*args)

    def test_discrete_step_improves_when_distributed_corrections_round_to_zero(self):
        from measure_tri_oracle_gate_up_code_calibration import fit_projection_codes
        # Fit A[M=2,H=4] repeats one row. W/C[K=1,H=4] sums to target.8.
        # Four continuous corrections near.2 all round to zero, but one legal
        # code step reduces the exact projection error from.8 to.2.
        activation=torch.ones(2,4)
        weight=torch.full((1,4),.2)
        codes=torch.zeros(1,4,dtype=torch.int8)
        changed=fit_projection_codes(activation,weight,codes,0)
        self.assertEqual(int(changed.sum()),1)
        self.assertLess(float((activation@changed.float().T-.8).square().sum()),
                        float((activation@codes.float().T-.8).square().sum()))


if __name__=='__main__':unittest.main()
