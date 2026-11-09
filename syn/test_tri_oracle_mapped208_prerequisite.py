"""Fail closed before a positive mapped run unless its same-source control failed."""
from copy import deepcopy
import unittest
from tri_oracle_mapped208_prerequisite import require_wrong_reference


class PrerequisiteTests(unittest.TestCase):
    def test_exact_expected_negative_accepted(self):
        require_wrong_reference(self.record(),{'bench':'same','simulator':'same'},8)

    def record(self):
        return dict(state='expected_wrong_mapped_reference_rejected',negative_reference=True,
            native_exit_status=1,temporary_build_removed=True,requested_simulation_workers=8,source_sha256={'bench':'same','simulator':'same'})

    def test_unfinished_wrong_source_and_wrong_outcomes_rejected(self):
        for key,value in [('state','failed'),('negative_reference',False),('native_exit_status',0),
                          ('native_exit_status',None),('native_exit_status',True),('requested_simulation_workers',1),
                          ('temporary_build_removed',False),('source_sha256',{'bench':'changed','simulator':'same'})]:
            with self.subTest(key=key):
                record=deepcopy(self.record());record[key]=value
                with self.assertRaises(AssertionError):require_wrong_reference(record,{'bench':'same','simulator':'same'},8)
        with self.assertRaises(AssertionError):require_wrong_reference(self.record(),{},8)

    def test_mapped_parent_mismatch_rejected_after_static_inputs_match(self):
        record=self.record();record['source_sha256']['mapped_parent']='parent_A'
        require_wrong_reference(record,{'bench':'same','simulator':'same'},8)
        with self.assertRaises(AssertionError):
            require_wrong_reference(record,{'bench':'same','simulator':'same','mapped_parent':'parent_B'},8)
        with self.assertRaises(AssertionError):
            require_wrong_reference(record,{'bench':'same','simulator':'same','producer_record':'different'},8)


if __name__=='__main__':unittest.main()
