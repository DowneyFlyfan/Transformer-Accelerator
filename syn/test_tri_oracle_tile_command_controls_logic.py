"""Faults must change exactly the declared mapped connection bit."""
from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parent))
from prove_tri_oracle_parent_reset import Module

class CommandControlsTest(unittest.TestCase):
    def test_one_observed_keep_bit_changes_without_reordering_other_bits(self):
        from prove_tri_oracle_tile_command_controls import replace_bus_bit
        module=Module(b'module m(bits);\ninput [2559:0] bits;\nendmodule\n')
        for index in (0,225,2559):
            changed=module.expression(replace_bus_bit('bits',2560,index,"1'b0"))
            wanted=tuple("1'b0" if bit==index else f'bits[{bit}]' for bit in range(2559,-1,-1))
            self.assertEqual(changed,wanted)

    def test_corruption_rejects_bit_outside_the_actual_bus(self):
        from prove_tri_oracle_tile_command_controls import replace_bus_bit
        for index in (-1,2560):
            with self.assertRaisesRegex(AssertionError,'outside'):
                replace_bus_bit('bits',2560,index,"1'b0")

    def test_actual_parenthesized_selector_inverter_is_accepted(self):
        from prove_tri_oracle_tile_command_controls import selector_inverter_pin
        self.assertEqual(selector_inverter_pin('(!I)'),'I')
        with self.assertRaisesRegex(AssertionError,'inverter'):
            selector_inverter_pin('I')

if __name__=='__main__':unittest.main()
