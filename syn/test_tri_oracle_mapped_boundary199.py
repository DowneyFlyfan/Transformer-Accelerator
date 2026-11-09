"""Independent acceptance/rejection cases for mapped connections and constraints."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

from tri_oracle_mapped_restore199 import constraints_equivalent, require_boundary_pin_set


MOCK = r'''
proc get_db {objects attribute} {
    global db
    set result {}
    foreach object $objects {
        if {[dict exists $db "$object,$attribute"]} {
            foreach value [dict get $db "$object,$attribute"] {lappend result $value}
        }
    }
    return $result
}
set db [dict create]
foreach {key value} {
    c,.name ctrl c,.hpins {p q}
    p,.name ctrl/out p,.direction out p,.constant no_constant
    p,.hnet {} p,.net n p,.hport.constant no_constant p,.hport.hnet.constant no_constant
    q,.name ctrl/in q,.direction in q,.net m
    n,.name flat n,.driver_pins d n,.driver_ports {} n,.load_pins l n,.load_ports {}
    m,.name another_net d,.name ctrl/driver/Z l,.name outside/load/A
    top,.name top_input op,.name top_output op,.direction out
} {dict set db $key $value}
set boundary199_stream stdout
set boundary199_inputs [dict create]
'''


def main():
    root = Path(__file__).resolve().parents[1]
    checks = []
    cases = [
        ('internal_driver_flat_output', '', 'flat_output:'),
        ('hierarchical_link', 'dict set db p,.hnet h;dict set db h,.name local_net', 'local_net'),
        ('constant_input', 'dict set db p,.direction in;dict set db p,.constant 1;dict set db p,.net {}', 'constant_input:1'),
        ('constant_one_output_without_net', 'dict set db p,.hport.constant 1;dict set db p,.net {}', 'constant_output:1'),
        ('constant_zero_internal_net', 'dict set db p,.hport.hnet.constant 0;dict set db p,.net {}', 'constant_output:0'),
        ('input_feedthrough', 'dict set db n,.driver_pins {};dict set db n,.driver_ports top;dict set db q,.net n', 'feedthrough_output:'),
        ('top_output_sink', 'dict set db n,.load_pins {};dict set db n,.load_ports op', 'flat_output:'),
        ('missing_flat_net', 'dict set db p,.net {}', None),
        ('multiple_hierarchical_nets', 'dict set db p,.hnet {h1 h2}', None),
        ('two_flat_drivers', 'dict set db n,.driver_pins {d d2}', None),
        ('undriven_flat_net', 'dict set db n,.driver_pins {}', None),
        ('internal_load_only', 'dict set db l,.name ctrl/internal/A', None),
        ('external_driver_without_feedthrough', 'dict set db d,.name outside/driver/Z', None),
        ('unknown_input', 'dict set db p,.direction in;dict set db p,.constant no_constant', None),
        ('conflicting_constants', 'dict set db p,.hport.constant 1;dict set db p,.hport.hnet.constant 0', None),
    ]
    helper = root/'syn/tri_oracle_mapped_boundary199.tcl'
    for name, changes, expected in cases:
        script = 'source $::env(TRI_ORACLE_BOUNDARY199_HELPER)\n' + MOCK + '\n' + changes + '\n'
        script += 'if {[catch {tri_oracle_boundary199_connection p c} result]} {puts "REJECTED $result"} else {puts "ACCEPTED $result"}\n'
        run = subprocess.run(['tclsh'], input=script, text=True, capture_output=True,
            env=dict(os.environ, TRI_ORACLE_BOUNDARY199_HELPER=str(helper)))
        assert run.returncode == 0 and not run.stderr, (name, run.stdout, run.stderr)
        if expected is None:
            assert 'REJECTED FRAME199_' in run.stdout and 'ACCEPTED ' not in run.stdout, (name, run.stdout)
        else:
            assert 'ACCEPTED ' + expected in run.stdout and 'REJECTED ' not in run.stdout, (name, run.stdout)
        checks.append(name)
    original = ['create_clock 1', 'set_dont_touch a', 'set_input_delay 2', 'set_dont_touch b']
    assert constraints_equivalent(original, ['create_clock 1', 'set_dont_touch b', 'set_input_delay 2', 'set_dont_touch a'])
    checks.append('preservation_subset_reorder_accepted')
    for mutated in [original+['set_dont_touch a'], original[:-1],
                    ['create_clock 2', *original[1:]], [original[2], original[1], original[0], original[3]]]:
        assert not constraints_equivalent(original, mutated)
    checks.append('duplicate_missing_changed_and_reordered_constraints_rejected')
    anchored = ['ctrl/a','ctrl/b','gate/c']
    require_boundary_pin_set(list(reversed(anchored)), anchored)
    for invalid in [anchored[:-1], ['ctrl/a','ctrl/b','gate/renamed'], ['ctrl/a','ctrl/a','gate/c']]:
        try: require_boundary_pin_set(invalid, anchored)
        except AssertionError: pass
        else: raise AssertionError('Lost, renamed or duplicate post-optimization pin accepted')
    checks.append('removed_renamed_duplicate_postopt_pins_rejected')
    files = [Path(__file__).resolve(), helper, root/'syn/tri_oracle_mapped_restore199.py']
    output = root/'records/boundary199_controls.json'
    assert not output.exists()
    output.write_text(json.dumps(dict(state='mapped_boundary_and_constraint_controls_passed', checks=checks,
        source_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
        native_hardware_executed=False, scope='Synthetic Tcl API peer and independent constraint controls only.'), indent=2)+'\n')
    print('Passed', len(checks), 'boundary/constraint control groups')


if __name__ == '__main__': main()
