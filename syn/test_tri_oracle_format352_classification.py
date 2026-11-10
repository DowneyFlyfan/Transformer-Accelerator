"""Reject unrelated native failures and missing first-frame evidence."""
import importlib.util
from pathlib import Path
import unittest


class ClassificationTests(unittest.TestCase):
    def setUp(self):
        path=Path('syn/run_tri_oracle_format352_source.py')
        self.assertTrue(path.is_file(), 'Native protected-format verification runner is missing')
        spec=importlib.util.spec_from_file_location('format352',path)
        self.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.module)

    def test_second_frame_control_requires_exact_observed_and_reference_words(self):
        log='FORMAT351_FRAME_PASS frame=0 outputs=35\nFORMAT351_INTEGER_OUTPUT frame=1 row=2 got=-5 expected=9\n'
        self.assertTrue(self.module.negative_matches(log,2,1,2,-5,9))
        self.assertFalse(self.module.negative_matches(log,0,1,2,-5,9))
        self.assertFalse(self.module.negative_matches(log,2,1,2,-4,9))
        self.assertFalse(self.module.negative_matches(log,2,1,2,-5,8))
        self.assertFalse(self.module.negative_matches(log.split('\n',1)[1],2,1,2,-5,9))

    def test_license_and_unrelated_protocol_failures_cannot_qualify(self):
        for log in ['xrun: *F,NOLICN: license checkout failed','FORMAT351_FETCHED_SKIPPED_CHANNEL',
                    'FORMAT351_PAIR_PASS outputs=70 frames=2 external_reset_releases=1']:
            self.assertFalse(self.module.negative_matches(log,2,0,0,2,1))


if __name__=='__main__':unittest.main()
