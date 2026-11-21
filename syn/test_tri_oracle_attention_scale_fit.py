"""Breaks caught: half-boundary exponent error and held-data retuning."""
import importlib.util,math,unittest
from pathlib import Path

class Tests(unittest.TestCase):
    def setUp(self):
        path=Path(__file__).with_name('tri_oracle_attention_scale_fit.py')
        self.assertTrue(path.exists(),'Fixed disjoint scale fitter is not implemented')
        spec=importlib.util.spec_from_file_location('scale_fit_test',path)
        self.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.module)

    def test_exact_power_of_two_endpoints(self):
        cases=[(0.,0),(127.,0),(127.0000000001,1),(128.,1),(254.,1),(255.,2),
               (127/32,-5),(127/32+2**-40,-4),(.5,-7),(1.,-6),(2.,-5)]
        for value,want in cases:
            with self.subTest(value=value):self.assertEqual(self.module.choose_exponent(value),want)
        for value in (-1.,math.nan,math.inf):
            with self.assertRaises(ValueError):self.module.choose_exponent(value)

    def test_held_rows_cannot_fit_or_revise_frozen_exponents(self):
        fit=self.module.FrozenScaleFit(layers=1,fit_cases=(0,1))
        fit.add(0,0,[127.]*40,[127/32]*32)
        with self.assertRaises(ValueError):fit.add(8,0,[10000.]*40,[10000.]*32)
        with self.assertRaises(RuntimeError):fit.freeze()
        fit.add(1,0,[254.]*40,[127/16]*32)
        frozen=fit.freeze()
        self.assertEqual(frozen['qkv_exponents'],[[1]*40])
        self.assertEqual(frozen['output_exponents'],[[-4]*32])
        with self.assertRaises(RuntimeError):fit.add(0,0,[10000.]*40,[10000.]*32)
        self.assertEqual(fit.frozen,frozen)

    def test_invalid_or_missing_groups_are_rejected(self):
        fit=self.module.FrozenScaleFit(layers=1,fit_cases=(0,))
        for q,o in [([1.]*39,[1.]*32),([1.]*40,[1.]*31),([math.nan]*40,[1.]*32)]:
            with self.assertRaises(ValueError):fit.add(0,0,q,o)
        with self.assertRaises(RuntimeError):fit.freeze()
        fit.add(0,0,[0.]*40,[0.]*32)
        self.assertEqual(fit.freeze()['qkv_exponents'],[[0]*40])

if __name__=='__main__':unittest.main(verbosity=2)
