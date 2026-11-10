"""Bind directed short-batch results to actual logs and unchanged hardware.

Only source functional qualification; this cannot release the paper gate.
"""
import datetime
import gzip
import hashlib
import json
from pathlib import Path
import re


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    root = Path(__file__).resolve().parents[1]
    output = root/'records/batch370_tail_qualification.json'
    archive = root/'records/batch370_native_logs.json.gz'
    assert not output.exists() and not archive.exists(), 'Preserve qualification history'
    identities = {}
    logs = {}
    groups = set()
    evidence = {}
    for mode, tokens, state in [
        ('red', [1, 3], 'missed_backpressure_coverage_reproduced'),
        ('green', [1, 3, 8, 16], 'decode_tail_and_full_batch_directed_stalls_source_passed')]:
        path = root/f'records/batch369_{mode}_result.json'
        d = json.loads(path.read_text())
        assert d['state'] == state and d['mode'] == mode
        assert d['token_counts'] == tokens and d['temporary_builds_removed'] is True
        assert d['production_hardware_unchanged'] is True
        assert all(d[k] is False for k in ['current_mapped_candidate_verified',
                   'full_model_verified', 'full_paper_results_matched'])
        evidence[str(path)] = sha(path)
        for p, digest in d['source_sha256'].items():
            assert str(Path(p).resolve()) == p and sha(p) == digest, 'Changed source '+p
            assert p not in identities or identities[p] == digest
            identities[p] = digest
        assert sorted(run['tokens'] for run in d['runs']) == tokens
        for run in d['runs']:
            n = run['tokens']
            assert run['state'] == ('expected_failure_verified' if mode == 'red' else 'passed')
            assert run['native_exit_status'] == (2 if mode == 'red' else 0)
            p = Path(run['log'])
            assert sha(p) == run['log_sha256']
            content = p.read_text()
            assert content.count('BATCH357_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=600') == 1
            inventory = re.search(r'BATCH369_INVENTORY tokens=(\d+) seen=(\d+) commands=(\d+) stalls=(\d+) directed=(\d+) first_hold_cycles=(\d+)', content)
            assert inventory
            actual = dict(zip(['tokens', 'seen', 'commands', 'stalls', 'directed', 'first_hold_cycles'],
                              map(int, inventory.groups())))
            assert actual == run['inventory']
            assert actual['tokens'] == actual['seen'] == n and actual['commands'] == n*64
            if mode == 'red':
                assert actual['stalls'] == actual['directed'] == 0
                assert 'BATCH369_FINAL_INVENTORY' in content and 'BATCH369_PASS tokens=' not in content
                assert content.count('xmsim: *F,FATSEV') == 1
            else:
                assert actual['directed'] == 1 and actual['first_hold_cycles'] == 4 and actual['stalls'] >= 4
                marker = f'BATCH369_PASS tokens={n} hidden=2048 rows=160 exact_outputs={n*160} commands={n*64} stalls={actual["stalls"]}'
                assert content.count(marker+'\n') == 1
                assert not re.search(r'\*(?:E|F),|\*ERROR|\*FATAL|Simulation terminated via \$fatal', content)
            assert not (p.parent/str(n)).exists(), 'Temporary compiled build remains'
            evidence[str(p)] = sha(p)
            logs[str(p)] = content
            groups.add(run['process_group'])
        groups.add(d['supervisor_pid'])
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            fields = (proc/'stat').read_text().rsplit(')', 1)[1].split()
            assert not (fields[0] != 'Z' and int(fields[2]) in groups), 'Owned native group still live'
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
    prior_path = root/'records/batch365_tail_result.json'
    prior = json.loads(prior_path.read_text())
    assert prior['state'] == 'failed'
    assert {run['tokens']: run['native_exit_status'] for run in prior['runs']} == {1: 2, 3: 2, 8: 0}
    assert identities[str(prior_path)] == sha(prior_path)
    bundle = json.dumps(logs, sort_keys=True, separators=(',', ':')).encode()
    archive.write_bytes(gzip.compress(bundle, mtime=0))
    assert json.loads(gzip.decompress(archive.read_bytes())) == logs
    result = dict(state='trained_decode_tail_and_full_batch_source_qualified',
        verified_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        qualifier_sha256=sha(__file__), source_sha256=identities, evidence_sha256=evidence,
        logs_archive_sha256=sha(archive), logs_archive_lossless_verified=True,
        actual_cores=20, actual_clusters=5, actual_vendor_memory_models=600,
        hidden_features=2048, output_rows=160, token_counts=[1, 3, 8, 16],
        exact_positive_output_comparisons=4480, original_red_output_comparisons=640,
        original_failure='Short periodic-ready runs exercised zero stalls despite exact arithmetic.',
        directed_first_output_stall_cycles=4, output_stability_under_stall_verified=True,
        production_hardware_unchanged=True, all_owned_workers_terminal=True,
        temporary_builds_removed=True, current_mapped_candidate_verified=False,
        external_memory_transfer_reduction_verified=False, full_model_verified=False,
        routed_timing_qualified=False, paper300_release_authorized=False,
        full_paper_results_matched=False,
        scope='Same trained first-layer raw-affine fixture and prepared per-token masks; source functional proof only. No complete feedforward, whole-model, memory-transfer, timing, power or paper-performance claim.')
    output.write_text(json.dumps(result, indent=2)+'\n')
    print('BATCH370_QUALIFIED exact_outputs=4480 token_counts=1,3,8,16 no_production_change', flush=True)


if __name__ == '__main__':
    main()
