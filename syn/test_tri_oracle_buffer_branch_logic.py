"""Accept intended escaped-instance rewires while rejecting real changes."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path.cwd()/'syn'))
from tri_oracle_buffer_branch_logic import prove_module


class LogicTests(unittest.TestCase):
    def circuit(self,escaped):
        name=br'\register[2]' if escaped else b'register2'
        canonical='register[2]' if escaped else 'register2'
        before=b'''module probe(a, clk, q);
  input a;
  input clk;
  output q;
  wire n;
  INVD18BWP12T40P140 driver (.I(a), .ZN(n));
  DFMQD1BWP12T40P140 '''+name+b''' (.CP(clk), .DA(a), .DB(a), .Q(q), .SA(n));
endmodule'''
        rewires={canonical:{'SA':('n','tri_load_repair_0_leaf0_wire')}}
        additions={'tri_load_repair_0_leaf0':('BUFFD12BWP12T40P140','n','tri_load_repair_0_leaf0_wire')}
        after=before.replace(b'.SA(n)',b'.SA(tri_load_repair_0_leaf0_wire)').replace(
            b'endmodule',b'  wire tri_load_repair_0_leaf0_wire;\n'
            b'  BUFFD12BWP12T40P140 tri_load_repair_0_leaf0 (.I(n), .Z(tri_load_repair_0_leaf0_wire));\nendmodule')
        return before,after,rewires,additions

    def test_intended_escaped_register_rewire_is_accepted(self):
        try:
            prove_module(*self.circuit(True))
        except AssertionError:
            self.fail('Verifier misclassifies the intended escaped-instance rewire as an unchanged cell')

    def test_ordinary_register_rewire_is_accepted(self):
        prove_module(*self.circuit(False))

    def test_extra_output_rewire_is_rejected(self):
        before,after,rewires,additions=self.circuit(True)
        with self.assertRaises(AssertionError):
            prove_module(before,after.replace(b'.Q(q)',b'.Q(a)'),rewires,additions)

    def test_wrong_buffer_input_is_rejected(self):
        before,after,rewires,additions=self.circuit(False)
        with self.assertRaises(AssertionError):
            prove_module(before,after.replace(b'.I(n)',b'.I(a)'),rewires,additions)

    def test_changed_original_driver_type_is_rejected(self):
        before,after,rewires,additions=self.circuit(True)
        with self.assertRaises(AssertionError):
            prove_module(before,after.replace(b'INVD18BWP12T40P140',b'INVD15BWP12T40P140'),rewires,additions)


    def test_unsupported_behavioral_statement_is_rejected(self):
        before,after,rewires,additions=self.circuit(False)
        with self.assertRaises(AssertionError):
            prove_module(before,after.replace(b'endmodule',b'always @* q = a;\nendmodule'),rewires,additions)

    def test_duplicate_pin_association_is_rejected(self):
        before,after,rewires,additions=self.circuit(False)
        with self.assertRaises(AssertionError):
            prove_module(before,after.replace(b'.SA(tri_load_repair_0_leaf0_wire)',
                b'.SA(tri_load_repair_0_leaf0_wire), .SA(n)'),rewires,additions)


if __name__=='__main__':
    unittest.main()
