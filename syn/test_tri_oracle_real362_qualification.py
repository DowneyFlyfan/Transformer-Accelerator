"""Reject stale-candidate and unrelated-failure substitutes for mapped proof."""
import importlib.util
from pathlib import Path
import unittest


class QualificationTests(unittest.TestCase):
    def setUp(self):
        p=Path('syn/qualify_tri_oracle_real362_mapped.py')
        self.assertTrue(p.exists(),'Independent current-candidate qualifier is missing')
        s=importlib.util.spec_from_file_location('real362',p);self.module=importlib.util.module_from_spec(s);s.loader.exec_module(self.module)

    def test_exact_current_parent_substitution_is_required(self):
        prepared='`include "/lib.v"\n`include "/core.v"\n`include "/old/parent.v"\n'
        current='/placed/restored_parent.v';expected=prepared.replace('/old/parent.v',current)
        self.module.require_current_bundle(prepared,expected,current)
        for changed in [prepared,expected+'module unrelated;endmodule\n',expected.replace(current,'/other/parent.v')]:
            with self.assertRaises(ValueError):self.module.require_current_bundle(prepared,changed,current)

    def test_exact_negative_and_complete_positive_must_both_match(self):
        hierarchy='REAL_FRAME_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=600\n'
        negative=hierarchy+'REAL_FRAME_INTEGER_OUTPUT row=0 got=-631 expected=-632\n'
        positive=hierarchy+'REAL_FRAME_PASS outputs=2048 packets=13 groups=176 strips=45056 channels=5632 prediction_packets=36 stalls=56 requests=1580544\n'
        self.assertEqual(self.module.parse_pair(negative,positive,2,0,0xfffffd89)['memory_requests'],1580544)
        for wrong,full,ncode,pcode in [(negative,positive,0,0),(negative,positive,2,2),
                                      (negative.replace('-631','-630'),positive,2,0),
                                      (negative,positive.replace('outputs=2048','outputs=35'),2,0),
                                      ('license checkout failed',positive,2,0)]:
            with self.assertRaises(ValueError):self.module.parse_pair(wrong,full,ncode,pcode,0xfffffd89)


if __name__=='__main__':unittest.main()
