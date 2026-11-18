"""Accepted row products must retain identity through pipeline stalls and writes."""
from pathlib import Path
from collections import deque
import random,sys,unittest,z3
sys.path.insert(0,str(Path(__file__).resolve().parent))


def number(x):return z3.simplify(x).as_long()
def truth(x):return z3.is_true(z3.simplify(x))
def signed(x,width):return x-(1<<width) if x&(1<<(width-1)) else x


def empty_pipeline():
    return dict(valid=[z3.BoolVal(False)]*4,
        data=[[z3.BitVecVal(0,16+stage)]*(8>>stage) for stage in range(4)],
        slot=[z3.BitVecVal(0,4)]*4,accumulate=[z3.BoolVal(False)]*4)


def offer(products,slot=0,accumulate=False):
    return dict(products=[z3.BitVecVal(x,16) for x in products],slot=z3.BitVecVal(slot,4),accumulate=z3.BoolVal(accumulate))


class NumericPipelineHistoryTest(unittest.TestCase):
    def test_published_contract_roots_reject_replacement_contents(self):
        from prove_tri_oracle_numeric_pipeline_history import load_contract,CONTRACT_ROOTS
        root=Path(__file__).resolve().parents[1]
        for kind,(name,_) in CONTRACT_ROOTS.items():
            content=(root/name).read_bytes();self.assertIsInstance(load_contract(kind,content),dict)
            with self.subTest(kind=kind),self.assertRaisesRegex(AssertionError,'Numeric contract digest'):
                load_contract(kind,content+b'\n')

    def test_array_contract_rejects_body_or_name_substitution(self):
        from hashlib import sha256
        from prove_tri_oracle_numeric_pipeline_history import require_array_contract
        body=b'mapped-body';row=dict(array_module_sha256=sha256(body).hexdigest())
        certificates={kind:dict(arrays={'array0':row}) for kind in ('product','reduction','valid')}
        require_array_contract(body,'array0',certificates)
        with self.assertRaisesRegex(AssertionError,'Numeric array body'):
            require_array_contract(body+b'changed','array0',certificates)
        with self.assertRaisesRegex(AssertionError,'Numeric array name'):
            require_array_contract(body,'array1',certificates)

    def test_masked_products_keep_signed_minimum_and_lane_identity(self):
        from prove_tri_oracle_numeric_pipeline_history import masked_products
        a=[-128,-1,127,2,-3,4,5,6];b=[-128,127,-1,-3,4,-5,6,7]
        enabled=[True,True,False,True,True,False,True,True]
        actual=masked_products([z3.BitVecVal(x,8) for x in a],[z3.BitVecVal(x,8) for x in b],[z3.BoolVal(x) for x in enabled])
        self.assertEqual([signed(number(x),16) for x in actual],[16384,-127,0,-6,-12,0,30,42])

    def test_stall_holds_all_data_slots_and_valids(self):
        from prove_tri_oracle_numeric_pipeline_history import pipeline_step
        old=empty_pipeline();old['valid']=[z3.BoolVal(True)]*4
        old['data']=[[z3.BitVecVal(stage*31+i,16+stage) for i in range(8>>stage)] for stage in range(4)]
        old['slot']=[z3.BitVecVal(i+1,4) for i in range(4)]
        new,ready=pipeline_step(old,z3.BoolVal(True),z3.BoolVal(False),offer([7]*8,9,True),z3.BoolVal(True))
        self.assertFalse(truth(ready))
        for field in old:
            self.assertEqual(str(z3.simplify(z3.And(*[a==b for a,b in zip(old[field],new[field])]))) if field!='data' else
                [[number(x) for x in row] for row in new[field]],
                'True' if field!='data' else [[number(x) for x in row] for row in old[field]])

    def test_four_stage_bubble_stall_reset_trace_matches_integer_fifo(self):
        from prove_tri_oracle_numeric_pipeline_history import pipeline_step,masked_products
        current=empty_pipeline();expected=deque();rng=random.Random(701);accepted=completed=reset_drops=0
        for cycle in range(260):
            reset=cycle in (0,81,163);offered=cycle<240 and cycle%5!=2
            outgoing=cycle%9 not in (2,3,4,5) if cycle<240 else True
            old_valid=truth(current['valid'][3]);ready=not old_valid or outgoing
            if reset:reset_drops+=len(expected);expected.clear()
            elif old_valid and outgoing:
                wanted_sum,wanted_slot,wanted_acc=expected.popleft()
                self.assertEqual(signed(number(current['data'][3][0]),19),wanted_sum)
                self.assertEqual(number(current['slot'][3]),wanted_slot)
                self.assertEqual(truth(current['accumulate'][3]),wanted_acc);completed+=1
            a=[rng.randrange(-128,128) for _ in range(8)];b=[rng.randrange(-128,128) for _ in range(8)]
            enables=[rng.choice((False,True)) for _ in range(8)];slot=(cycle//3)%4;accumulate=cycle%7!=0
            products=masked_products([z3.BitVecVal(x,8) for x in a],[z3.BitVecVal(x,8) for x in b],[z3.BoolVal(x) for x in enables])
            incoming=dict(products=products,slot=z3.BitVecVal(slot,4),accumulate=z3.BoolVal(accumulate))
            if not reset and offered and ready:
                expected.append((sum(x*y for x,y,e in zip(a,b,enables) if e),slot,accumulate));accepted+=1
            current,_=pipeline_step(current,z3.BoolVal(offered),z3.BoolVal(outgoing),incoming,z3.BoolVal(not reset))
            current={key:[[z3.simplify(x) for x in row] for row in values] if key=='data' else
                         [z3.simplify(x) for x in values] for key,values in current.items()}
        self.assertFalse(expected);self.assertGreater(completed,75);self.assertGreater(reset_drops,0)
        self.assertEqual(accepted,completed+reset_drops)

    def test_pending_fold_applies_oldest_first_with_same_slot_overwrite(self):
        from prove_tri_oracle_numeric_pipeline_history import fold_pending
        memory=z3.K(z3.BitVecSort(4),z3.BitVecVal(10,32));state=empty_pipeline()
        state['valid']=[z3.BoolVal(True)]*4;state['slot']=[z3.BitVecVal(3,4)]*4
        state['accumulate']=[z3.BoolVal(True),z3.BoolVal(False),z3.BoolVal(True),z3.BoolVal(True)]
        ghosts=[[z3.BitVecVal(value,16)]+[z3.BitVecVal(0,16)]*7 for value in (7,5,-3,2)]
        # Oldest2 adds to10, then-3 =>9; overwrite5, then add7 =>12.
        result=fold_pending(memory,state,ghosts)
        self.assertEqual(number(z3.Select(result,z3.BitVecVal(3,4))),12)
        self.assertEqual(number(z3.Select(result,z3.BitVecVal(2,4))),10)

    def test_numeric_history_proves_stage_and_serial_memory_composition(self):
        from prove_tri_oracle_numeric_pipeline_history import prove_history
        result=prove_history()
        self.assertTrue(all(q['result']=='unsat' for q in result['queries']))
        self.assertIn('accepted_input_updates_ordered_pending_memory_fold',{q['label'] for q in result['queries']})
        self.assertFalse(result['input_memory_contents_verified'])

    def test_numeric_metadata_successors_equal_the_certified_queue_projection(self):
        from prove_tri_oracle_numeric_pipeline_history import proof_obligations
        label='certified_metadata_projection_matches_numeric_and_writeback_successors'
        obligations={name:(conditions,proposition) for name,conditions,proposition in proof_obligations()}
        self.assertIn(label,obligations,'Numeric history omits the certified metadata projection')
        conditions,proposition=obligations[label]
        solver=z3.Solver();solver.add(*conditions,z3.Not(proposition));self.assertEqual(solver.check(),z3.unsat)

    def test_displaced_pending_slot_is_rejected_by_the_metadata_projection(self):
        from prove_tri_oracle_numeric_pipeline_history import pipeline_step,proof_obligations
        def displaced(old,in_valid,out_ready,incoming,rst):
            return pipeline_step(old,in_valid,out_ready,dict(incoming,slot=old['slot'][0]),rst)
        label='certified_metadata_projection_matches_numeric_and_writeback_successors'
        obligations={name:(conditions,proposition) for name,conditions,proposition in proof_obligations(displaced)}
        self.assertIn(label,obligations,'Numeric history omits the certified metadata projection')
        conditions,proposition=obligations[label]
        solver=z3.Solver();solver.add(*conditions,z3.Not(proposition),z3.Bool('numeric.rst_n'),z3.Bool('numeric.in_valid'),
            z3.Bool('numeric.out_ready'),z3.BitVec('numeric.input_slot',4)==2,z3.BitVec('numeric.slot0',4)==1)
        self.assertEqual(solver.check(),z3.sat)

    def test_inverted_pending_accumulation_is_rejected_by_the_metadata_projection(self):
        from prove_tri_oracle_numeric_pipeline_history import pipeline_step,proof_obligations
        def inverted(old,in_valid,out_ready,incoming,rst):
            return pipeline_step(old,in_valid,out_ready,dict(incoming,accumulate=z3.Not(incoming['accumulate'])),rst)
        label='certified_metadata_projection_matches_numeric_and_writeback_successors'
        obligations={name:(conditions,proposition) for name,conditions,proposition in proof_obligations(inverted)}
        self.assertIn(label,obligations,'Numeric history omits the certified metadata projection')
        conditions,proposition=obligations[label]
        solver=z3.Solver();solver.add(*conditions,z3.Not(proposition),z3.Bool('numeric.rst_n'),z3.Bool('numeric.in_valid'),z3.Bool('numeric.out_ready'))
        self.assertEqual(solver.check(),z3.sat)

    def test_wrong_product_lane_order_has_a_stage_zero_counterexample(self):
        from prove_tri_oracle_numeric_pipeline_history import pipeline_step,proof_obligations
        def corrupt(old,in_valid,out_ready,incoming,rst):
            changed=dict(incoming,products=list(reversed(incoming['products'])))
            return pipeline_step(old,in_valid,out_ready,changed,rst)
        label,conditions,proposition=next(q for q in proof_obligations(corrupt) if q[0]=='pipeline_stage0_history_successor')
        solver=z3.Solver();solver.add(*conditions,z3.Not(proposition));self.assertEqual(solver.check(),z3.sat)

    def test_advancing_during_stall_cannot_move_the_reference_fifo(self):
        from prove_tri_oracle_numeric_pipeline_history import pipeline_step,proof_obligations
        def corrupt(old,in_valid,out_ready,incoming,rst):return pipeline_step(old,in_valid,z3.BoolVal(True),incoming,rst)
        _,conditions,proposition=next(q for q in proof_obligations(corrupt) if q[0]=='pipeline_ready_matches_available_output')
        solver=z3.Solver();solver.add(*conditions,z3.Not(proposition));self.assertEqual(solver.check(),z3.sat)

    def test_zero_extension_has_an_activated_negative_product_counterexample(self):
        from prove_tri_oracle_numeric_pipeline_history import pipeline_step,proof_obligations
        def corrupt(old,in_valid,out_ready,incoming,rst):
            new,ready=pipeline_step(old,in_valid,out_ready,incoming,rst)
            wrong=z3.ZeroExt(1,old['data'][0][0])+z3.ZeroExt(1,old['data'][0][1])
            new['data'][1][0]=z3.If(z3.And(ready,old['valid'][0]),wrong,old['data'][1][0])
            return new,ready
        _,conditions,proposition=next(q for q in proof_obligations(corrupt) if q[0]=='pipeline_stage1_history_successor')
        solver=z3.Solver();solver.add(*conditions,z3.Not(proposition),z3.Bool('numeric.rst_n'),z3.Bool('numeric.out_ready'),
            z3.Bool('numeric.valid0'),z3.BitVec('numeric.data0.0',16)==0xffff,z3.BitVec('numeric.data0.1',16)==0)
        self.assertEqual(solver.check(),z3.sat)

    def test_collision_heavy_input_to_memory_trace_matches_integer_serial_reference(self):
        from prove_tri_oracle_numeric_pipeline_history import pipeline_step,ghost_step,fold_pending
        from prove_tri_oracle_output_memory_service import service_step,logical_memory,output_data
        from test_tri_oracle_output_memory_service_logic import state as memory_state
        pipe=empty_pipeline();service=memory_state();ghost=[[z3.BitVecVal(0,16)]*8 for _ in range(4)]
        committed=[11]*16;serialized=committed.copy();pending=None;queued=deque();latest=None;last_response=0
        accepted=completed=collisions=misses=dropped=0;rng=random.Random(991)
        for cycle in range(330):
            reset=cycle in (0,101,207);in_valid=cycle<300 and cycle%6!=4
            read_valid=cycle>30 and cycle%5==2;read_slot=(cycle*7)%16
            hit=pending is not None and pending[0]==read_slot
            miss=read_valid and not hit and latest!=read_slot
            out_ready=not miss;ready=not truth(pipe['valid'][3]) or out_ready
            self.assertEqual(truth(service['wb_valid']),pending is not None)
            response=0 if reset else committed[read_slot] if read_valid else last_response
            request=dict(array_valid=pipe['valid'][3],array_slot=pipe['slot'][3],array_sum=pipe['data'][3][0],
                array_accumulate=pipe['accumulate'][3],read_valid=z3.BoolVal(read_valid),read_slot=z3.BitVecVal(read_slot,4))
            new_service,signals=service_step(service,request,z3.BoolVal(not reset))
            self.assertEqual(truth(signals['array_out_ready']),out_ready)
            if reset:
                dropped+=len(queued)+(pending is not None);queued.clear();pending=None;latest=None
                serialized=committed.copy()
            else:
                if pending is not None:
                    slot,total,acc=pending;committed[slot]=(total+(committed[slot] if acc else 0))&0xffffffff;latest=slot;completed+=1
                pending=None
                if truth(pipe['valid'][3]) and out_ready:
                    slot,total,acc=queued.popleft()
                    self.assertEqual(number(pipe['slot'][3]),slot)
                    self.assertEqual(signed(number(pipe['data'][3][0]),19),total)
                    self.assertEqual(truth(pipe['accumulate'][3]),acc)
                    pending=(slot,total,acc)
                collisions+=truth(signals['accepted_array']) and truth(signals['collision']);misses+=miss
            values=[rng.randrange(-128,128)*rng.randrange(-128,128) if rng.randrange(4)!=0 else 0 for _ in range(8)]
            slot=(cycle//5)%3;accumulate=cycle%7!=0;incoming=offer(values,slot,accumulate)
            if not reset and in_valid and ready:
                total=sum(values);queued.append((slot,total,accumulate));accepted+=1
                serialized[slot]=(total+(serialized[slot] if accumulate else 0))&0xffffffff
            new_pipe,_=pipeline_step(pipe,z3.BoolVal(in_valid),z3.BoolVal(out_ready),incoming,z3.BoolVal(not reset))
            ghost=ghost_step(ghost,pipe['valid'],z3.BoolVal(ready),z3.BoolVal(in_valid),incoming['products'])
            ghost=[[z3.simplify(x) for x in row] for row in ghost]
            pipe={key:[[z3.simplify(x) for x in row] for row in value] if key=='data' else [z3.simplify(x) for x in value]
                  for key,value in new_pipe.items()}
            service={key:z3.simplify(value) for key,value in new_service.items()};last_response=response
            self.assertEqual(number(output_data(service)),response)
            self.assertEqual([number(z3.Select(service['memory'],z3.BitVecVal(i,4))) for i in range(16)],committed)
            folded=fold_pending(logical_memory(service),pipe,ghost)
            self.assertEqual([number(z3.Select(folded,z3.BitVecVal(i,4))) for i in range(16)],serialized)
        self.assertFalse(queued);self.assertIsNone(pending)
        self.assertGreater(collisions,40);self.assertGreater(misses,30);self.assertGreater(dropped,0)
        self.assertEqual(accepted,completed+dropped)


if __name__=='__main__':unittest.main()
