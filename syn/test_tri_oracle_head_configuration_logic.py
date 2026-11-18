"""Check enum-domain predicates, conservative tile cuts and coupled handshakes."""
import importlib.util
from pathlib import Path
import unittest

SOURCE = Path(__file__).with_name('prove_tri_oracle_head_configuration.py')


class HeadConfigurationTests(unittest.TestCase):
    def engine(self):
        self.assertTrue(SOURCE.exists(), 'Head configuration proof is not implemented')
        spec = importlib.util.spec_from_file_location('head_configuration', SOURCE)
        module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module

    def test_enum_membership_checks_every_code_including_illegal_seven(self):
        engine=self.engine()
        from prove_tri_oracle_packaged_products import BooleanGraph
        for allowed in [{1,5},{1,2},{2,3,4},{1,2,5,6},{4,6},set()]:
            graph=BooleanGraph();word=[graph.variable(f'b{bit}') for bit in range(3)]
            root=engine.member_bits(graph,word,allowed)
            for value in range(8):
                self.assertEqual(graph.evaluate([root],{f'b{bit}':(value>>bit)&1 for bit in range(3)}),[int(value in allowed)])
        with self.assertRaises(ValueError):engine.member_bits(graph,word,{8})

    def test_wide_tile_outputs_are_unconstrained_not_assumed_equal_to_inputs(self):
        engine=self.engine()
        from prove_tri_oracle_parent_reset import Module
        body=b'module parent(clk,rst_n,x,y,z); input clk,rst_n; input [1:0] x; output [1:0] y; output z; TILE tile(.a(x),.b(y)); BUF g(.I(y[0]),.Z(z)); endmodule'
        child=Module(b'module TILE(a,b); input [1:0] a; output [1:0] b; endmodule')
        library={('BUF','I'):{'direction':'input'},('BUF','Z'):{'direction':'output','function':'I'}}
        model=engine.ParentCone(body,library,{}, {'TILE':child});root=model.cone('z')
        self.assertEqual(model.graph.evaluate([root],{'y[0]':0}),[0])
        self.assertEqual(model.graph.evaluate([root],{'y[0]':1}),[1])

    def test_tile_width_mismatch_or_internal_input_driver_is_rejected(self):
        engine=self.engine()
        from prove_tri_oracle_parent_reset import Module
        child=Module(b'module TILE(a,b); input [1:0] a; output [1:0] b; endmodule')
        for outputs in ['y[0]','x']:
            body=f'module parent(clk,rst_n,x,y); input clk,rst_n; input [1:0] x; output [1:0] y; TILE tile(.a(x),.b({outputs})); endmodule'.encode()
            with self.assertRaises(AssertionError):engine.ParentCone(body,{}, {}, {'TILE':child})

    def test_acceptance_and_retirement_use_correlated_ready_valid(self):
        engine=self.engine()
        self.assertEqual(engine.abstract_successors(4,6,0,1),{(0,0)})
        self.assertEqual(engine.abstract_successors(4,6,1,0),{(4,6)})
        self.assertEqual(engine.abstract_successors(1,0,0,0),{(2,1),(2,6)})
        self.assertEqual(engine.abstract_successors(0,0,1,1),{(1,0),(5,0)})
        result=engine.transaction_invariant()
        self.assertTrue(result['at_most_one_local_accept_per_parent_transaction'])
        self.assertTrue(result['invalid_parent_configuration_creates_no_local_accept'])

    def test_verifier_rejects_report_outside_cache_before_reading_design(self):
        engine=self.engine()
        self.assertTrue(hasattr(engine,'verify'),'Reproducible configuration verifier is missing')
        with self.assertRaises(AssertionError):engine.verify(SOURCE.parent/'forbidden-report.json')

    def test_fault_injection_changes_only_the_selected_instance_input(self):
        engine=self.engine()
        self.assertTrue(hasattr(engine,'replace_instance_pin'),'Strict instance fault injector is missing')
        from prove_tri_oracle_head_ratio import ClassifierCone
        body=b'module top(a,b,y,z); input a,b; output y,z; BUF g(.I(a),.Z(y)); BUF g_extra(.I(b),.Z(z)); endmodule'
        changed=engine.replace_instance_pin(body,'g','I',b"1'b1")
        library={('BUF','I'):{'direction':'input'},('BUF','Z'):{'direction':'output','function':'I'}}
        model=ClassifierCone(changed,library,{})
        self.assertEqual(model.graph.evaluate([model.cone('y'),model.cone('z')],{'a':0,'b':0}),[1,0])
        self.assertEqual(model.graph.evaluate([model.cone('y'),model.cone('z')],{'a':0,'b':1}),[1,1])
        with self.assertRaises(AssertionError):engine.replace_instance_pin(body,'g','missing',b"1'b0")


if __name__=='__main__':unittest.main()
