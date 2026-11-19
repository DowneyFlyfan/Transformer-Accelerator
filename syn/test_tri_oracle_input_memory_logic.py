"""Compiled input-memory ports must retain physical bit and mask identity."""
from pathlib import Path
import sys,unittest,z3
sys.path.insert(0,str(Path(__file__).resolve().parent))


def library_fixture():
    types=[];buses=[]
    for name,width in [('Q',128),('D',128),('A',5),('BWEB',128)]:
        types.append(f'type(t_{name}) {{ base_type:array; data_type:bit; bit_width:{width}; bit_from:{width-1}; bit_to:0; downto:true; }}')
        direction='output' if name=='Q' else 'input'
        buses.append(f'bus({name}) {{ bus_type:t_{name}; direction:{direction}; pin({name}[{width-1}:0]) {{ }} }}')
    return '\n'.join(types)+'\ncell(SRAM) {\n'+'\n'.join(buses)+'\n}'


class InputMemoryLogicTest(unittest.TestCase):
    def test_pinned_inventory_rejects_conflicting_predecessor_sources(self):
        from prove_tri_oracle_input_memory_history import merge_pinned_inputs
        self.assertEqual(merge_pinned_inputs({'source.py':'a'},{'source.py':'a','root.json':'b'}),{'source.py':'a','root.json':'b'})
        with self.assertRaisesRegex(AssertionError,'Conflicting pinned input'):
            merge_pinned_inputs({'source.py':'a'},{'source.py':'changed'})

    def test_commented_bus_and_pin_do_not_supply_real_liberty_declarations(self):
        from tri_oracle_input_memory_routes import memory_bus_view
        text=library_fixture();bus=next(line for line in text.splitlines() if line.startswith('bus(Q)'))
        pin='pin(Q[127:0]) { }'
        for source in (text.replace(bus,'/* '+bus+' */'),text.replace(pin,'/* '+pin+' */')):
            with self.subTest(source=source),self.assertRaisesRegex(AssertionError,'declaration'):
                memory_bus_view(source,'SRAM',data_width=128,address_width=5,masked=True)

    def test_nested_and_quoted_groups_do_not_replace_direct_liberty_declarations(self):
        from tri_oracle_input_memory_routes import memory_bus_view
        text=library_fixture();bus=next(line for line in text.splitlines() if line.startswith('bus(Q)'))
        for replacement in ('timing() { '+bus+' }','description:"'+bus+'";',bus.replace('bus(Q)','bus(""Q"")')):
            with self.subTest(replacement=replacement),self.assertRaisesRegex(AssertionError,'declaration'):
                memory_bus_view(text.replace(bus,replacement),'SRAM',data_width=128,address_width=5,masked=True)
        wrapped='library(real) { '+text.replace('cell(SRAM) {','cell(SRAM) { description:"{ /* marker */ bus(fake) {} }";')+' }'
        table=memory_bus_view(wrapped,'SRAM',data_width=128,address_width=5,masked=True)
        self.assertEqual(table['SRAM','Q[127:0]'],{'direction':'output'})

    def test_snapshot_induction_covers_stalls_bank_changes_and_writes(self):
        from prove_tri_oracle_input_memory_history import prove_input_snapshot_history
        proof=prove_input_snapshot_history()
        self.assertEqual({row['label'] for row in proof['queries']},{
            'input_reset_drops_pending_without_initializing_memory',
            'accepted_command_captures_preedge_memory_words',
            'pending_snapshot_history_successor',
            'parent_bank0_commands_preserve_bank0_selection_history',
            'processing_array_consumes_previous_snapshot_before_new_reads'})
        self.assertTrue(all(row['result']=='unsat' for row in proof['queries']))

    def test_write_that_corrupts_prefetched_q_has_a_stalled_command_counterexample(self):
        from prove_tri_oracle_input_memory_history import memory_step,input_snapshot_step,input_snapshot_obligations
        def bad_memory(memory,q,ce_n,we_n,address,data,bit_mask=None):
            new=memory_step(memory,q,ce_n,we_n,address,data,bit_mask)
            new['q']=z3.If(new['write'],data,new['q'])
            return new
        def advance(old,request,ready,rst):
            return input_snapshot_step(old,request,ready,rst,advance_memory=bad_memory)
        queries,case=input_snapshot_obligations(advance)
        _,conditions,claim=next(row for row in queries if row[0]=='pending_snapshot_history_successor')
        solver=z3.SolverFor('QF_AUFBV');solver.add(*conditions,z3.Not(claim),
            case['old']['pending'],z3.Not(case['ready']),case['rst'],
            z3.Not(case['request']['weights']['ce_n']),z3.Not(case['request']['weights']['we_n']))
        self.assertEqual(solver.check(),z3.sat)

    def test_wrong_selected_activation_bank_has_an_accepted_command_counterexample(self):
        from prove_tri_oracle_input_memory_history import input_snapshot_step,input_snapshot_obligations
        def advance(old,request,ready,rst):
            new=input_snapshot_step(old,request,ready,rst);new['bank']=z3.Not(new['bank']);return new
        queries,case=input_snapshot_obligations(advance)
        _,conditions,claim=next(row for row in queries if row[0]=='accepted_command_captures_preedge_memory_words')
        solver=z3.SolverFor('QF_AUFBV');solver.add(*conditions,z3.Not(claim),case['request']['accepted'],case['request']['bank'])
        self.assertEqual(solver.check(),z3.sat)

    def test_residual_controller_is_optional_only_with_its_complete_interface(self):
        from types import SimpleNamespace
        from prove_tri_oracle_input_memory_history import input_controller_contexts
        cells={name:('mapped_controller',{}) for name in ('input_owner','grouped_input_banks')}
        native=SimpleNamespace(cells=cells,directions={})
        self.assertEqual(input_controller_contexts(native),('input_owner','grouped_input_banks'))
        residual={name:'input' for name in ('residual_lease','residual_ce_n','residual_we_n','residual_addr','residual_d')}
        residual['residual_q']='output'
        shared=SimpleNamespace(cells=dict(cells,residual_input_bank_lease=('mapped_mux',{})),directions=residual)
        self.assertEqual(input_controller_contexts(shared),('input_owner','grouped_input_banks','residual_input_bank_lease'))

    def test_orphaned_residual_port_or_missing_mux_interface_is_rejected(self):
        from types import SimpleNamespace
        from prove_tri_oracle_input_memory_history import input_controller_contexts
        cells={name:('mapped_controller',{}) for name in ('input_owner','grouped_input_banks')}
        bad=[SimpleNamespace(cells=cells,directions={'residual_lease':'input'}),
             SimpleNamespace(cells=dict(cells,residual_input_bank_lease=('mapped_mux',{})),directions={})]
        for module in bad:
            with self.subTest(module=module),self.assertRaisesRegex(AssertionError,'Residual controller interface'):
                input_controller_contexts(module)

    def test_masked_write_changes_memory_but_retains_prefetched_q(self):
        from prove_tri_oracle_input_memory_history import memory_step
        memory=z3.K(z3.BitVecSort(5),z3.BitVecVal(0x1122,16));q=z3.BitVecVal(0x55cc,16)
        new=memory_step(memory,q,z3.BoolVal(False),z3.BoolVal(False),z3.BitVecVal(3,5),
            z3.BitVecVal(0xaabb,16),z3.BitVecVal(0xff00,16))
        self.assertEqual(z3.simplify(z3.Select(new['memory'],z3.BitVecVal(3,5))).as_long(),0x11bb)
        self.assertEqual(z3.simplify(new['q']).as_long(),0x55cc)
        self.assertEqual(z3.simplify(z3.Select(new['memory'],z3.BitVecVal(4,5))).as_long(),0x1122)

    def test_disabled_memory_holds_state_even_with_write_selected(self):
        from prove_tri_oracle_input_memory_history import memory_step
        memory=z3.K(z3.BitVecSort(5),z3.BitVecVal(0x1122,16));q=z3.BitVecVal(0x55cc,16)
        new=memory_step(memory,q,z3.BoolVal(True),z3.BoolVal(False),z3.BitVecVal(3,5),z3.BitVecVal(0xaabb,16))
        self.assertTrue(z3.is_true(z3.simplify(new['memory']==memory)))
        self.assertEqual(z3.simplify(new['q']).as_long(),0x55cc)

    def test_pending_operand_snapshot_survives_later_writes_until_a_new_read(self):
        from prove_tri_oracle_input_memory_history import memory_step
        address=z3.BitVecVal(3,5);memory=z3.K(z3.BitVecSort(5),z3.BitVecVal(11,16));q=z3.BitVecVal(0,16)
        read=memory_step(memory,q,z3.BoolVal(False),z3.BoolVal(True),address,z3.BitVecVal(0,16))
        written=memory_step(read['memory'],read['q'],z3.BoolVal(False),z3.BoolVal(False),address,z3.BitVecVal(99,16))
        self.assertEqual(z3.simplify(written['q']).as_long(),11)
        self.assertEqual(z3.simplify(z3.Select(written['memory'],address)).as_long(),99)
        later=memory_step(written['memory'],written['q'],z3.BoolVal(False),z3.BoolVal(True),address,z3.BitVecVal(0,16))
        self.assertEqual(z3.simplify(later['q']).as_long(),99)

    def test_bus_direction_is_inherited_without_losing_width_or_mask(self):
        from tri_oracle_input_memory_routes import memory_bus_view
        table=memory_bus_view(library_fixture(),'SRAM',data_width=128,address_width=5,masked=True)
        self.assertEqual(table['SRAM','Q[127:0]'],{'direction':'output'})
        self.assertEqual(table['SRAM','A[4:0]'],{'direction':'input'})
        self.assertEqual(table['SRAM','BWEB[127:0]'],{'direction':'input'})
        self.assertEqual(len(table),4)

    def test_wrong_or_conflicting_bus_direction_is_rejected(self):
        from tri_oracle_input_memory_routes import memory_bus_view
        text=library_fixture()
        bad=[text.replace('direction:output','direction:input'),
             text.replace('pin(Q[127:0]) { }','pin(Q[127:0]) { direction:inout; }')]
        for source in bad:
            with self.subTest(source=source),self.assertRaisesRegex(AssertionError,'memory bus direction'):
                memory_bus_view(source,'SRAM',data_width=128,address_width=5,masked=True)

    def test_address_and_bitmask_shapes_cannot_be_truncated(self):
        from tri_oracle_input_memory_routes import memory_bus_view
        text=library_fixture()
        bad=[text.replace('pin(A[4:0])','pin(A[3:0])'),text.replace('pin(BWEB[127:0])','pin(BWEB[0:127])'),
             text.replace('bit_width:5','bit_width:4'),text.replace('downto:true','downto:false',1)]
        for source in bad:
            with self.subTest(source=source),self.assertRaisesRegex(AssertionError,'memory bus (type|pin range)'):
                memory_bus_view(source,'SRAM',data_width=128,address_width=5,masked=True)

    def test_tristate_behavior_is_not_silently_cut_as_known_memory_data(self):
        from tri_oracle_input_memory_routes import memory_bus_view
        text=library_fixture()
        for source in [text.replace('direction:output;','direction:output; three_state:1;'),
                       text.replace('pin(Q[127:0]) { }','pin(Q[127:0]) { three_state:enable; }')]:
            with self.subTest(source=source),self.assertRaisesRegex(AssertionError,'memory bus.*three.state'):
                memory_bus_view(source,'SRAM',data_width=128,address_width=5,masked=True)


if __name__=='__main__':unittest.main()
