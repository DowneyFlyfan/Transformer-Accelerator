"""Exercise exponent dispatch with real unchanged integer arithmetic."""
import importlib.util
from pathlib import Path
import sys
import unittest


class ExponentPolicyTests(unittest.TestCase):
    def setUp(self):
        path=Path('syn/tri_oracle_format335_policy.py')
        self.assertTrue(path.is_file(),'Input-exponent format dispatch is missing')
        sys.path.insert(0,'syn')
        spec=importlib.util.spec_from_file_location('policy335',path)
        self.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.module)
        import torch
        from tri_oracle_integer_reference import IntegerFeedForwardReference
        self.torch=torch
        torch.set_num_threads(1)
        torch.manual_seed(335)
        weights=[torch.randn((32,32),device='cuda')*.1 for _ in range(3)]
        self.reference=IntegerFeedForwardReference(*weights,1e-5)
        self.activation=torch.randn((7,32),device='cuda')*torch.tensor([.25,4,1,.25,4,1,.5],device='cuda')[:,None]
        self.residual=self.activation*.3

    def compare(self,expected,actual):
        for left,right in zip(expected[:2],actual[:2]):self.assertTrue(self.torch.equal(left,right))
        self.assertEqual(set(expected[2]),set(actual[2]))
        for key in expected[2]:self.assertTrue(self.torch.equal(expected[2][key],actual[2][key]),key)

    def test_uniform_settings_preserve_unsorted_rows_and_all_statistics(self):
        from tri_oracle_integer_reference import _quantize
        pair=dict(maximum_up_gain_bits=2,down_shift_offset=0)
        exponents=_quantize(self.activation,per_row=True)[1][:,0].tolist()
        self.assertGreater(len(set(exponents)),1)
        policy=dict(fallback=pair,buckets=[dict(activation_exponent=e,**pair) for e in set(exponents)])
        expected=self.reference.evaluate(self.activation,self.residual,prune=True,**pair)
        self.assertGreater(int((expected[0]!=0).sum()),0)
        actual=self.module.evaluate_policy(self.reference,self.activation,self.residual,policy,prune=True)
        self.compare(expected,actual)

    def test_mixed_bucket_and_unseen_fallback_match_independent_single_rows(self):
        from tri_oracle_integer_reference import _quantize
        exponents=_quantize(self.activation,per_row=True)[1][:,0].tolist()
        special=max(exponents)
        fallback=dict(maximum_up_gain_bits=2,down_shift_offset=0)
        override=dict(maximum_up_gain_bits=-2,down_shift_offset=2)
        policy=dict(fallback=fallback,buckets=[dict(activation_exponent=special,**override)])
        expected=[]
        for row,e in enumerate(exponents):
            expected.append(self.reference.evaluate(self.activation[row:row+1],self.residual[row:row+1],
                            prune=False,**(override if e==special else fallback)))
        combined=(self.torch.cat([v[0] for v in expected]),self.torch.cat([v[1] for v in expected]),
                  {key:self.torch.cat([v[2][key] for v in expected]) for key in expected[0][2]})
        actual=self.module.evaluate_policy(self.reference,self.activation,self.residual,policy,prune=False)
        self.compare(combined,actual)

    def test_duplicate_exponents_are_rejected(self):
        pair=dict(maximum_up_gain_bits=2,down_shift_offset=0)
        bucket=dict(activation_exponent=-5,**pair)
        with self.assertRaises(ValueError):
            self.module.evaluate_policy(self.reference,self.activation,self.residual,
                                        dict(fallback=pair,buckets=[bucket,bucket]),prune=False)


if __name__=='__main__':unittest.main()
