"""An attention response epoch must retain a busy, unpaired receiver."""
from pathlib import Path
import sys,unittest,z3
sys.path.insert(0,str(Path(__file__).resolve().parent))


class SharedReturnTest(unittest.TestCase):
    def test_owned_attention_requires_busy_and_unpaired(self):
        from prove_tri_oracle_shared_return import ownership_invariant
        for owned,busy,paired,wanted in ((True,True,False,True),(True,False,False,False),
                (True,True,True,False),(False,False,True,True),(False,True,True,True)):
            value=ownership_invariant(*(z3.BoolVal(x) for x in (owned,busy,paired)))
            self.assertEqual(z3.is_true(z3.simplify(value)),wanted)

    def test_only_five_physical_state_triples_are_permitted(self):
        from prove_tri_oracle_shared_return import ownership_invariant
        triples=[(owned,busy,paired) for owned in (False,True) for busy in (False,True) for paired in (False,True)
            if z3.is_true(z3.simplify(ownership_invariant(*(z3.BoolVal(x) for x in (owned,busy,paired)))))]
        self.assertEqual(len(triples),5)
        self.assertEqual([x for x in triples if x[0]],[(True,True,False)])

    def test_multibit_state_cannot_replace_a_physical_flag(self):
        from prove_tri_oracle_shared_return import ownership_invariant
        with self.assertRaisesRegex(AssertionError,'Boolean'):
            ownership_invariant(z3.BoolVal(True),z3.BitVecVal(1,2),z3.BoolVal(False))

    def test_reference_acquires_retains_and_retires_on_the_actual_events(self):
        from prove_tri_oracle_shared_return import ownership_reference_next
        # Old owned/busy/paired; attention accept/terminal; receiver
        # accept/terminal; receiver paired configuration. Accept has priority.
        cases=[((False,False,True,True,False,True,False,False),(True,True,False)),
               ((True,True,False,False,False,False,False,True),(True,True,False)),
               ((True,True,False,False,True,False,True,True),(False,False,False)),
               ((False,False,False,True,True,True,True,True),(True,True,True))]
        for arguments,wanted in cases:
            with self.subTest(arguments=arguments):
                actual=ownership_reference_next(*(z3.BoolVal(x) for x in arguments))
                self.assertEqual(tuple(z3.is_true(z3.simplify(x)) for x in actual),wanted)


if __name__=='__main__':unittest.main()
