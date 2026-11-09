"""Check the maximum-ID guard against the original per-row 65-bit expression."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import signal

from tri_oracle_process_guard import terminate_process_group
import time


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    root = Path(__file__).resolve().parents[1]
    result = root/'records/rowguard177_validation.json'
    assert not result.exists()
    helper = root/'verilog/tri_oracle_row_address_guard.sv'
    bench = root/'verilog/tri_oracle_row_address_guard_tb.sv'
    paths = [Path(__file__).resolve(), helper, bench, Path('/usr/local/bin/iverilog'),
             Path('/usr/local/bin/vvp'), Path('/opt/cadence/bin/xrun'),
             root/'syn/tri_oracle_process_guard.py']
    identities = {str(path): sha(path) for path in paths}
    available = int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines()
                         if line.startswith('MemAvailable:')))*1024
    assert available > 5*1024**3
    def stop(signum, frame):
        raise InterruptedError('Stop requested')
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    started = time.monotonic()
    steps = []
    with tempfile.TemporaryDirectory(prefix='rowguard177_', dir=root/'.cache/physical') as folder:
        directory = Path(folder)
        def run(command, label, positive, rows):
            assert all(sha(p) == h for p, h in identities.items())
            console = directory/(label+'_'+str(rows)+'.log')
            with console.open('w') as stream:
                execution = subprocess.Popen(command, cwd=directory, stdin=subprocess.DEVNULL,
                    stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    execution.wait(timeout=180)
                finally:
                    terminate_process_group(execution, log_argument=str(directory/'xrun.log'))
            text = console.read_text(errors='replace')
            match = re.search(r'ROW_GUARD_PASS rows='+str(rows)+r' checks=(\d+)', text)
            if positive:
                assert execution.returncode == 0 and match, text[-5000:]
            else:
                assert execution.returncode != 0 and 'ROW_GUARD_MISMATCH' in text and not match, text[-5000:]
            steps.append(dict(label=label, rows=rows, native_exit_status=execution.returncode,
                              checks=int(match[1]) if match else None, console=text))
        for rows in [1, 32, 160]:
            executable = directory/'guard.vvp'
            subprocess.run(['iverilog', '-g2012', '-s', 'tri_oracle_row_address_guard_tb',
                            '-P', 'tri_oracle_row_address_guard_tb.ROWS='+str(rows),
                            '-o', str(executable), str(helper), str(bench)], check=True,
                           cwd=directory, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
            run(['vvp', str(executable)], 'icarus_positive', True, rows)
        # Deliberately use only the first row instead of the maximum active ID.
        mutant = directory/'wrong_guard.sv'
        text = helper.read_text()
        assert text.count('maximum_id = id_tree[1];') == 1
        mutant.write_text(text.replace('maximum_id = id_tree[1];', 'maximum_id = id_tree[LEAF_COUNT];'))
        mutant_hash = sha(mutant)
        executable = directory/'wrong.vvp'
        subprocess.run(['iverilog', '-g2012', '-s', 'tri_oracle_row_address_guard_tb', '-o', str(executable),
                        str(mutant), str(bench)], check=True, cwd=directory, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, timeout=60)
        run(['vvp', str(executable)], 'wrong_first_row_rejected', False, 160)
        assert sha(mutant) == mutant_hash
        run(['/opt/cadence/bin/xrun', '-64bit', '-sv', '-top', 'tri_oracle_row_address_guard_tb',
             '-xmlibdirname', str(directory/'xcelium.d'), '-l', str(directory/'xrun.log'),
             '-history_file', str(directory/'history'), str(helper), str(bench)],
            'xcelium_positive', True, 160)
    assert all(sha(p) == h for p, h in identities.items())
    result.write_text(json.dumps(dict(state='maximum_active_row_guard_equivalence_simulations_passed',
        source_sha256=identities, elapsed_seconds=time.monotonic()-started, steps=steps,
        total_positive_checks=sum(step['checks'] or 0 for step in steps),
        scope='Known binary packet inputs; original row-wise 65-bit guard and an independent distance-to-limit calculation. '
              'All representable count values, all feature values, overflow thresholds, inactive IDs, '
              'zero stride, empty count, and deterministic randomized full-width IDs. Not a formal proof.',
        mathematical_argument=[
            'For 10-bit features, p=8*features lies between0 and8184.',
            'For unsigned16-bit row ID r, (r+1)*p is less than2^29.',
            'The 64-bit base plus this product fits65 bits; positive p therefore has no pre-subtraction wrap.',
            'For p>0, base+(r+1)*p-1 is monotone in r, so its maximum is at the largest active ID.',
            'For p=0, every active row produces the same65-bit value, including base0 underflow.',
            'Count0 suppresses the maximum check exactly as the original guarded loop.',
            'IDs outside the represented active rows are masked to0; out-of-range counts retain all original loop rows.'
        ], temporary_build_removed=True, full_paper_results_matched=False), indent=2)+'\n')
    print(result.read_text())


if __name__ == '__main__':
    main()
