"""Exercise reset ancestry through the optimizer's library-proven BUFFXD family."""
import os
from pathlib import Path
import re
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
TRACE = Path(os.environ.get('TRI_ORACLE_RESET104_TRACE',
                            ROOT/'syn/tri_oracle_registered_reset_trace102.tcl'))


class RegisteredReset104Tests(unittest.TestCase):
    def trace(self, master, output='Z', inputs='buffer/I buffer/Z'):
        # Native database access is replaced by a small connectivity graph;
        # the production ancestry walker itself runs unchanged in Tcl.
        script = r'''
proc get_db {object property} {
    global graph
    if {![dict exists $graph $object $property]} {error "MISSING_FIXTURE $object $property"}
    return [dict get $graph $object $property]
}
set graph [dict create \
    external [dict create .name rst_n .driver_pins {} .driver_ports rst_port] \
    registered [dict create .name registered .driver_pins flop/Q .driver_ports {}] \
    buffered [dict create .name buffered .driver_pins buffer/OUT .driver_ports {}] \
    flop/Q [dict create .inst flop .base_pin.name DFCNQD1BWP12T40P140/Q .name flop/Q] \
    flop [dict create .name child_rst_n_reg .base_cell.name DFCNQD1BWP12T40P140 .pins {flop/Q flop/CDN flop/CP}] \
    flop/CDN [dict create .base_pin.name DFCNQD1BWP12T40P140/CDN .net external] \
    flop/CP [dict create .base_pin.name DFCNQD1BWP12T40P140/CP .net clock] \
    clock [dict create .name clk] \
    buffer/OUT [dict create .inst buffer .name buffer/OUT .base_pin.name MASTER/OUTPUT] \
    buffer [dict create .base_cell.name MASTER .pins {INPUTS}] \
    buffer/I [dict create .base_pin.name MASTER/I .net registered] \
    buffer/Z [dict create .base_pin.name MASTER/Z]]
namespace eval tri_oracle_registered_reset34 {
    set masters [dict create DFCNQD1BWP12T40P140 1]
    set memo {}; set busy {}; set edges {}; set root_port rst_port
}
try {
    puts [tri_oracle_registered_reset34::walk buffered]
} on error {message options} {puts stderr $message; exit 1}
'''
        script = 'source {'+str(TRACE)+'}\n'+script
        script = script.replace('MASTER', master).replace('OUTPUT', output).replace('INPUTS', inputs)
        return subprocess.run(['tclsh'], input=script, text=True, capture_output=True, check=False)

    def test_verified_optimizer_buffer_preserves_registered_ancestor(self):
        for master in ['BUFFXD3BWP12T40P140','BUFFXD6BWP12T40P140','BUFFXD8BWP12T40P140','BUFFXD12BWP12T40P140','BUFFXD16BWP12T40P140']:
            with self.subTest(master=master):
                result = self.trace(master)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), '{child_rst_n_reg DFCNQD1BWP12T40P140 clk}')

    def test_existing_inverter_path_remains_supported(self):
        result = self.trace('INVD2BWP12T40P140', output='ZN')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), '{child_rst_n_reg DFCNQD1BWP12T40P140 clk}')

    def test_unverified_buffer_and_logic_gate_remain_rejected(self):
        for master in ['BUFFXD999BWP12T40P140', 'ND2D1BWP12T40P140']:
            with self.subTest(master=master):
                result = self.trace(master)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('COMBINATIONAL_DRIVER', result.stderr)

    def test_verified_buffer_requires_actual_output_and_input(self):
        result = self.trace('BUFFXD16BWP12T40P140', output='ZN')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('UNSUPPORTED_BUFFER_OUTPUT', result.stderr)
        result = self.trace('BUFFXD16BWP12T40P140', inputs='buffer/Z')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('MISSING_BUFFER_INPUT', result.stderr)

    def test_actual_library_views_prove_stateless_identity(self):
        library = ROOT/'.cache/physical/library'
        for master in ['BUFFXD3BWP12T40P140','BUFFXD6BWP12T40P140','BUFFXD8BWP12T40P140','BUFFXD12BWP12T40P140','BUFFXD16BWP12T40P140']:
            for corner in ['tt1v25c', 'ssg0p9v125c', 'ffg1p05vm40c']:
                text = (library/('tcbn28hpcplusbwp12t40p140'+corner+'.lib')).read_text()
                match = re.search(r'\bcell\s*\(\s*'+master+r'\s*\)\s*\{', text)
                self.assertIsNotNone(match)
                start = match.end(); depth = 1; end = start
                while depth:
                    depth += (text[end] == '{') - (text[end] == '}'); end += 1
                body = text[start:end-1]
                self.assertEqual(re.findall(r'\bfunction\s*:\s*"([^"]+)"', body), ['I'])
                self.assertEqual(re.findall(r'\bdirection\s*:\s*(\w+)', body), ['input', 'output'])
                self.assertNotRegex(body, r'\b(ff|latch|three_state)\b')
            text = (library/'tcbn28hpcplusbwp12t40p140.v').read_text()
            body = re.search(r'\bmodule\s+'+master+r'\s*\([^;]*\);(.*?)\bendmodule', text, re.S)[1]
            body = re.sub(r'\bspecify\b.*?\bendspecify\b', '', body, flags=re.S)
            self.assertRegex(body, r'input\s+I\s*;\s*output\s+Z\s*;\s*buf\s*\(Z,\s*I\);')



if __name__ == '__main__':
    unittest.main()
