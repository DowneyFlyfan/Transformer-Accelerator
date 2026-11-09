"""Admit only the exact, separately audited unused hierarchy-input set."""
import unittest
from tri_oracle_audited_wiring213 import require_audited_wiring


TOP='tri_oracle_predicted_feedforward_frame'
REPORT=f'''Check Design Report (c)
-------------------
Undriven Port(s)/Pin(s)
------------------------
No undriven combinational pin in '{TOP}'
No undriven sequential pin in '{TOP}'
The following hierarchical pin(s) in design '{TOP}' are undriven
hpin:{TOP}/wrapper/a (fanout : 0)
hpin:{TOP}/wrapper/b (fanout : 0)
Total number of hierarchical undriven pins in design '{TOP}' : 2
No undriven port in '{TOP}'
Multidriven Port(s)/Pin(s)
--------------------------
No multidriven combinational pin in '{TOP}'
No multidriven sequential pin in '{TOP}'
No multidriven hierarchical pin in '{TOP}'
No multidriven ports in '{TOP}'
No multidriven unloaded nets in '{TOP}'
Done Checking the design.
'''


class WiringTests(unittest.TestCase):
    def test_exact_audited_set_accepted(self):
        self.assertEqual(require_audited_wiring(REPORT,{'wrapper/a','wrapper/b'})['audited_dead_wrapper_inputs'],2)

    def test_other_issues_and_identity_changes_rejected(self):
        mutations=[REPORT.replace('wrapper/b','wrapper/c'),REPORT.replace('wrapper/b','wrapper/a'),
            REPORT.replace('(fanout : 0)','(fanout : 1)',1),REPORT.replace(' : 2',' : 3'),
            REPORT.replace(f"No undriven sequential pin in '{TOP}'",'pin:bad_live_pin (fanout : 1)'),
            REPORT.replace(f"No undriven port in '{TOP}'",'port:bad_output (fanout : 0)'),
            REPORT.replace(f"No multidriven combinational pin in '{TOP}'",'pin:multiple_driver'),
            REPORT+'unexpected warning\n',REPORT.replace(f"No undriven combinational pin in '{TOP}'",'')]
        for report in mutations:
            with self.subTest(report=report[-120:]):
                with self.assertRaises(ValueError):require_audited_wiring(report,{'wrapper/a','wrapper/b'})


if __name__=='__main__':unittest.main()
