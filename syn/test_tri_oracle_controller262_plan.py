"""Unsafe, asynchronous and cross-boundary nets must not enter an enable plan."""
import unittest
import io
from tri_oracle_controller262_plan import select_enable_nets, read_native_nets


def row(controller='unit/implementation',suffix='a'):
    pins=[f'{controller}/{suffix}_reg[{i}]/E' for i in range(128)]
    return dict(constant='no_constant',power='false',ground='false',
        driver_pins='{'+controller+'/'+suffix+'/ZN}',driver_ports='',
        load_pins=' '.join('{'+pin+'}' for pin in pins),load_ports='')


class SelectionTests(unittest.TestCase):
    def test_native_synthesized_colon_names_remain_reachable(self):
        candidate=row();candidate['load_pins']+=' unit/implementation/slice:op/A1'
        got=select_enable_nets([candidate],{'unit/implementation'})
        self.assertEqual(len(got),1)
        self.assertIn('unit/implementation/slice:op/A1',got[0]['pins'])

    def test_large_clock_field_can_be_read_and_excluded(self):
        text='constant\tpower\tground\tdriver_pins\tdriver_ports\tload_pins\tload_ports\n'
        text+='no_constant\tfalse\tfalse\t\tclock\t'+'a'*131073+'\t\n'
        rows=list(read_native_nets(io.StringIO(text)))
        self.assertEqual(len(rows),1)
        self.assertEqual(len(rows[0]['load_pins']),131073)
        self.assertEqual(select_enable_nets(rows,{'unit/implementation'}),[])

    def test_invalid_native_header_or_row_width_is_rejected(self):
        for text in ['driver\tloads\n', 'constant\tpower\tground\tdriver_pins\tdriver_ports\tload_pins\tload_ports\nshort\trow\n']:
            with self.subTest(text=text),self.assertRaises(ValueError):
                list(read_native_nets(io.StringIO(text)))

    def test_all_eligible_nets_are_kept_in_stable_driver_order(self):
        a,b=row(suffix='a'),row(suffix='b')
        got=select_enable_nets([b,a],{'unit/implementation'})
        self.assertEqual([x['driver'] for x in got],['unit/implementation/a/ZN','unit/implementation/b/ZN'])
        self.assertEqual([len(x['pins']) for x in got],[128,128])
        self.assertEqual(got[0]['pins'][0],'unit/implementation/a_reg[0]/E')
        self.assertEqual(got[0]['controller'],'unit/implementation')

    def test_power_constants_ports_and_multiple_drivers_are_excluded(self):
        for key,value in [('constant','0'),('power','true'),('ground','true'),
                          ('driver_ports','input'),('load_ports','output'),
                          ('driver_pins','unit/implementation/a/ZN unit/implementation/b/ZN')]:
            candidate=row();candidate[key]=value
            with self.subTest(key=key):
                self.assertEqual(select_enable_nets([candidate],{'unit/implementation'}),[])
        self.assertEqual(select_enable_nets([row('other/implementation')],{'unit/implementation'}),[])

    def test_async_clock_and_cross_hierarchy_loads_are_excluded(self):
        for pin in ['unit/implementation/reset/CDN','unit/implementation/flop/CP','other/flop/E']:
            candidate=row();candidate['load_pins']+=' {'+pin+'}'
            with self.subTest(pin=pin):
                self.assertEqual(select_enable_nets([candidate],{'unit/implementation'}),[])

    def test_duplicate_sinks_or_duplicate_candidate_drivers_are_rejected(self):
        candidate=row();candidate['load_pins']+=' {unit/implementation/a_reg[0]/E}'
        with self.assertRaises(ValueError):select_enable_nets([candidate],{'unit/implementation'})
        with self.assertRaises(ValueError):select_enable_nets([row(),row()],{'unit/implementation'})

    def test_small_or_data_only_nets_are_not_enable_candidates(self):
        small=row();small['load_pins']=' '.join(small['load_pins'].split()[:127])
        data=row();data['load_pins']=data['load_pins'].replace('/E}','/A1}')
        self.assertEqual(select_enable_nets([small,data],{'unit/implementation'}),[])

    def test_unserializable_candidate_pins_are_rejected(self):
        for pins in ['{unit/implementation/bad pin/E}', '{unit/implementation/flop/E', '"unit/implementation/flop/E"']:
            candidate=row();candidate['load_pins']=pins
            with self.subTest(pins=pins),self.assertRaises(ValueError):
                select_enable_nets([candidate],{'unit/implementation'})


if __name__=='__main__':unittest.main()
