"""Native flat and nested core paths must produce real simulator observers."""
import unittest

from run_tri_oracle_optimized_parent89 import core_bindings


class BindingTests(unittest.TestCase):
    def fixture(self):
        return ['tri_oracle_sram_memory_compute \\fabric/clusters['+str(c)+'].unit/cluster/implementation/cores['+str(k)+'] (.rst_n(r),.cmd_valid(v),.cmd_ready(q));'
                for c in range(5) for k in range(4)]

    def test_flat_native_identifiers_remain_single_identifiers(self):
        rows=core_bindings('module tri_oracle_predicted_fabric();'+''.join(self.fixture())+'endmodule')
        self.assertEqual(len(rows),20)
        self.assertEqual(rows[0],(0,'dut.\\fabric/clusters[0].unit/cluster/implementation/cores[0] '))
        self.assertEqual(rows[-1][0],19)

    def test_nested_native_identifiers(self):
        source='module tri_oracle_predicted_fabric(); child fabric(); endmodule\nmodule child();'
        source+=''.join(x.replace('\\fabric/','\\') for x in self.fixture())+'endmodule'
        rows=core_bindings(source)
        self.assertEqual(rows[0][1],'dut.fabric.\\clusters[0].unit/cluster/implementation/cores[0] ')

    def test_missing_core_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'20 original cores'):
            core_bindings('module tri_oracle_predicted_fabric();'+''.join(self.fixture()[:-1])+'endmodule')

    def test_duplicate_logical_core_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'Duplicate logical core'):
            core_bindings('module tri_oracle_predicted_fabric();'+''.join(self.fixture()+self.fixture()[:1])+'endmodule')

    def test_missing_observed_port_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'observable ports'):
            core_bindings(('module tri_oracle_predicted_fabric();'+''.join(self.fixture())+'endmodule').replace('.cmd_ready(q)',''))


if __name__=='__main__': unittest.main()
