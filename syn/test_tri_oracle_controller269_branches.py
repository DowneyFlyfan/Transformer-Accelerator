"""A branch repair must keep external and clock/reset connections intact."""
import unittest
from tri_oracle_controller269_branches import select_local_branches, plan_at_driver


def signal_row(driver='unit/implementation/error_reg/Q'):
    return dict(constant='no_constant',power='false',ground='false',driver_pins=driver,
                driver_ports='',load_ports='',load_pins=' '.join(f'unit/implementation/g{i}/B1' for i in range(128)))


class LocalBranchTests(unittest.TestCase):
    def test_sequential_control_with_one_external_load_gets_only_local_branch(self):
        row=signal_row();row['load_pins']+=' parent/error_buffer/I'
        got=select_local_branches([row],{'unit/implementation'})
        self.assertEqual(len(got),1)
        self.assertEqual(got[0]['driver'],'unit/implementation/error_reg/Q')
        self.assertEqual(len(got[0]['pins']),128)
        self.assertEqual(got[0]['remaining'],['parent/error_buffer/I'])
        self.assertEqual(got[0]['original_loads'],129)

    def test_generic_combinational_control_does_not_require_enable_pins(self):
        got=select_local_branches([signal_row('unit/implementation/and_gate/Z')],{'unit/implementation'})
        self.assertEqual(len(got),1)
        self.assertEqual(got[0]['remaining'],[])

    def test_clock_and_async_reset_roots_are_excluded_even_with_data_loads(self):
        for pin in ['unit/implementation/flop/CP','parent/flop/CDN','parent/flop/SDN','parent/gate/CLK']:
            row=signal_row();row['load_pins']+=' '+pin
            with self.subTest(pin=pin):self.assertEqual(select_local_branches([row],{'unit/implementation'}),[])

    def test_ports_constants_power_multiple_drivers_and_small_local_branches_excluded(self):
        for key,value in [('constant','1'),('power','true'),('ground','true'),('driver_ports','input'),('load_ports','output'),('driver_pins','unit/implementation/a/Q unit/implementation/b/Q')]:
            row=signal_row();row[key]=value
            with self.subTest(key=key):self.assertEqual(select_local_branches([row],{'unit/implementation'}),[])
        row=signal_row();row['load_pins']=' '.join(row['load_pins'].split()[:127])+' parent/flop/D'
        self.assertEqual(select_local_branches([row],{'unit/implementation'}),[])

    def test_duplicate_original_sinks_and_ambiguous_roots_rejected(self):
        row=signal_row();row['load_pins']+=' unit/implementation/g0/B1'
        with self.assertRaises(ValueError):select_local_branches([row],{'unit/implementation'})
        with self.assertRaises(ValueError):select_local_branches([signal_row(),signal_row()],{'unit/implementation'})

    def test_root_is_at_driver_and_all_leaf_groups_remain_local(self):
        points=[(f'unit/g{i}/B1',float(i),0.) for i in range(128)]
        nodes=plan_at_driver(points,(1000.,500.))
        self.assertEqual(len(nodes),5)
        self.assertEqual((nodes[-1]['x'],nodes[-1]['y']),(1000.,500.))
        self.assertEqual({(n['x'],n['y']) for n in nodes[:-1]},{(15.5,0.),(47.5,0.),(79.5,0.),(111.5,0.)})
        self.assertEqual(sorted(p for n in nodes for p in n['pins']),sorted(p[0] for p in points))

    def test_invalid_driver_geometry_is_rejected(self):
        for location in [(float('nan'),0.),(0.,float('inf')),(1.,)]:
            with self.subTest(location=location),self.assertRaises(ValueError):plan_at_driver([('a/I',0.,0.)],location)


if __name__=='__main__':unittest.main()
