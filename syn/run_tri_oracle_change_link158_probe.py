"""Probe native reference swapping without modifying the saved accelerator."""
import datetime
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

from tri_oracle_memory_pressure_guard import MemoryPressurePolicy, OwnedProcessPause
from tri_oracle_process_guard import terminate_process_group


RTL = '''module link_probe_leaf(input wire clk, input wire [3:0] x,y, output wire [3:0] z);
assign z=x^y;
endmodule
module link_probe_top(input wire clk, input wire [3:0] x,y, output wire [3:0] z);
link_probe_leaf child(.clk(clk),.x(x),.y(y),.z(z));
endmodule
'''
MAPPED = '''module link_probe_gate(clk,x,y,z);
input clk;
input [3:0] x,y;
output [3:0] z;
''' + ''.join('XOR2D1BWP12T40P140 g'+str(i)+'(.A1(x['+str(i)+']),.A2(y['+str(i)+']),.Z(z['+str(i)+']));\n' for i in range(4)) + 'endmodule\n'
TCL = '''set output $::env(TRI_ORACLE_LINK156_OUTPUT)
set_db fail_on_error_mesg true
set_db auto_ungroup none
set_db max_cpus_per_server 2
read_libs {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator/.cache/physical/library/tcbn28hpcplusbwp12t40p140ssg0p9v125c.lib}
read_hdl -sv $output/source.sv
elaborate link_probe_top
create_clock -name core_clock -period 1.72414 [get_ports clk]
set_clock_uncertainty 0.05 [get_clocks core_clock]
set_input_delay 0.2 -clock core_clock [get_ports {x* y*}]
set_output_delay 0.2 -clock core_clock [get_ports z*]
proc snapshot156 {filename} {
    set instances [get_db hinsts -if {.name == child}]
    if {[llength $instances]!=1} {error LINK156_CHILD_NOT_UNIQUE}
    set stream [open $filename w]
    set prefix "[get_db $instances .name]/"
    foreach pin [get_db $instances .hpins] {
        set relative [string range [get_db $pin .name] [string length $prefix] end]
        if {[string first / $relative]>=0} {continue}
        set net [get_db $pin .hnet]
        if {[llength $net]!=1} {error LINK156_DISCONNECTED_PIN}
        puts $stream "[get_db $pin .name]\\t[get_db $net .name]"
    }
    close $stream
}
snapshot156 $output/before.tsv
write_sdc > $output/before.sdc
read_hdl -netlist $output/mapped.v
elaborate link_probe_gate
current_design link_probe_top
change_link -instances [get_db hinsts -if {.name == child}] -design_name design:link_probe_gate
snapshot156 $output/after.tsv
write_sdc > $output/after.sdc
set_db [get_db hinsts -if {.name == child}] .preserve true
write_sdc > $output/preserved.sdc
if {[check_design -undriven -multiple_driver -cross_hier -status]} {error LINK156_BAD_WIRING}
set leaves [get_db [get_db designs link_probe_top] .insts]
puts "LINK156_TOP_LEAF_COUNT [llength $leaves]"
foreach leaf $leaves {puts "LINK156_LEAF [get_db $leaf .name] [get_db $leaf .base_cell.name]"}
write_hdl > $output/after.v
write_db -design link_probe_top $output/relinked.db
puts LINK156_NATIVE_REFERENCE_SWAP_COMPLETED
exit
'''


def main():
    root = Path(__file__).resolve().parents[1]
    result = root/'records/change_link158_probe_result.json'
    assert not result.exists()
    record = dict(state='preflight', supervisor_pid=os.getpid(),
                  started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  scope='Native four-XOR reference-swap API and wiring/constraint probe only; no accelerator integration claim.',
                  full_paper_results_matched=False)
    started = time.monotonic()
    child = pause = None
    stop_requested = False

    def save(**items):
        record.update(items, elapsed_seconds=time.monotonic()-started)
        temporary = result.with_suffix('.tmp')
        temporary.write_text(json.dumps(record, indent=2)+'\n')
        temporary.replace(result)

    def memory():
        available = int(next(x.split()[1] for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:')))*1024
        anonymous = int(dict(x.split() for x in Path('/sys/fs/cgroup/memory.stat').read_text().splitlines())['anon'])
        return available, anonymous

    def stop(signum, frame):
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    save()
    with tempfile.TemporaryDirectory(prefix='link156_', dir=root/'.cache/physical') as folder:
        output = Path(folder)
        try:
            available, anonymous = memory()
            assert available > 12*1024**3 and anonymous < 8*1024**3, 'Probe startup memory reserve'
            for name, text in [('source.sv', RTL), ('mapped.v', MAPPED), ('query.tcl', TCL)]:
                (output/name).write_text(text)
            log = root/'records/change_link158_probe_native.log'
            assert not log.exists()
            command = ['genus', '-no_gui', '-batch', '-log', str(output/'native'), '-files', str(output/'query.tcl')]
            with log.open('w') as stream:
                child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
                                         start_new_session=True, env=dict(os.environ, TRI_ORACLE_LINK156_OUTPUT=str(output)))
                pause = OwnedProcessPause(child, str(output/'native'))
                policy = MemoryPressurePolicy(host_reserve_bytes=5*1024**3, resume_bytes=6*1024**3, anonymous_limit_bytes=12*1024**3)
                save(state='native_reference_swap_probe_running', native_process_group=child.pid)
                while child.poll() is None:
                    assert not stop_requested and time.monotonic()-started < 180, 'Probe runtime limit'
                    available, anonymous = memory()
                    action = policy.observe(available, anonymous, time.monotonic())
                    if action == 'pause':
                        pause.pause()
                    elif action == 'resume':
                        pause.resume()
                    time.sleep(.1)
                pause.resume()
                terminate_process_group(child, log_argument=str(output/'native'))
            text = log.read_text(errors='replace')
            assert child.returncode == 0 and '\nLINK156_NATIVE_REFERENCE_SWAP_COMPLETED\n' in text, text[-3000:]
            save(before_boundary=(output/'before.tsv').read_text(), after_boundary=(output/'after.tsv').read_text(),
                 before_constraints=(output/'before.sdc').read_text(), after_constraints=(output/'after.sdc').read_text(),
                 preserved_constraints=(output/'preserved.sdc').read_text(),
                 native_tcl=TCL, source=RTL, mapped=MAPPED, exported_netlist=(output/'after.v').read_text())
            assert sorted((output/'before.tsv').read_text().splitlines()) == sorted((output/'after.tsv').read_text().splitlines()), 'Native reference swap changed the boundary ledger'
            commands = lambda path: [line.strip() for line in path.read_text().splitlines() if line.strip() and not line.lstrip().startswith('#')]
            assert commands(output/'before.sdc') == commands(output/'after.sdc'), 'Native reference swap changed exported constraint commands'
            expected_preserve='set_dont_touch [get_cells child]'
            preserved_commands=commands(output/'preserved.sdc')
            assert preserved_commands.count(expected_preserve)==1
            assert [line for line in preserved_commands if line!=expected_preserve]==commands(output/'after.sdc')
            assert len((output/'after.tsv').read_text().splitlines())==13
            assert '\nLINK156_TOP_LEAF_COUNT 4\n' in text
            save(state='native_reference_swap_wiring_and_constraints_probe_passed', native_exit_status=0,
                 boundary=(output/'after.tsv').read_text(), source=RTL, mapped=MAPPED, native_tcl=TCL,
                 exported_netlist=(output/'after.v').read_text(), rows=[line for line in text.splitlines() if line.startswith('LINK156_')])
        except BaseException as error:
            save(state='failed', exception=repr(error))
            raise
        finally:
            if child is not None:
                if pause is not None:
                    pause.resume()
                terminate_process_group(child, log_argument=str(output/'native'))
    save(temporary_build_removed=not output.exists())


if __name__ == '__main__':
    main()
