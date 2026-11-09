"""Exercise the actual Tcl admission policy before any physical mutation."""
from pathlib import Path
import subprocess
import unittest


POLICY = Path(__file__).with_name("tri_oracle_endpoint_hold_policy.tcl")


class EndpointHoldPolicyTests(unittest.TestCase):
    def evaluate(self, body):
        self.assertTrue(POLICY.is_file(), "Endpoint hold admission policy is missing")
        script = """
proc require {condition message} {
    if {![uplevel 1 [list expr $condition]]} {error $message}
}
try {
    source [lindex $argv 0]
""" + body + """
} on error {message options} {
    puts stderr $message
    exit 1
}
"""
        # Tcl's '-' script argument leaves an extra '-' in argv; set the
        # source path directly instead so the child receives no shell parsing.
        script = script.replace("source [lindex $argv 0]", "source {" + str(POLICY) + "}")
        result = subprocess.run(["tclsh"], input=script, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "", result.stderr)

    def test_admits_measured_feedback_and_configuration_paths(self):
        self.evaluate(r'''
foreach pin {D DB SI} {
    set kind [tri_oracle_endpoint_hold_kind \
        {core/storage[28].inputs/words_reg[9][6]/CP} \
        [format {core/storage[28].inputs/words_reg[9][6]/%s} $pin] -0.011157]
    require {$kind eq "feedback"} "Measured feedback path was rejected"
}
set kind [tri_oracle_endpoint_hold_kind {cfg_weight_base[57]} {gate_base_reg[57]/D} -0.001]
require {$kind eq "configuration"} "Measured configuration path was rejected"
''')

    def test_rejects_unmeasured_paths_and_wrong_pin_roles(self):
        self.evaluate(r'''
foreach pair {
    {other/CP target/D}
    {target/Q target/D}
    {target/CP target/CP}
    {target/CP target/SE}
    {cfg_weight_base[56] gate_base_reg[56]/D}
    {cfg_weight_base[57] gate_base_reg[58]/D}
    {cfg_weight_base[57]/CP gate_base_reg[57]/D}
} {
    lassign $pair launch capture
    require {[catch {tri_oracle_endpoint_hold_kind $launch $capture -0.001}]} \
        "An unmeasured path reached the repair boundary"
}
''')

    def test_admits_only_newly_measured_output_configuration_bit(self):
        self.evaluate(r'''
require {[tri_oracle_endpoint_hold_kind {cfg_output_count[4]} {output_count_reg[4]/D} -0.0041] eq "configuration"} \
    "Freshly measured output-count configuration path was rejected"
foreach pair {
    {cfg_output_count[3] output_count_reg[3]/D}
    {cfg_output_count[4] output_count_reg[5]/D}
} {
    lassign $pair launch capture
    require {[catch {tri_oracle_endpoint_hold_kind $launch $capture -0.001}]} \
        "An unmeasured configuration path was admitted"
}
''')

    def test_rejects_nonnegative_nonfinite_and_large_hold_deficits(self):
        self.evaluate(r'''
foreach slack {0 0.001 -0.050001 NaN Inf -Inf invalid {}} {
    require {[catch {tri_oracle_endpoint_hold_kind {cell/CP} {cell/D} $slack}]} \
        "An invalid or out-of-scope hold deficit was admitted"
}
require {[tri_oracle_endpoint_hold_kind {cell/CP} {cell/D} -0.05] eq "feedback"} \
    "The inclusive lower hold bound was rejected"
''')

    def test_admits_only_two_cold_measured_external_input_paths(self):
        self.evaluate(r'''
require {[tri_oracle_endpoint_hold_kind {cfg_dense_features[13]} {dense_features_reg[13]/D} -0.005019] eq "configuration"} \
    "Measured dense-feature input path was rejected"
require {[tri_oracle_endpoint_hold_kind {norm_activations[92]} {prediction/predictor/outlier_acc_reg[0]/D} -0.001991] eq "activation"} \
    "Measured normalized-activation input path was rejected"
foreach pair {
    {cfg_dense_features[12] dense_features_reg[12]/D}
    {cfg_dense_features[13] dense_features_reg[14]/D}
    {norm_activations[91] prediction/predictor/outlier_acc_reg[0]/D}
    {norm_activations[92] prediction/predictor/outlier_acc_reg[1]/D}
    {norm_activations[92] prediction/predictor/outlier_acc_reg[0]/CP}
} {
    lassign $pair launch capture
    require {[catch {tri_oracle_endpoint_hold_kind $launch $capture -0.001}]} \
        "An unmeasured external-input path was admitted"
}
''')

    def test_requires_both_setup_views_with_finite_headroom(self):
        self.evaluate(r'''
tri_oracle_endpoint_hold_headroom {cell/D} [dict create setup_slow 0.4 setup_typ 0.8]
foreach slacks {
    {setup_slow 0.399999 setup_typ 0.8}
    {setup_slow 0.8 setup_typ -0.01}
    {setup_slow 0.8}
    {setup_typ 0.8}
    {setup_slow NaN setup_typ 0.8}
    {setup_slow Inf setup_typ 0.8}
    {setup_slow 0.8 setup_typ invalid}
} {
    require {[catch {tri_oracle_endpoint_hold_headroom {cell/D} $slacks}]} \
        "Missing or insufficient setup headroom was admitted"
}
''')

    def test_allocates_after_highest_existing_hierarchical_delay_identifier(self):
        self.evaluate(r'''
require {[tri_oracle_endpoint_hold_next_index {}] == 0} "Empty design did not start at zero"
require {[tri_oracle_endpoint_hold_next_index {
    core/storage[3].inputs/TRI_ENDPOINT_HOLD_0
    TRI_ENDPOINT_HOLD_3
    prediction/TRI_ENDPOINT_HOLD_71
    core/TRI_ENDPOINT_HOLD_12
}] == 72} "Existing hierarchical delay identifier would be reused"
foreach names {
    {TRI_ENDPOINT_HOLD_bad}
    {prefix_TRI_ENDPOINT_HOLD_72}
    {core/TRI_ENDPOINT_HOLD_07}
} {
    require {[catch {tri_oracle_endpoint_hold_next_index $names}]} \
        "Unrecognized existing delay naming was silently ignored"
}
''')

    def test_smaller_characterized_cell_has_separate_headroom_admission(self):
        self.evaluate(r'''
tri_oracle_endpoint_hold_headroom {cell/D} {setup_slow 0.388867 setup_typ 0.6} DEL025D1BWP12T40P140
tri_oracle_endpoint_hold_headroom {cell/D} {setup_slow 0.35 setup_typ 0.35} DEL025D1BWP12T40P140
require {[catch {tri_oracle_endpoint_hold_headroom {cell/D} {setup_slow 0.349999 setup_typ 0.8} DEL025D1BWP12T40P140}]} \
    "Insufficient small-cell setup reserve was admitted"
require {[catch {tri_oracle_endpoint_hold_headroom {cell/D} {setup_slow 0.388867 setup_typ 0.8} DEL100D1BWP12T40P140}]} \
    "Original large-cell reserve was relaxed"
require {[catch {tri_oracle_endpoint_hold_headroom {cell/D} {setup_slow 0.8 setup_typ 0.8} UNKNOWN_CELL}]} \
    "Uncharacterized delay cell was admitted"
''')


if __name__ == "__main__":
    unittest.main()
