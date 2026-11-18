"""Do not invent input cuts or independent opposite FF polarities."""
from pathlib import Path
import sys
import unittest
import z3
sys.path.insert(0,str(Path(__file__).resolve().parent))
from prove_tri_oracle_tile_command_routes import CommandRoutes
from prove_tri_oracle_head_intensity import WordBridge

class CommandRoutesTest(unittest.TestCase):
    def fixture(self,**options):
        body=b'module m(d, q, qn);\ninput d;\noutput q, qn;\nF storage (.D(d),.Q(q),.QN(qn));\nendmodule\n'
        library={('F','D'):{'direction':'input'},('F','Q'):{'direction':'output','function':'IQ'},
                 ('F','QN'):{'direction':'output','function':'IQN'}}
        return CommandRoutes(lambda _:body,{'m'},library,{'F':{'ff':1}},'m',tile='',**options)

    def test_both_ff_polarities_describe_one_physical_bit(self):
        route=self.fixture();positive=route.trace('','q');negative=route.trace('','qn')
        bridge=WordBridge(route.graph);got,=bridge.convert([route.graph.operation('^',positive,negative)])
        solver=z3.Solver();solver.add(z3.Not(got));self.assertEqual(solver.check(),z3.unsat)

    def test_offpath_cut_cannot_replace_an_input(self):
        with self.assertRaisesRegex(AssertionError,'output'):
            self.fixture(offpath={'':{'d'}})

    def test_routed_word_preserves_declared_numeric_bit_order(self):
        from prove_tri_oracle_tile_command_routes import route_word
        body=b'module m(data);\ninput [3:0] data;\nendmodule\n'
        route=CommandRoutes(lambda _:body,{'m'},{},{},'m')
        bridge=WordBridge(route.graph)
        word=route_word(route,bridge,'','data',4,direction='input')
        solver=z3.Solver()
        solver.add(bridge.boolean('top.data[0]'),z3.Not(bridge.boolean('top.data[1]')),
                   bridge.boolean('top.data[2]'),z3.Not(bridge.boolean('top.data[3]')),word!=5)
        self.assertEqual(solver.check(),z3.unsat)

    def test_routed_word_rejects_wrong_width_or_direction(self):
        from prove_tri_oracle_tile_command_routes import route_word
        route=self.fixture();bridge=WordBridge(route.graph)
        with self.assertRaisesRegex(AssertionError,'width'):
            route_word(route,bridge,'','d',2,direction='input')
        with self.assertRaisesRegex(AssertionError,'direction'):
            route_word(route,bridge,'','q',1,direction='input')

    def test_owner_bridge_uses_actual_hierarchical_input_binding(self):
        from prove_tri_oracle_tile_command_capture import OwnerRouteBridge
        from prove_tri_oracle_head_ratio import ClassifierCone
        bodies={'top':b'module top(data, q);\ninput data;\noutput q;\nwire n;\nINV invert (.I(data),.ZN(n));\nchild u (.d(n),.q(q));\nendmodule\n',
                'child':b'module child(d, q);\ninput d;\noutput q;\nF storage (.D(d),.Q(q));\nendmodule\n'}
        library={('INV','I'):{'direction':'input'},('INV','ZN'):{'direction':'output','function':'!I'},
                 ('F','D'):{'direction':'input'},('F','Q'):{'direction':'output','function':'IQ'}}
        routes=CommandRoutes(bodies.__getitem__,set(bodies),library,{'F':{'ff':1}},'top')
        route_bridge=WordBridge(routes.graph)
        model=ClassifierCone(bodies['child'],library,{'F':{'ff':1}})
        owner=OwnerRouteBridge(model,routes,route_bridge,'u')
        got,=owner.convert([model.cone('d')])
        solver=z3.Solver();solver.add(got!=z3.Not(route_bridge.boolean('top.data')))
        self.assertEqual(solver.check(),z3.unsat)

    def test_driver_inventory_scans_each_context_only_once(self):
        route=self.fixture()
        module=route.module('m')
        class CountCells(dict):
            scans=0
            def items(self):
                self.scans+=1
                return super().items()
        module.cells=CountCells(module.cells)
        route.trace('','q');route.trace('','qn')
        self.assertEqual(module.cells.scans,1)

    def test_index_retains_multiple_driver_rejection(self):
        body=b'module m(d, q);\ninput d;\noutput q;\nassign q=d;\nF storage (.D(d),.Q(q));\nendmodule\n'
        route=self.fixture();route.body=lambda _:body;route.modules.clear()
        with self.assertRaisesRegex(AssertionError,'one command route driver'):
            route.trace('','q')

if __name__=='__main__':unittest.main()
