"""Physical pin ordering and signed accumulation must agree with integer arithmetic."""
from pathlib import Path
import sys,tempfile,unittest,z3
sys.path.insert(0,str(Path(__file__).resolve().parent))


def memory_fixture(*,extra='',first_q='q0',input_q=False,web='web',reb='reb'):
    ports='clk,web,reb,address'+(',q0' if input_q else '')
    text=f'module core({ports});\ninput clk;\ninput web;\ninput reb;\ninput [3:0] address;\n'
    for bank in range(8):
        text+=f'{"input" if input_q and bank==0 else "wire"} [127:0] q{bank};\nwire [127:0] d{bank};\n'
        text+=f'SRAM \\outputs[{bank}]  (.CLKW(clk),.CLKR(clk),.AA(address),.AB(address),.WEB({web}),.REB({reb}),.D(d{bank}),.Q({first_q if bank==0 else f"q{bank}"}));\n'
    return (text+extra+'\nendmodule').encode()


def fixture_routes(body):
    from prove_tri_oracle_packaged_accumulators import AccumulatorRoutes
    library={('SRAM',pin):dict(direction=direction) for pin,direction in (
        ('Q[127:0]','output'),('D[127:0]','input'),('AA[3:0]','input'),('AB[3:0]','input'),
        ('CLKW','input'),('CLKR','input'),('WEB','input'),('REB','input'))}
    library.update({('INV','ZN'):dict(direction='output',function='!I'),('INV','I'):dict(direction='input')})
    return AccumulatorRoutes(lambda _:body,{'core'},library,{},'core',memory_master='SRAM')


class AccumulatorContractTest(unittest.TestCase):
    def test_signed19_sum_and_modulo32_wrap_with_both_sources(self):
        from prove_tri_oracle_packaged_accumulators import reference_writeback
        for bits,memory,forward,accumulate,bypass in (
            (1,0xffffffff,7,True,False),(0x7ffff,0,17,False,False),
            (0x40000,4,0xffffffff,True,True),(0x3ffff,9,0x7fffffff,True,True),
            (0x40000,999,888,False,True)):
            signed=(bits^(1<<18))-(1<<18)
            expected=(signed+((forward if bypass else memory) if accumulate else 0))&0xffffffff
            actual=reference_writeback(z3.BitVecVal(bits,19),z3.BitVecVal(memory,32),
                z3.BitVecVal(forward,32),z3.BoolVal(accumulate),z3.BoolVal(bypass))
            self.assertEqual(z3.simplify(actual).as_long(),expected)

    def test_physical_memory_words_preserve_aliases_and_bit_order(self):
        from prove_tri_oracle_packaged_accumulators import memory_pins
        from prove_tri_oracle_command_admission import parse_admission_module
        body=b'''module core(clk);
input clk;
wire [127:0] d;
wire [127:0] q;
wire [31:0] alias_word;
SRAM \\outputs[0]  (.CLKW(clk),.CLKR(clk),.AA(4'b0),.AB(4'b0),.WEB(clk),.REB(clk),.D({d[127:32],alias_word}),.Q(q));
endmodule'''
        module=parse_admission_module(body)
        pins=memory_pins(module,'SRAM',banks=1)
        self.assertEqual(pins['data_words'][0],tuple(f'alias_word[{bit}]' for bit in range(32)))
        self.assertEqual(pins['data_words'][3],tuple(f'd[{96+bit}]' for bit in range(32)))
        self.assertEqual(pins['output_words'][0],tuple(f'q[{bit}]' for bit in range(32)))

    def test_duplicate_physical_memory_output_is_rejected(self):
        from prove_tri_oracle_packaged_accumulators import memory_pins
        from prove_tri_oracle_command_admission import parse_admission_module
        body=b'''module core(clk);
input clk;
wire [127:0] d;
wire [127:0] q;
SRAM \\outputs[0]  (.CLKW(clk),.CLKR(clk),.AA(4'b0),.AB(4'b0),.WEB(clk),.REB(clk),.D(d),.Q({q[127:1],q[1]}));
endmodule'''
        with self.assertRaisesRegex(AssertionError,'Repeated memory output'):
            memory_pins(parse_admission_module(body),'SRAM',banks=1)

    def test_memory_bus_direction_requires_the_exact_liberty_range(self):
        from prove_tri_oracle_packaged_accumulators import memory_bus_direction
        library={('SRAM','Q[127:0]'):dict(direction='output'),('SRAM','D[127:0]'):dict(direction='input')}
        self.assertEqual(memory_bus_direction(library,'SRAM','Q'),'output')
        self.assertEqual(memory_bus_direction(library,'SRAM','D'),'input')
        with self.assertRaisesRegex(AssertionError,'Liberty bus'):
            memory_bus_direction({('SRAM','Q[63:0]'):dict(direction='output')},'SRAM','Q')

    def test_compiler_bus_inherits_direction_without_inventing_pin_properties(self):
        from prove_tri_oracle_packaged_accumulators import memory_bus_library,memory_bus_direction
        types='\n'.join(f'type({name}_type) {{base_type:array;data_type:bit;bit_width:{width};bit_from:{width-1};bit_to:0;downto:true;}}'
                        for name,width in (('Q',128),('D',128),('AA',4),('AB',4)))
        buses='\n'.join(f'bus({name}) {{bus_type:{name}_type;direction:{direction};pin({name}[{width-1}:0]) {{}}}}'
                        for name,width,direction in (('Q',128,'output'),('D',128,'input'),('AA',4,'input'),('AB',4,'input')))
        text=types+'\ncell(SRAM) {'+buses+'}'
        library=memory_bus_library(text,'SRAM')
        self.assertEqual(memory_bus_direction(library,'SRAM','Q'),'output')
        self.assertEqual(memory_bus_direction(library,'SRAM','AA'),'input')
        for corrupted in (text.replace('direction:output','direction:input'),
                          text.replace('bit_width:128','bit_width:64',1),
                          text.replace('pin(Q[127:0])','pin(Q[63:0])'),
                          text.replace('pin(Q[127:0]) {}','pin(Q[127:0]) {direction:inout;}'),
                          text.replace('pin(Q[127:0]) {}','pin(Q[127:0]) {internal_power() {} direction:inout;}'),
                          text.replace('pin(Q[127:0]) {}','pin(Q[127:0]) {direction:output;direction:output;}')):
            with self.subTest(corrupted=corrupted),self.assertRaisesRegex(AssertionError,'memory bus'):
                memory_bus_library(corrupted,'SRAM')
        commented=text.replace('pin(Q[127:0]) {}','pin(Q[127:0]) {/* direction:inout; */}')
        self.assertEqual(memory_bus_direction(memory_bus_library(commented,'SRAM'),'SRAM','Q'),'output')

    def test_fault_pin_expression_preserves_escaped_array_bit_identity(self):
        from prove_tri_oracle_packaged_accumulators import physical_pin_expression
        from prove_tri_oracle_command_admission import parse_admission_module
        module=parse_admission_module(b'''module core(clk);
input clk;
wire [3:0] \\slot_pipe[3] ;
wire [1:0] data;
endmodule''')
        wanted=('slot_pipe[3][2]','data[0]',"1'b0",'clk')
        expression=physical_pin_expression(module,wanted)
        self.assertEqual(module.expression(expression),wanted)
        expression=physical_pin_expression(module,reversed(wanted))
        self.assertEqual(module.expression(expression),tuple(reversed(wanted)))

    def test_source_manifest_includes_lazy_transitive_imports_and_handles_cycles(self):
        from prove_tri_oracle_packaged_accumulators import local_source_paths
        with tempfile.TemporaryDirectory(prefix='accumulator_source_test_',dir=Path(__file__).resolve().parents[1]/'.cache') as directory:
            root=Path(directory)
            for name,body in {'entry.py':'from second import value\nimport json\n',
                              'second.py':'def value():\n import third\n',
                              'third.py':'import entry\n','unused.py':'unused = True\n'}.items():
                (root/name).write_text(body)
            found=local_source_paths((root/'entry.py',),root)
            self.assertEqual({path.name for path in found},{'entry.py','second.py','third.py'})

    def test_memory_q_requires_its_exact_sole_physical_driver(self):
        routes=fixture_routes(memory_fixture())
        root=routes.trace('','q0[0]')
        self.assertEqual(routes.graph.nodes[root],('v','physical_memory.outputs[0].Q[0]'))
        for body in (memory_fixture(extra="assign q0[0] = 1'b0;"),
                     memory_fixture(extra="INV U (.I(1'b0),.ZN(q0[0]));"),
                     memory_fixture(input_q=True),memory_fixture(first_q="{q0[127:1],1'b0}")):
            with self.subTest(body=body),self.assertRaisesRegex(AssertionError,'Memory Q'):
                fixture_routes(body)

    def test_memory_enables_reject_multibit_verilog_truncation(self):
        for pin in ('web','reb'):
            with self.subTest(pin=pin),self.assertRaisesRegex(AssertionError,'memory '+pin.upper()+' width'):
                fixture_routes(memory_fixture(**{pin:'{'+pin+",1'b1}"}))

    def test_prior_arithmetic_records_require_successful_states_and_all_arrays(self):
        from prove_tri_oracle_packaged_accumulators import validate_prior_records
        import copy
        states={'product':'packaged_signed_product_next_states_exhaustively_verified',
                'reduction':'packaged_signed_reduction_next_states_symbolically_verified',
                'valid':'packaged_local_valid_transitions_and_clears_verified'}
        # Terminal state strings below are taken from the public prior contracts.
        prior={kind:dict(state=state,candidate_sha256='candidate',array_instances=20,
               arrays={f'array{i}':dict(array_module_sha256=str(i)) for i in range(20)}) for kind,state in states.items()}
        validate_prior_records(prior)
        for kind in states:
            for field,value in (('state','failed'),('array_instances',19),('candidate_sha256','other')):
                bad=copy.deepcopy(prior);bad[kind][field]=value
                with self.assertRaisesRegex(AssertionError,'prior arithmetic'):
                    validate_prior_records(bad)
        bad=copy.deepcopy(prior);bad['valid']['arrays']['array0']['array_module_sha256']='wrong'
        with self.assertRaisesRegex(AssertionError,'prior arithmetic'):validate_prior_records(bad)
        bad=copy.deepcopy(prior);bad['valid']['arrays']['other']=bad['valid']['arrays'].pop('array0')
        with self.assertRaisesRegex(AssertionError,'prior arithmetic'):validate_prior_records(bad)


if __name__=='__main__':unittest.main()
