"""Command identity must survive bubbles, stalls, writeback and completion."""
from pathlib import Path
from collections import deque
import sys,unittest,z3
sys.path.insert(0,str(Path(__file__).resolve().parent))


def state(valid,slots,accum):
    return dict(valid=[z3.BoolVal(x) for x in valid],slot=[z3.BitVecVal(x,4) for x in slots],
                accumulate=[z3.BoolVal(x) for x in accum])


def integers(value):
    return {key:[z3.is_true(z3.simplify(x)) if z3.is_bool(x) else z3.simplify(x).as_long() for x in values]
            for key,values in value.items()}


class MetadataHistoryTest(unittest.TestCase):
    def test_stall_preserves_pending_and_array_but_drains_writeback_and_done(self):
        from prove_tri_oracle_accumulator_metadata import queue_next
        old=state([True,False,True,False,True,True,False],[1,2,3,4,5,6,7],[False,True,False,True,False,True])
        actual=integers(queue_next(old,z3.BoolVal(True),z3.BitVecVal(9,4),z3.BoolVal(False),
                                   z3.BoolVal(False),z3.BoolVal(False),z3.BoolVal(True)))
        self.assertEqual(actual,dict(valid=[True,False,True,False,True,False,True],
            slot=[1,2,3,4,5,6,6],accumulate=[False,True,False,True,False,True]))

    def test_accepted_command_shifts_old_metadata_and_captures_new_identity(self):
        from prove_tri_oracle_accumulator_metadata import queue_next
        old=state([True,False,True,False,True,False,True],[1,2,3,4,5,6,7],[False,True,False,True,False,True])
        actual=integers(queue_next(old,z3.BoolVal(True),z3.BitVecVal(9,4),z3.BoolVal(True),
                                   z3.BoolVal(True),z3.BoolVal(True),z3.BoolVal(True)))
        self.assertEqual(actual,dict(valid=[True,True,False,True,False,True,False],
            slot=[9,1,2,3,4,5,7],accumulate=[True,False,True,False,True,False]))

    def test_admission_denial_and_empty_output_advance_without_accepting_command(self):
        from prove_tri_oracle_accumulator_metadata import queue_next
        old=state([True,False,True,False,False,False,False],[1,2,3,4,5,6,7],[False,True,False,True,False,True])
        actual=integers(queue_next(old,z3.BoolVal(True),z3.BitVecVal(9,4),z3.BoolVal(True),
                                   z3.BoolVal(False),z3.BoolVal(False),z3.BoolVal(True)))
        self.assertEqual(actual,dict(valid=[False,True,False,True,False,False,False],
            slot=[1,1,2,3,4,6,7],accumulate=[False,False,True,False,True,True]))

    def test_reset_cancels_all_pending_metadata_and_valid_bits(self):
        from prove_tri_oracle_accumulator_metadata import queue_next
        old=state([True]*7,[15]*7,[True]*6)
        actual=integers(queue_next(old,z3.BoolVal(True),z3.BitVecVal(9,4),z3.BoolVal(True),
                                   z3.BoolVal(True),z3.BoolVal(False),z3.BoolVal(False)))
        self.assertEqual(actual,dict(valid=[False]*7,slot=[0]*7,accumulate=[False]*6))

    def test_prefetch_uses_same_slot_current_write_and_preserves_other_slots(self):
        from prove_tri_oracle_accumulator_metadata import prefetch_base
        memory=z3.K(z3.BitVecSort(4),z3.BitVecVal(11,32))
        for read,write,enabled,wanted in ((3,3,True,29),(3,4,True,11),(3,3,False,11)):
            actual,updated=prefetch_base(memory,z3.BitVecVal(read,4),z3.BoolVal(enabled),
                                        z3.BitVecVal(write,4),z3.BitVecVal(29,32))
            self.assertEqual(z3.simplify(actual).as_long(),wanted)
            self.assertEqual(z3.simplify(z3.Select(updated,z3.BitVecVal(read,4))).as_long(),wanted)

    def test_reference_queue_returns_accepted_metadata_in_order_under_stalls(self):
        from prove_tri_oracle_accumulator_metadata import queue_next
        current=state([False]*7,[0]*7,[False]*6);expected=deque();accepted=completed=0
        for cycle in range(232):
            previous=integers(current)
            if previous['valid'][6]:
                self.assertTrue(expected)
                self.assertEqual(previous['slot'][6],expected.popleft())
                completed+=1
            outgoing=(cycle%7 not in (1,2,3)) if cycle<200 else True
            ready=not previous['valid'][4] or outgoing
            admitted=ready and (cycle%5!=0)
            offered=cycle<200 and cycle%3!=0
            slot=accepted%16
            if offered and admitted:expected.append(slot);accepted+=1
            current=queue_next(current,z3.BoolVal(offered),z3.BitVecVal(slot,4),z3.BoolVal(cycle%2==0),
                z3.BoolVal(outgoing),z3.BoolVal(admitted),z3.BoolVal(True))
        self.assertGreater(accepted,40)
        self.assertEqual(completed,accepted)
        self.assertEqual(len(expected),0)

    def test_unpublished_predecessor_cannot_omit_required_evidence(self):
        from prove_tri_oracle_accumulator_metadata import qualified_predecessor
        import json
        content=(Path(__file__).resolve().parents[1]/'records/tri_oracle_packaged_accumulator_next_states.json').read_bytes()
        current=qualified_predecessor(content)
        changed=json.loads(content);changed['evidence_sha256']={}
        self.assertEqual(current['core_count'],20)
        with self.assertRaisesRegex(AssertionError,'predecessor digest'):
            qualified_predecessor((json.dumps(changed,indent=2)+'\n').encode())


if __name__=='__main__':unittest.main()
