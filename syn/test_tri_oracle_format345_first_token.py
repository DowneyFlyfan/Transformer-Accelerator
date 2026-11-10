"""Real integer-arithmetic tests for first-token protection and decode offsets."""
import importlib.util
from pathlib import Path
import sys
import unittest


class FirstTokenTests(unittest.TestCase):
    def setUp(self):
        """Own deterministic CUDA fixtures: gate/up[32,2048],down[32,32],
        activation/residual[7,2048], and scalar metadata policies. No large model.
        """
        path=Path('syn/tri_oracle_format345_first_token.py')
        self.assertTrue(path.is_file(),'First-token format dispatcher is missing')
        sys.path.insert(0,'syn')
        spec=importlib.util.spec_from_file_location('protected345',path)
        self.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.module)
        import torch
        from tri_oracle_integer_reference import IntegerFeedForwardReference
        self.torch=torch;torch.set_num_threads(1);torch.manual_seed(345)
        weights=[torch.randn(shape,device='cuda')*.1 for shape in [(32,2048),(32,2048),(32,32)]]
        self.reference=IntegerFeedForwardReference(*weights,1e-5)
        self.activation=torch.randn((7,2048),device='cuda')*torch.tensor([.25,4,1,.25,4,1,.5],device='cuda')[:,None]
        self.residual=self.activation*.3
        self.first=dict(maximum_up_gain_bits=-2,down_shift_offset=2)
        self.ordinary=dict(maximum_up_gain_bits=2,down_shift_offset=0)
        self.policy=dict(fallback=self.ordinary,buckets=[])

    def compare(self,expected,actual):
        """Compare actual raw/dequant outputs[M,32] and every statistic[M,...]."""
        for left,right in zip(expected[:2],actual[:2]):self.assertTrue(self.torch.equal(left,right))
        self.assertEqual(set(expected[2]),set(actual[2]))
        for key in expected[2]:self.assertTrue(self.torch.equal(expected[2][key],actual[2][key]),key)

    def test_initial_prefill_protects_only_first_row(self):
        expected=[]
        for row in range(7):
            expected.append(self.reference.evaluate(self.activation[row:row+1],self.residual[row:row+1],
                            prune=True,**(self.first if row==0 else self.ordinary)))
        combined=(self.torch.cat([v[0] for v in expected]),self.torch.cat([v[1] for v in expected]),
                  {key:self.torch.cat([v[2][key] for v in expected]) for key in expected[0][2]})
        actual=self.module.evaluate_protected(self.reference,self.activation,self.residual,
                                             self.policy,self.first,0,prune=True)
        self.compare(combined,actual)

    def test_single_token_decode_uses_ordinary_policy(self):
        a=self.activation[2:3];r=self.residual[2:3]
        expected=self.reference.evaluate(a,r,prune=False,**self.ordinary)
        wrong=self.reference.evaluate(a,r,prune=False,**self.first)
        self.assertFalse(self.torch.equal(expected[0],wrong[0]),'Decode fixture does not distinguish policies')
        actual=self.module.evaluate_protected(self.reference,a,r,self.policy,self.first,606,prune=False)
        self.compare(expected,actual)

    def test_single_initial_token_uses_first_policy(self):
        a=self.activation[:1];r=self.residual[:1]
        expected=self.reference.evaluate(a,r,prune=False,**self.first)
        wrong=self.reference.evaluate(a,r,prune=False,**self.ordinary)
        self.assertFalse(self.torch.equal(expected[0],wrong[0]),'Initial-token fixture does not distinguish policies')
        actual=self.module.evaluate_protected(self.reference,a,r,self.policy,self.first,0,prune=False)
        self.compare(expected,actual)

    def test_uniform_profile_preserves_all_outputs_and_statistics(self):
        for prune in [False,True]:
            expected=self.reference.evaluate(self.activation,self.residual,prune=prune,**self.ordinary)
            actual=self.module.evaluate_protected(self.reference,self.activation,self.residual,
                                                 self.policy,self.ordinary,0,prune=prune)
            self.compare(expected,actual)

    def test_invalid_global_offset_rejected(self):
        for offset in [-1,.5,True]:
            with self.subTest(offset=offset),self.assertRaises(ValueError):
                self.module.evaluate_protected(self.reference,self.activation,self.residual,
                                               self.policy,self.first,offset,prune=False)


if __name__=='__main__':unittest.main()
