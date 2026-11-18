"""Check hierarchy cutpoint identity, vector order and exact driver rejection."""
import importlib.util
from pathlib import Path
import unittest
import tempfile

SOURCE = Path(__file__).with_name('prove_tri_oracle_head_routing.py')


class HeadRoutingTests(unittest.TestCase):
    def engine(self):
        self.assertTrue(SOURCE.exists(), 'Head routing proof is not implemented')
        spec = importlib.util.spec_from_file_location('head_routing', SOURCE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def fixture(self):
        return {
            'top': b'''module top(clk,rst_n); input clk,rst_n; wire [3:0] req;
                wire [1:0] reply; wire hv,hr;
                sched s(.clk(clk),.rst_n(rst_n),.head_request(req),.head_response(reply));
                head h(.clk(clk),.rst_n(rst_n),.cfg_alpha({req[0],req[3],req[2],req[1]}),
                       .out_valid(hv),.cfg_ready(hr));
                assign reply = {hr,hv}; endmodule''',
            'sched': b'''module sched(clk,rst_n,head_request,head_response); input clk,rst_n;
                output [3:0] head_request; input [1:0] head_response; endmodule''',
            'head': b'''module head(clk,rst_n,cfg_alpha,out_valid,cfg_ready); input clk,rst_n;
                input [3:0] cfg_alpha; output out_valid,cfg_ready; endmodule''',
        }

    def test_each_vector_bit_keeps_its_real_concatenation_order(self):
        engine = self.engine(); bodies = self.fixture()
        checker = engine.HeadRoutes(bodies.__getitem__, set(bodies), {}, {}, 'top', 's', {0: 'h'})
        for bit, source in enumerate([1,2,3,0]):
            root = checker.trace('h', f'cfg_alpha[{bit}]')
            self.assertEqual(checker.graph.nodes[root], ('v', f'scheduler.head_request[{source}]'))
        self.assertEqual(checker.graph.nodes[checker.trace('s','head_response[0]')], ('v','head0.out_valid'))
        self.assertEqual(checker.graph.nodes[checker.trace('s','head_response[1]')], ('v','head0.cfg_ready'))

    def test_boundary_cuts_do_not_hide_missing_or_multiple_parent_drivers(self):
        engine = self.engine()
        for replacement in [b'', b'assign req[0] = 1\'b0;']:
            bodies = self.fixture()
            if not replacement:
                bodies['top'] = bodies['top'].replace(b'.head_request(req)', b'.head_request()')
            else:
                bodies['top'] = bodies['top'].replace(b'endmodule', replacement+b'endmodule')
            checker = engine.HeadRoutes(bodies.__getitem__, set(bodies), {}, {}, 'top', 's', {0:'h'})
            with self.assertRaisesRegex(AssertionError, 'driver'):
                checker.trace('h','cfg_alpha[3]')

    def test_hierarchy_input_with_a_driver_is_rejected(self):
        engine = self.engine(); bodies = self.fixture()
        bodies['top'] = bodies['top'].replace(b'wire [3:0] req;',b'input [3:0] req;').replace(b'top(clk,rst_n)',b'top(clk,rst_n,req)')
        checker = engine.HeadRoutes(bodies.__getitem__, set(bodies), {}, {}, 'top', 's', {0:'h'})
        with self.assertRaisesRegex(AssertionError, 'driver'):
            checker.trace('h','cfg_alpha[0]')

    def test_sibling_consuming_the_bus_does_not_require_its_unrelated_internals(self):
        engine=self.engine();bodies=self.fixture()
        bodies['unused']=b'module unused(data); input [3:0] data; reg q; always @* q = data[0]; endmodule'
        bodies['top']=bodies['top'].replace(b'endmodule',b'unused side(.data(req)); endmodule')
        checker=engine.HeadRoutes(bodies.__getitem__,set(bodies),{}, {},'top','s',{0:'h'})
        root=checker.trace('h','cfg_alpha[0]')
        self.assertEqual(checker.graph.nodes[root],('v','scheduler.head_request[1]'))

    def test_clock_library_includes_memory_consumers_and_rejects_missing_views(self):
        engine=self.engine()
        self.assertTrue(hasattr(engine,'routing_libraries'),'Complete route library loader is missing')
        with tempfile.TemporaryDirectory(dir=SOURCE.parent.parent/'.cache') as folder:
            sources={}
            for corner in ('tt','ss','ff'):
                paths=[]
                for index in range(7):
                    path=Path(folder)/f'{corner}_{index}.lib'
                    name='BUF' if index==0 else f'MEM{index}'
                    path.write_text(f'library(test) {{\ncapacitive_load_unit (1,pf);\ncell ({name}) {{\n pin (CLKW) {{\n direction : input;\n }}\n}}\n}}\n')
                    paths.append(path)
                sources[corner]=paths
                paths[0].write_text(paths[0].read_text()+'\ncell (FILL) {\n}\n')
            table=engine.routing_libraries(sources,{'BUF','FILL',*(f'MEM{i}' for i in range(1,7))})
            self.assertEqual(table['tt']['MEM6','CLKW'],{'direction':'input'})
            with self.assertRaisesRegex(AssertionError,'seven'):
                engine.routing_libraries({**sources,'tt':sources['tt'][:1]},{'BUF'})
            sources['ff'][-1].write_text(sources['ff'][-1].read_text().replace('direction : input','direction : output'))
            with self.assertRaisesRegex(AssertionError,'corners'):
                engine.routing_libraries(sources,{'BUF',*(f'MEM{i}' for i in range(1,7))})


if __name__ == '__main__':
    unittest.main()
