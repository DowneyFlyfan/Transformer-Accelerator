"""Output service must return pre-write snapshots and preserve response history."""
from pathlib import Path
import sys,unittest,z3
sys.path.insert(0,str(Path(__file__).resolve().parent))


def state(**changes):
    values=dict(wb_valid=False,wb_slot=0,sum=0,accumulate=False,forward=False,
        forward_data=0,q=11,recent_valid=False,recent_slot=0,recent_data=0,
        result_valid=False,bypass=False,bypass_data=0,held=0)
    values.update(changes)
    result={name:z3.BoolVal(value) if type(value) is bool else z3.BitVecVal(value,19 if name=='sum' else 4 if name.endswith('_slot') else 32)
            for name,value in values.items()}
    result['memory']=z3.K(z3.BitVecSort(4),z3.BitVecVal(11,32))
    return result


def inputs(**changes):
    values=dict(array_valid=False,array_slot=0,array_sum=0,array_accumulate=False,read_valid=False,read_slot=0)
    values.update(changes)
    return {name:z3.BoolVal(value) if type(value) is bool else z3.BitVecVal(value,19 if name=='array_sum' else 4)
            for name,value in values.items()}


def integer(value):return z3.simplify(value).as_long()


class OutputMemoryServiceTest(unittest.TestCase):
    def test_history_theorem_proves_reset_induction_serialization_and_no_contention(self):
        from prove_tri_oracle_output_memory_service import prove_history
        result=prove_history()
        self.assertEqual({query['label'] for query in result['queries']},
            {'service_reset_basis','service_history_successor','service_serialized_pending_fold','service_no_macro_port_contention'})
        self.assertTrue(all(query['result']=='unsat' for query in result['queries']))
        self.assertFalse(result['universal_vendor_semantics_verified'])

    def test_scalar_archive_oracle_decodes_signed_lanes_and_masked_accumulation(self):
        from audit_tri_oracle_output_memory_models import scalar_commands
        result,dots=scalar_commands([0x0504fd02],[0xfe01],[0xf],
            [(0,0,0,0,False),(0,0,0,0,True)],rows=2,lanes=2,slots=2)
        self.assertEqual(dots,[[8,-6],[8,-6]])
        self.assertEqual(result,[[16,0xfffffff4],[0,0]])
        result,_=scalar_commands([0x0504fd02],[0xfe01],[0x5],[(0,0,0,0,False)],rows=2,lanes=2,slots=1)
        self.assertEqual(result,[[2,4]])

    def test_archived_native_outcome_cannot_confuse_expected_failure_with_pass(self):
        from audit_tri_oracle_output_memory_models import validate_native_outcome
        good=dict(state='passed',simulator='Cadence Xcelium',profile='capacity',implementation='routed44',
            negative_reference=False,elaborate_only=False,smoke_only=False,functional_simulation_completed=True,
            exit_status=0,native_exit_status=0,wrong_reference_rejected=False,raw_routed_clock_connections_preserved=True)
        log='GPU_CORE_CAPACITY_PASS commands=1024 sums=512 input_addresses=1024\nSimulation complete via $finish(1)\n'
        validate_native_outcome(good,log)
        with self.assertRaisesRegex(AssertionError,'archive native'):
            validate_native_outcome(good|dict(native_exit_status=2),log)
        bad=good|dict(negative_reference=True,native_exit_status=2,wrong_reference_rejected=True)
        failure='xmsim: *F,FATSEV\nGPU_CORE_REFERENCE_MISMATCH slot=0\nSimulation terminated via $fatal(1)\n'
        validate_native_outcome(bad,failure)
        with self.assertRaisesRegex(AssertionError,'archive native'):
            validate_native_outcome(bad,failure.replace('REFERENCE_MISMATCH','WATCHDOG'))

    def test_read_during_same_slot_write_returns_old_base_not_new_sum(self):
        from prove_tri_oracle_output_memory_service import service_step,output_data
        new,signals=service_step(state(wb_valid=True,wb_slot=3,sum=5),inputs(read_valid=True,read_slot=3),z3.BoolVal(True))
        self.assertEqual(integer(z3.Select(new['memory'],z3.BitVecVal(3,4))),5)
        self.assertEqual(integer(output_data(new)),11)
        self.assertTrue(z3.is_true(z3.simplify(signals['current_hit'])))

    def test_recent_hit_returns_cache_without_using_unrelated_memory_q(self):
        from prove_tri_oracle_output_memory_service import service_step,output_data
        new,signals=service_step(state(recent_valid=True,recent_slot=4,recent_data=11,q=99),
            inputs(read_valid=True,read_slot=4),z3.BoolVal(True))
        self.assertEqual(integer(output_data(new)),11)
        self.assertTrue(z3.is_false(z3.simplify(signals['read_enable'])))

    def test_external_miss_blocks_array_and_reads_requested_address(self):
        from prove_tri_oracle_output_memory_service import service_step,output_data
        old=state(q=99);old['memory']=z3.Store(old['memory'],z3.BitVecVal(2,4),z3.BitVecVal(23,32))
        new,signals=service_step(old,inputs(read_valid=True,read_slot=2,array_valid=True,array_slot=5,array_sum=7),z3.BoolVal(True))
        self.assertEqual(integer(output_data(new)),23)
        self.assertTrue(z3.is_false(z3.simplify(new['wb_valid'])))
        self.assertEqual(integer(signals['read_address']),2)

    def test_forwarding_chain_folds_next_partial_over_current_commit(self):
        from prove_tri_oracle_output_memory_service import service_step,writeback_data
        middle,signals=service_step(state(wb_valid=True,wb_slot=3,sum=5),
            inputs(array_valid=True,array_slot=3,array_sum=7,array_accumulate=True),z3.BoolVal(True))
        self.assertEqual(integer(z3.Select(middle['memory'],z3.BitVecVal(3,4))),5)
        self.assertEqual(integer(writeback_data(middle)),12)
        self.assertTrue(z3.is_false(z3.simplify(signals['read_enable'])))
        last,_=service_step(middle,inputs(),z3.BoolVal(True))
        self.assertEqual(integer(z3.Select(last['memory'],z3.BitVecVal(3,4))),12)

    def test_response_holds_when_prefetch_changes_memory_output(self):
        from prove_tri_oracle_output_memory_service import service_step,output_data
        new,_=service_step(state(result_valid=True,q=23,held=7),
            inputs(array_valid=True,array_slot=4,array_sum=9),z3.BoolVal(True))
        self.assertEqual(integer(new['q']),11)
        self.assertEqual(integer(output_data(new)),23)
        self.assertTrue(z3.is_false(z3.simplify(new['result_valid'])))

    def test_reset_retains_committed_memory_and_cancels_pending_response(self):
        from prove_tri_oracle_output_memory_service import service_step,output_data
        new,_=service_step(state(wb_valid=True,wb_slot=3,sum=5,result_valid=True,held=44),
            inputs(read_valid=True,read_slot=3,array_valid=True,array_sum=9),z3.BoolVal(False))
        self.assertEqual(integer(z3.Select(new['memory'],z3.BitVecVal(3,4))),11)
        self.assertEqual(integer(output_data(new)),0)
        self.assertTrue(z3.is_false(z3.simplify(new['wb_valid'])))

    def test_mixed_history_matches_independent_prewrite_memory_and_serial_fold(self):
        from prove_tri_oracle_output_memory_service import service_step,output_data,logical_memory
        current=state();memory=[11]*16;serialized=memory.copy();last_response=0
        accepted=reads=collisions=misses=resets=0
        for cycle in range(180):
            reset=cycle in (0,53,111);slot=(cycle*7+3)%16;read_slot=slot if cycle%4==0 else (cycle*3)%16
            offered=cycle%5!=1;read=cycle%3!=1;accumulate=cycle%4!=2
            signed_sum=(-1 if cycle%2 else 1)*(cycle*19+7)
            expected_response=0 if reset else memory[read_slot] if read else last_response
            previous_valid=z3.is_true(z3.simplify(current['wb_valid']))
            previous_slot=integer(current['wb_slot'])
            current_hit=previous_valid and previous_slot==read_slot
            recent_hit=z3.is_true(z3.simplify(current['recent_valid'])) and integer(current['recent_slot'])==read_slot
            external_miss=read and not current_hit and not recent_hit
            take=not reset and offered and not external_miss
            if reset:
                serialized=memory.copy();resets+=1
            else:
                if previous_valid:memory[previous_slot]=serialized[previous_slot]
                if take:
                    serialized[slot]=(signed_sum+(serialized[slot] if accumulate else 0))&0xffffffff
                    accepted+=1;collisions+=previous_valid and previous_slot==slot
                reads+=read;misses+=external_miss
            current,_=service_step(current,inputs(array_valid=offered,array_slot=slot,array_sum=signed_sum,
                array_accumulate=accumulate,read_valid=read,read_slot=read_slot),z3.BoolVal(not reset))
            current={key:z3.simplify(value) for key,value in current.items()}
            self.assertEqual(integer(output_data(current)),expected_response)
            self.assertEqual(z3.is_true(current['result_valid']),read and not reset)
            self.assertEqual([integer(z3.Select(current['memory'],z3.BitVecVal(i,4))) for i in range(16)],memory)
            self.assertEqual([integer(z3.Select(logical_memory(current),z3.BitVecVal(i,4))) for i in range(16)],serialized)
            last_response=expected_response
        self.assertGreater(accepted,20);self.assertGreater(reads,20);self.assertGreater(misses,20)
        self.assertEqual(resets,3)


if __name__=='__main__':unittest.main()
